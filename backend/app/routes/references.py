from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel

from ..contexte import Contexte
from ..references import GABARIT_FICHE, ErreurReference
from .commun import contexte

routeur = APIRouter(prefix="/api/references", tags=["references"])


class Activation(BaseModel):
    actif: bool


class Fiche(BaseModel):
    contenu: str


@routeur.get("")
def lister(ctx: Contexte = Depends(contexte)) -> dict:
    return {"sources": ctx.references.lister(), "fiches": ctx.references.fiches(), "gabarit": GABARIT_FICHE}


@routeur.post("", status_code=201)
async def ajouter(
    taches: BackgroundTasks,
    fichier: UploadFile | None = None,
    url: str | None = Form(None),
    mode: str = Form("a_la_demande"),
    titre: str | None = Form(None),
    ctx: Contexte = Depends(contexte),
) -> dict:
    """B-1 : ajoute un document (fichier) ou un lien (url + mode)."""
    try:
        if fichier is not None:
            contenu = await fichier.read()
            if len(contenu) > 100 * 1024 * 1024:
                raise HTTPException(413, "Document trop volumineux (100 Mo au plus).")
            identifiant = ctx.references.enregistrer_document(fichier.filename or "document", contenu)
            taches.add_task(ctx.references.convertir_document, identifiant)  # conversion et OCR en tâche de fond
        elif url:
            identifiant = ctx.references.ajouter_lien(url.strip(), mode, titre)
        else:
            raise HTTPException(400, "Fournir un fichier ou une URL.")
    except ErreurReference as erreur:
        raise HTTPException(422, str(erreur)) from erreur
    taches.add_task(ctx.synchro.apres_commit_agent)
    return ctx.references.source(identifiant)


@routeur.get("/recherche")
def rechercher(q: str, ctx: Contexte = Depends(contexte)) -> list[dict]:
    return ctx.references.rechercher(q)


@routeur.get("/fiches/{nom}")
def lire_fiche(nom: str, ctx: Contexte = Depends(contexte)) -> dict:
    try:
        contenu = ctx.references.lire_fiche(nom)
    except ErreurReference as erreur:
        raise HTTPException(400, str(erreur)) from erreur
    if contenu is None:
        raise HTTPException(404, "Fiche introuvable.")
    return {"nom": nom, "contenu": contenu}


@routeur.put("/fiches/{nom}")
def ecrire_fiche(nom: str, corps: Fiche, taches: BackgroundTasks, ctx: Contexte = Depends(contexte)) -> dict:
    try:
        with ctx.synchro.verrou:
            ctx.references.ecrire_fiche(nom, corps.contenu.rstrip() + "\n")
    except ErreurReference as erreur:
        raise HTTPException(422, str(erreur)) from erreur
    taches.add_task(ctx.synchro.apres_commit_agent)
    return lire_fiche(nom, ctx)


@routeur.delete("/fiches/{nom}", status_code=204)
def supprimer_fiche(nom: str, ctx: Contexte = Depends(contexte)) -> Response:
    try:
        ctx.references.supprimer_fiche(nom)
    except ErreurReference as erreur:
        raise HTTPException(400, str(erreur)) from erreur
    return Response(status_code=204)


@routeur.patch("/{identifiant}")
def activer(identifiant: int, corps: Activation, ctx: Contexte = Depends(contexte)) -> dict:
    try:
        ctx.references.activer(identifiant, corps.actif)
    except ErreurReference as erreur:
        raise HTTPException(404, str(erreur)) from erreur
    return ctx.references.source(identifiant)


@routeur.post("/{identifiant}/rafraichir")
def rafraichir(identifiant: int, ctx: Contexte = Depends(contexte)) -> dict:
    try:
        return ctx.references.rafraichir(identifiant)
    except ErreurReference as erreur:
        raise HTTPException(400, str(erreur)) from erreur


@routeur.delete("/{identifiant}", status_code=204)
def supprimer(identifiant: int, ctx: Contexte = Depends(contexte)) -> Response:
    try:
        ctx.references.supprimer(identifiant)
    except ErreurReference as erreur:
        raise HTTPException(400, str(erreur)) from erreur
    return Response(status_code=204)
