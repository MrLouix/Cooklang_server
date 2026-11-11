from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from ..contexte import Contexte
from ..db import maintenant, requete_fts
from ..tours import Occupe, nouvel_identifiant
from .commun import chemin_sur, contexte, sse

routeur = APIRouter(prefix="/api/discussions", tags=["discussions"])


class Creation(BaseModel):
    modele: str | None = None
    recette: str | None = None
    titre: str | None = None


class Modification(BaseModel):
    titre: str | None = None
    archivee: bool | None = None
    modele: str | None = None
    domaine: str | None = None


class Envoi(BaseModel):
    texte: str
    pieces: list[dict] = []


class Duplication(BaseModel):
    message_id: int | None = None


def _discussion(ctx: Contexte, identifiant: str) -> dict:
    d = ctx.base.ligne("SELECT * FROM discussions WHERE id = ?", (identifiant,))
    if d is None:
        raise HTTPException(404, "Discussion introuvable.")
    d["archivee"], d["titre_auto"] = bool(d["archivee"]), bool(d["titre_auto"])
    d["en_cours"] = identifiant in ctx.tours.actifs
    d["recettes"] = [
        r["chemin"] for r in ctx.base.lignes(
            "SELECT DISTINCT chemin FROM propositions WHERE discussion_id = ? AND etat = 'validee' AND cible = 'recette'", (identifiant,)
        )
    ]  # fmt: skip
    return d


def _modele(ctx: Contexte, modele: str | None) -> str:
    """Modèle demandé s'il est proposé par le moteur principal ; à défaut, son modèle par défaut."""
    proposes = ctx.moteur.modeles()
    if modele is None:
        return (
            ctx.config.modele_defaut if ctx.config.modele_defaut in proposes or not proposes else proposes[0]
        )
    if modele not in proposes:
        raise HTTPException(400, "Modèle inconnu.")
    return modele


@routeur.get("")
def lister(q: str = "", archivees: bool = False, ctx: Contexte = Depends(contexte)) -> list[dict]:
    """D-1 : tri par dernière activité, recherche par titre et par contenu."""
    extraits: dict[str, str] = {}
    if q.strip():
        ids = {
            d["id"]
            for d in ctx.base.lignes("SELECT id FROM discussions WHERE titre LIKE ?", (f"%{q.strip()}%",))
        }
        requete = requete_fts(q)
        if requete:
            for ligne in ctx.base.lignes(
                "SELECT m.discussion_id AS id, snippet(messages_fts, 0, '**', '**', '…', 16) AS extrait "
                "FROM messages_fts JOIN messages m ON m.id = messages_fts.rowid WHERE messages_fts MATCH ? ORDER BY rank LIMIT 200",
                (requete,),
            ):
                extraits.setdefault(ligne["id"], ligne["extrait"])
        ids |= set(extraits)
    lignes = ctx.base.lignes(
        "SELECT id FROM discussions WHERE archivee = ? ORDER BY modifie_le DESC, cree_le DESC",
        (int(archivees),),
    )
    resultat = []
    for ligne in lignes:
        if q.strip() and ligne["id"] not in ids:
            continue
        d = _discussion(ctx, ligne["id"])
        d["extrait"] = extraits.get(ligne["id"])
        resultat.append(d)
    return resultat


@routeur.post("", status_code=201)
def creer(corps: Creation, ctx: Contexte = Depends(contexte)) -> dict:
    recette = None
    if corps.recette:
        recette = chemin_sur(ctx.recettes, corps.recette)
        if ctx.recettes.lire(recette) is None:
            raise HTTPException(404, "Recette introuvable.")
    identifiant, instant = nouvel_identifiant(), maintenant()
    titre = corps.titre or (
        f"À propos de {recette.rsplit('/', 1)[-1].removesuffix('.cook')}"
        if recette
        else "Nouvelle discussion"
    )
    ctx.base.executer(
        "INSERT INTO discussions(id, titre, titre_auto, modele, recette_contexte, cree_le, modifie_le) VALUES(?, ?, ?, ?, ?, ?, ?)",
        (
            identifiant,
            titre,
            int(not corps.titre and not recette),
            _modele(ctx, corps.modele),
            recette,
            instant,
            instant,
        ),
    )
    return _discussion(ctx, identifiant)


@routeur.get("/{identifiant}")
def lire(identifiant: str, ctx: Contexte = Depends(contexte)) -> dict:
    """D-3 : tout l'historique vient de la base, indépendamment des fichiers du CLI."""
    d = _discussion(ctx, identifiant)
    ids = ctx.base.lignes("SELECT id FROM messages WHERE discussion_id = ? ORDER BY id", (identifiant,))
    d["messages"] = [ctx.tours.message(m["id"]) for m in ids]
    return d


@routeur.patch("/{identifiant}")
def modifier(identifiant: str, corps: Modification, ctx: Contexte = Depends(contexte)) -> dict:
    _discussion(ctx, identifiant)
    if corps.titre is not None:
        titre = " ".join(corps.titre.split())[:120]
        if not titre:
            raise HTTPException(400, "Le titre ne peut pas être vide.")
        ctx.base.executer(
            "UPDATE discussions SET titre = ?, titre_auto = 0 WHERE id = ?", (titre, identifiant)
        )
    if corps.archivee is not None:
        ctx.base.executer(
            "UPDATE discussions SET archivee = ? WHERE id = ?", (int(corps.archivee), identifiant)
        )
    if corps.modele is not None:
        ctx.base.executer(
            "UPDATE discussions SET modele = ? WHERE id = ?", (_modele(ctx, corps.modele), identifiant)
        )
    if corps.domaine is not None:
        ctx.base.executer(
            "UPDATE discussions SET domaine = ? WHERE id = ?", (corps.domaine or None, identifiant)
        )
    return _discussion(ctx, identifiant)


@routeur.delete("/{identifiant}", status_code=204)
def supprimer(identifiant: str, ctx: Contexte = Depends(contexte)) -> Response:
    _discussion(ctx, identifiant)
    if identifiant in ctx.tours.actifs:
        raise HTTPException(409, "Une réponse est en cours dans cette discussion.")
    ctx.base.executer(
        "DELETE FROM messages_fts WHERE rowid IN (SELECT id FROM messages WHERE discussion_id = ?)",
        (identifiant,),
    )
    ctx.base.executer("DELETE FROM discussions WHERE id = ?", (identifiant,))
    return Response(status_code=204)


@routeur.post("/{identifiant}/dupliquer", status_code=201)
def dupliquer(identifiant: str, corps: Duplication, ctx: Contexte = Depends(contexte)) -> dict:
    """D-5 : copie l'historique jusqu'au message donné ; la session CLI sera recréée au premier tour (D-4)."""
    source = _discussion(ctx, identifiant)
    limite = corps.message_id or 10**18
    nouveau, instant = nouvel_identifiant(), maintenant()
    ctx.base.executer(
        "INSERT INTO discussions(id, titre, titre_auto, modele, domaine, recette_contexte, cree_le, modifie_le) VALUES(?, ?, 0, ?, ?, ?, ?, ?)",
        (
            nouveau,
            f"{source['titre']} (copie)"[:120],
            source["modele"],
            source["domaine"],
            source["recette_contexte"],
            instant,
            instant,
        ),
    )
    for m in ctx.base.lignes(
        "SELECT * FROM messages WHERE discussion_id = ? AND id <= ? AND etat = 'termine' ORDER BY id",
        (identifiant, limite),
    ):
        contenu = ctx.propositions.developper(m["contenu"]) if m["role"] == "assistant" else m["contenu"]
        curseur = ctx.base.executer(
            "INSERT INTO messages(discussion_id, role, contenu, pieces, outils, etat, cree_le) VALUES(?, ?, '', ?, ?, 'termine', ?)",
            (nouveau, m["role"], m["pieces"], m["outils"], m["cree_le"]),
        )
        if m["role"] == "assistant":
            contenu, _ = ctx.propositions.extraire(contenu, curseur.lastrowid, nouveau)
            ctx.base.executer(
                "UPDATE propositions SET etat = 'rejetee', traite_le = ? WHERE message_id = ?",
                (instant, curseur.lastrowid),
            )
        ctx.base.executer("UPDATE messages SET contenu = ? WHERE id = ?", (contenu, curseur.lastrowid))
        ctx.base.executer(
            "INSERT INTO messages_fts(rowid, contenu) VALUES(?, ?)", (curseur.lastrowid, contenu)
        )
    return _discussion(ctx, nouveau)


@routeur.post("/{identifiant}/messages")
async def envoyer(identifiant: str, corps: Envoi, ctx: Contexte = Depends(contexte)):
    """Envoie un message ; la réponse arrive en SSE. Le tour continue si le client se déconnecte (P-3)."""
    if not corps.texte.strip() and not corps.pieces:
        raise HTTPException(400, "Message vide.")
    pieces = []
    for piece in corps.pieces:
        fichier = str(piece.get("fichier", ""))
        if "/" in fichier or not (ctx.config.agent / "pieces" / fichier).is_file():
            raise HTTPException(400, "Pièce jointe inconnue.")
        pieces.append(
            {
                "fichier": fichier,
                "nom": str(piece.get("nom", fichier))[:200],
                "type": str(piece.get("type", ""))[:100],
            }
        )
    try:
        tour = ctx.tours.soumettre(identifiant, corps.texte.strip(), pieces)
    except KeyError:
        raise HTTPException(404, "Discussion introuvable.") from None
    except Occupe:
        raise HTTPException(409, "Une réponse est déjà en cours dans cette discussion.") from None
    return sse(ctx.tours.flux(tour))


@routeur.get("/{identifiant}/flux")
async def flux(identifiant: str, ctx: Contexte = Depends(contexte)):
    """Se réabonner au tour en cours (retour de veille) ; 204 s'il n'y en a pas."""
    tour = ctx.tours.actifs.get(identifiant)
    if tour is None:
        return Response(status_code=204)
    return sse(ctx.tours.flux(tour))
