"""Propositions, mémoire, synchro, quota, paramètres, pièces jointes, santé, connexion."""

from __future__ import annotations

import hmac
import mimetypes
import secrets
import shutil
import subprocess
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .. import parametres as mod_parametres
from ..config import MODELES
from ..contexte import Contexte
from ..db import maintenant
from ..initialisation import FICHIERS_MEMOIRE
from ..propositions import Refus
from .commun import contexte

routeur = APIRouter(prefix="/api")

# --- propositions -----------------------------------------------------------


def _refus(refus: Refus) -> JSONResponse:
    return JSONResponse({"code": refus.code, "message": refus.message, **refus.details}, status_code=refus.statut)


@routeur.get("/propositions/{identifiant}")
def lire_proposition(identifiant: int, ctx: Contexte = Depends(contexte)):
    try:
        return ctx.propositions.vue(identifiant)
    except Refus as refus:
        return _refus(refus)


@routeur.post("/propositions/{identifiant}/valider")
def valider_proposition(
    identifiant: int, taches: BackgroundTasks, confirmer_exclusions: bool = False, forcer: bool = False,
    ctx: Contexte = Depends(contexte),
):  # fmt: skip
    """Valider, écrire, commiter, puis synchroniser en tâche de fond."""
    try:
        resultat = ctx.propositions.valider(identifiant, confirmer_exclusions, forcer)
    except Refus as refus:
        return _refus(refus)
    cible = resultat["proposition"]["cible"]
    taches.add_task(ctx.synchro.apres_commit if cible == "recette" else ctx.synchro.apres_commit_agent)
    return resultat


@routeur.post("/propositions/{identifiant}/rejeter")
def rejeter_proposition(identifiant: int, ctx: Contexte = Depends(contexte)):
    try:
        return ctx.propositions.rejeter(identifiant)
    except Refus as refus:
        return _refus(refus)


# --- mémoire (F-11, F-12) ---------------------------------------------------


class Texte(BaseModel):
    contenu: str


@routeur.get("/memoire")
def lister_memoire(ctx: Contexte = Depends(contexte)) -> list[dict]:
    return [{"fichier": f, "contenu": ctx.agent.lire(f"memoire/{f}") or ""} for f in FICHIERS_MEMOIRE]


@routeur.get("/memoire/{fichier}")
def lire_memoire(fichier: str, ctx: Contexte = Depends(contexte)) -> dict:
    if fichier not in FICHIERS_MEMOIRE:
        raise HTTPException(404, "Fichier de mémoire inconnu.")
    return {"fichier": fichier, "contenu": ctx.agent.lire(f"memoire/{fichier}") or ""}


@routeur.put("/memoire/{fichier}")
def ecrire_memoire(fichier: str, corps: Texte, taches: BackgroundTasks, ctx: Contexte = Depends(contexte)) -> dict:
    if fichier not in FICHIERS_MEMOIRE:
        raise HTTPException(404, "Fichier de mémoire inconnu.")
    with ctx.synchro.verrou:
        ctx.agent.ecrire(f"memoire/{fichier}", corps.contenu.rstrip() + "\n", f"Mémoire modifiée : {fichier}")
    taches.add_task(ctx.synchro.apres_commit_agent)
    return lire_memoire(fichier, ctx)


# --- synchro (S-5) et quota (M-6) -------------------------------------------


@routeur.get("/synchro")
def lire_synchro(ctx: Contexte = Depends(contexte)) -> dict:
    return {"etat": ctx.synchro.etat(), "journal": ctx.synchro.journal()}


@routeur.post("/synchro")
def relancer_synchro(ctx: Contexte = Depends(contexte)) -> dict:
    return {"bilan": ctx.synchro.resynchroniser(), **lire_synchro(ctx)}


@routeur.get("/quota")
def quota(ctx: Contexte = Depends(contexte)) -> dict:
    mois = maintenant()[:7]
    total = ctx.base.ligne("SELECT coalesce(sum(cout), 0) AS c, count(*) AS n FROM messages WHERE role = 'assistant' AND cree_le LIKE ?", (f"{mois}%",))
    historique = ctx.base.lignes(
        "SELECT substr(cree_le, 1, 7) AS mois, round(sum(cout), 4) AS cout, count(*) AS tours FROM messages "
        "WHERE role = 'assistant' GROUP BY 1 ORDER BY 1 DESC LIMIT 12"
    )
    return {
        "mois": mois, "cout": round(total["c"], 4), "tours": total["n"], "credit": ctx.config.credit_mensuel,
        "atteint": ctx.base.meta("quota_atteint") == mois, "historique": historique,
    }  # fmt: skip


# --- paramètres (PA-8) ------------------------------------------------------


@routeur.get("/parametres")
def lire_parametres(ctx: Contexte = Depends(contexte)) -> dict:
    return {"valeurs": ctx.parametres.lire(), "defauts": mod_parametres.defauts()}


@routeur.get("/parametres/schema")
def schema_parametres() -> dict:
    return mod_parametres.SCHEMA


@routeur.put("/parametres")
def ecrire_parametres(valeurs: dict, taches: BackgroundTasks, ctx: Contexte = Depends(contexte)) -> dict:
    try:
        with ctx.synchro.verrou:
            propres = ctx.parametres.enregistrer(valeurs)
    except mod_parametres.ParametresInvalides as erreur:
        raise HTTPException(422, str(erreur)) from erreur
    taches.add_task(ctx.synchro.apres_commit_agent)
    return {"valeurs": propres, "defauts": mod_parametres.defauts()}


# --- pièces jointes (F-4) ---------------------------------------------------

TYPES_PIECES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf", ".txt", ".md", ".cook"}
TAILLE_MAX = 15 * 1024 * 1024


@routeur.post("/pieces", status_code=201)
async def deposer_piece(fichier: UploadFile, ctx: Contexte = Depends(contexte)) -> dict:
    extension = Path(fichier.filename or "").suffix.lower()
    if extension not in TYPES_PIECES:
        raise HTTPException(415, "Type de fichier refusé (images, PDF, texte, .cook).")
    contenu = await fichier.read(TAILLE_MAX + 1)
    if len(contenu) > TAILLE_MAX:
        raise HTTPException(413, "Fichier trop volumineux (15 Mo au plus).")
    nom = f"{uuid.uuid4().hex}{extension}"
    (ctx.config.agent / "pieces" / nom).write_bytes(contenu)
    return {"fichier": nom, "nom": fichier.filename, "type": fichier.content_type or mimetypes.guess_type(nom)[0] or ""}


@routeur.get("/pieces/{nom}")
def lire_piece(nom: str, ctx: Contexte = Depends(contexte)):
    chemin = ctx.config.agent / "pieces" / nom
    if "/" in nom or nom.startswith(".") or not chemin.is_file():
        raise HTTPException(404, "Pièce introuvable.")
    return FileResponse(chemin)


# --- santé ------------------------------------------------------------------


def _version(*commande: str) -> str:
    if not shutil.which(commande[0]):
        return "absent"
    try:
        sortie = subprocess.run(commande, capture_output=True, text=True, timeout=10).stdout.strip().splitlines()
        return sortie[0] if sortie else "?"
    except (OSError, subprocess.TimeoutExpired):
        return "erreur"


@routeur.get("/sante")
async def sante(ctx: Contexte = Depends(contexte)) -> dict:
    return {
        "etat": "ok",
        "moteur": ctx.moteur.nom,
        "cli": await ctx.moteur.version(),
        "git": _version("git", "--version"),
        "rclone": _version("rclone", "version"),
        "node": _version("node", "--version"),
        "ocr": shutil.which("tesseract") is not None,
        "modeles": MODELES,
        "modele_defaut": ctx.config.modele_defaut,
        "domaines": ctx.parametres.domaines(),
        "file": ctx.tours.file.qsize(),
    }


# --- connexion (X-2) --------------------------------------------------------

COOKIE = "ac_session"


class Connexion(BaseModel):
    mot_de_passe: str


def jetons(ctx: Contexte) -> set[str]:
    return set(filter(None, (ctx.base.meta("sessions", "") or "").split(",")))


def est_connecte(request: Request, ctx: Contexte) -> bool:
    if not ctx.config.mot_de_passe:
        return True
    return request.cookies.get(COOKIE, "") in jetons(ctx)


@routeur.get("/session")
def session(request: Request, ctx: Contexte = Depends(contexte)) -> dict:
    return {"protege": bool(ctx.config.mot_de_passe), "connecte": est_connecte(request, ctx)}


@routeur.post("/connexion")
def connexion(corps: Connexion, response: Response, ctx: Contexte = Depends(contexte)) -> dict:
    if not ctx.config.mot_de_passe:
        return {"connecte": True}
    if not hmac.compare_digest(corps.mot_de_passe.encode(), ctx.config.mot_de_passe.encode()):
        raise HTTPException(401, "Mot de passe incorrect.")
    jeton = secrets.token_urlsafe(32)
    ctx.base.definir_meta("sessions", ",".join([*list(jetons(ctx))[-9:], jeton]))
    response.set_cookie(COOKIE, jeton, max_age=180 * 86400, httponly=True, samesite="strict", secure=True)
    return {"connecte": True}


@routeur.post("/deconnexion")
def deconnexion(request: Request, response: Response, ctx: Contexte = Depends(contexte)) -> dict:
    ctx.base.definir_meta("sessions", ",".join(jetons(ctx) - {request.cookies.get(COOKIE, "")}))
    response.delete_cookie(COOKIE)
    return {"connecte": False}
