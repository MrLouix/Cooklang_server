from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from ..contexte import Contexte
from ..parametres import normaliser
from .commun import chemin_sur, contexte

routeur = APIRouter(prefix="/api/recettes", tags=["recettes"])


class Restauration(BaseModel):
    sha: str


def _recettes(ctx: Contexte) -> list[str]:
    racine = ctx.recettes.racine
    return sorted(
        str(f.relative_to(racine)) for f in racine.rglob("*.cook") if not any(p.startswith(".") for p in f.relative_to(racine).parts)
    )


def _existant(ctx: Contexte, chemin: str) -> str:
    chemin_sur(ctx.recettes, chemin)
    if not chemin.endswith(".cook") or ctx.recettes.lire(chemin) is None:
        raise HTTPException(404, "Recette introuvable.")
    return chemin


@routeur.get("")
def arborescence(q: str = "", ctx: Contexte = Depends(contexte)) -> dict:
    """F-10 : navigation par catégorie et recherche plein texte."""
    mots = [normaliser(m) for m in q.split() if m]
    categories: dict[str, list[dict]] = {}
    for chemin in _recettes(ctx):
        categorie, _, nom = chemin.rpartition("/")
        entree = {"chemin": chemin, "nom": nom.removesuffix(".cook"), "conflit": ".conflit-" in nom}
        if mots:
            contenu = ctx.recettes.lire(chemin) or ""
            cible = normaliser(chemin + "\n" + contenu)
            if not all(m in cible for m in mots):
                continue
            for ligne in contenu.splitlines():
                if mots[0] in normaliser(ligne):
                    entree["extrait"] = ligne.strip()[:160]
                    break
        categories.setdefault(categorie or "Sans catégorie", []).append(entree)
    return {"categories": [{"nom": nom, "recettes": recettes} for nom, recettes in sorted(categories.items())]}


@routeur.get("/{chemin:path}/historique")
def historique(chemin: str, ctx: Contexte = Depends(contexte)) -> list[dict]:
    return ctx.recettes.historique(_existant(ctx, chemin))


@routeur.get("/{chemin:path}/version/{sha}")
def version(chemin: str, sha: str, ctx: Contexte = Depends(contexte)) -> dict:
    contenu = ctx.recettes.version(chemin_sur(ctx.recettes, chemin), sha)
    if contenu is None:
        raise HTTPException(404, "Version introuvable.")
    return {"chemin": chemin, "sha": sha, "contenu": contenu}


@routeur.get("/{chemin:path}/discussions")
def discussions(chemin: str, ctx: Contexte = Depends(contexte)) -> list[dict]:
    """D-6 : discussions qui ont créé ou modifié la recette."""
    return ctx.base.lignes(
        "SELECT DISTINCT d.id, d.titre, d.modifie_le, p.type, p.commit_sha, p.traite_le FROM propositions p "
        "JOIN discussions d ON d.id = p.discussion_id WHERE p.chemin = ? AND p.cible = 'recette' AND p.etat = 'validee' ORDER BY p.traite_le DESC",
        (chemin,),
    )


@routeur.post("/{chemin:path}/restaurer")
def restaurer(chemin: str, corps: Restauration, taches: BackgroundTasks, ctx: Contexte = Depends(contexte)) -> dict:
    """F-8 : restaure une version par un nouveau commit, sans réécrire l'historique."""
    chemin_sur(ctx.recettes, chemin)
    with ctx.synchro.verrou:
        try:
            sha = ctx.recettes.restaurer(chemin, corps.sha)
        except Exception as erreur:  # noqa: BLE001
            raise HTTPException(400, str(erreur)) from erreur
    taches.add_task(ctx.synchro.apres_commit)
    return {"chemin": chemin, "commit": sha, "contenu": ctx.recettes.lire(chemin)}


@routeur.get("/{chemin:path}")
def lire(chemin: str, ctx: Contexte = Depends(contexte)) -> dict:
    chemin = _existant(ctx, chemin)
    return {
        "chemin": chemin,
        "contenu": ctx.recettes.lire(chemin),
        "historique": ctx.recettes.historique(chemin),
        "discussions": discussions(chemin, ctx),
    }
