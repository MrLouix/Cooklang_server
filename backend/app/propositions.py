"""Propositions (F-5 à F-9, F-12, B-8) : extraction des blocs, validation, écriture, commit."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from . import cooklang
from .db import maintenant
from .depots import CheminInvalide, Depot
from .initialisation import FICHIERS_MEMOIRE
from .parametres import verifier_exclusions
from .references import ErreurReference, nom_sur, valider_fiche

BLOC = re.compile(r"(?ms)^(`{3,})proposition[ \t]*\n(.*?)^\1[ \t]*$")
MARQUEUR = re.compile(r"\[\[proposition:(\d+)\]\]")
CIBLES = ("recette", "memoire", "fiche")
TYPES = ("creation", "modification", "variante")


class Refus(Exception):
    """Refus de validation : `statut` HTTP, `code` lisible par la PWA, `details` affichables."""

    def __init__(self, statut: int, code: str, message: str, **details):
        super().__init__(message)
        self.statut, self.code, self.message, self.details = statut, code, message, details


def analyser_bloc(corps: str) -> dict | None:
    entete, separateur, contenu = corps.partition("\n---\n")
    if not separateur:
        return None
    champs = {}
    for ligne in entete.strip().splitlines():
        cle, _, valeur = ligne.partition(":")
        champs[cle.strip().lower()] = valeur.strip()
    cible = champs.get("cible", "recette").lower()
    genre = champs.get("type", "creation").lower().replace("é", "e")
    chemin = champs.get("chemin", "").strip("`'\" ").replace("\\", "/")
    if cible not in CIBLES or genre not in TYPES or not chemin or not contenu.strip():
        return None
    return {"cible": cible, "type": genre, "chemin": chemin, "contenu": contenu.rstrip() + "\n"}


def normaliser_chemin(cible: str, chemin: str) -> str:
    p = PurePosixPath(chemin)
    if p.is_absolute() or ".." in p.parts or any(part.startswith(".") for part in p.parts):
        raise CheminInvalide(f"Chemin refusé : {chemin}")
    if cible == "recette":
        if p.suffix != ".cook" or len(p.parts) < 2:
            raise CheminInvalide("Une recette s'écrit dans `<Catégorie>/<Nom>.cook`.")
    elif cible == "memoire":
        if len(p.parts) != 2 or p.parts[0] != "memoire" or p.name not in FICHIERS_MEMOIRE:
            raise CheminInvalide(
                "La mémoire se limite à : " + ", ".join(f"memoire/{f}" for f in FICHIERS_MEMOIRE) + "."
            )
    elif cible == "fiche":
        if len(p.parts) != 3 or p.parts[:2] != ("references", "fiches") or p.suffix != ".md":
            raise CheminInvalide("Une fiche s'écrit dans `references/fiches/<nom>.md`.")
        return f"references/fiches/{nom_sur(p.stem)}.md"
    return str(p)


class Propositions:
    def __init__(self, ctx):
        self.ctx = ctx

    def depot(self, cible: str) -> Depot:
        return self.ctx.recettes if cible == "recette" else self.ctx.agent

    # --- extraction en fin de tour ---------------------------------------
    def extraire(self, texte: str, message_id: int, discussion_id: str) -> tuple[str, list[dict]]:
        """Remplace chaque bloc valide par un marqueur `[[proposition:ID]]` et l'enregistre en attente."""
        creees: list[dict] = []

        def remplacer(trouve: re.Match) -> str:
            bloc = analyser_bloc(trouve.group(2))
            if bloc is None:
                return trouve.group(0)
            try:
                bloc["chemin"] = normaliser_chemin(bloc["cible"], bloc["chemin"])
                base = self.depot(bloc["cible"]).empreinte(bloc["chemin"])
            except (CheminInvalide, ErreurReference):
                return trouve.group(0)
            curseur = self.ctx.base.executer(
                "INSERT INTO propositions(message_id, discussion_id, cible, type, chemin, contenu, sha_base, cree_le) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    message_id,
                    discussion_id,
                    bloc["cible"],
                    bloc["type"],
                    bloc["chemin"],
                    bloc["contenu"],
                    base,
                    maintenant(),
                ),
            )
            creees.append(self.vue(curseur.lastrowid))
            return f"[[proposition:{curseur.lastrowid}]]"

        return BLOC.sub(remplacer, texte), creees

    def developper(self, texte: str) -> str:
        """Opération inverse, pour réinjecter l'historique dans une nouvelle session (D-4)."""

        def remplacer(trouve: re.Match) -> str:
            p = self.ctx.base.ligne("SELECT * FROM propositions WHERE id = ?", (int(trouve.group(1)),))
            if not p:
                return ""
            return f"````proposition\ncible: {p['cible']}\ntype: {p['type']}\nchemin: {p['chemin']}\n---\n{p['contenu']}````"

        return MARQUEUR.sub(remplacer, texte)

    # --- lecture ----------------------------------------------------------
    def vue(self, identifiant: int) -> dict:
        p = self.ctx.base.ligne("SELECT * FROM propositions WHERE id = ?", (identifiant,))
        if not p:
            raise Refus(404, "introuvable", "Proposition introuvable.")
        if p["etat"] == "en_attente":
            actuel = self.depot(p["cible"]).lire(p["chemin"])
            p["original"] = actuel
            p["existe"] = actuel is not None
            p["fichier_modifie"] = self.depot(p["cible"]).empreinte(p["chemin"]) != p["sha_base"]
        return p

    def du_message(self, message_id: int) -> list[dict]:
        ids = self.ctx.base.lignes(
            "SELECT id FROM propositions WHERE message_id = ? ORDER BY id", (message_id,)
        )
        return [self.vue(i["id"]) for i in ids]

    # --- actions ----------------------------------------------------------
    def rejeter(self, identifiant: int) -> dict:
        p = self.vue(identifiant)
        if p["etat"] != "en_attente":
            raise Refus(409, "deja_traitee", "Cette proposition a déjà été traitée.")
        self.ctx.base.executer(
            "UPDATE propositions SET etat = 'rejetee', traite_le = ? WHERE id = ?",
            (maintenant(), identifiant),
        )
        return self.vue(identifiant)

    def valider(self, identifiant: int, confirmer_exclusions: bool = False, forcer: bool = False) -> dict:
        ctx = self.ctx
        p = self.vue(identifiant)
        if p["etat"] != "en_attente":
            raise Refus(409, "deja_traitee", "Cette proposition a déjà été traitée.")
        depot, chemin, contenu = self.depot(p["cible"]), p["chemin"], p["contenu"]
        avertissements: list[str] = []

        # 1. Validation du contenu (F-7, B-8).
        if p["cible"] == "recette":
            analyse = cooklang.analyser(contenu, ctx.config.outils_node)
            if not analyse.valide:
                self._noter_erreur(identifiant, "; ".join(analyse.erreurs))
                raise Refus(
                    422, "syntaxe", "Le fichier Cooklang est invalide.", erreurs=analyse.erreurs,
                    message_assistant=(
                        f"La validation Cooklang de `{chemin}` a échoué, le fichier n'a pas été enregistré :\n"
                        + "\n".join(f"- {e}" for e in analyse.erreurs)
                        + "\n\nCorrige et propose de nouveau le fichier complet."
                    ),
                )  # fmt: skip
            avertissements = analyse.avertissements
            # 2. Exclusions strictes (PA-5).
            alertes = verifier_exclusions(
                ctx.parametres.lire(), analyse.ingredients, ctx.parametres.synonymes()
            )
            if alertes and not confirmer_exclusions:
                raise Refus(
                    409,
                    "exclusions",
                    "La recette contient un ingrédient en exclusion stricte.",
                    alertes=alertes,
                )
        elif p["cible"] == "fiche":
            erreurs = valider_fiche(contenu)
            if erreurs:
                raise Refus(422, "gabarit", "La fiche ne respecte pas le gabarit.", erreurs=erreurs)

        discussion = ctx.base.ligne("SELECT titre FROM discussions WHERE id = ?", (p["discussion_id"],))
        libelle = {"creation": "Création", "modification": "Modification", "variante": "Variante"}[p["type"]]
        message = f"{libelle} : {chemin}\n\nDiscussion : {discussion['titre'] if discussion else '?'} ({p['discussion_id']})"

        with ctx.synchro.verrou:
            conflits: list[str] = []
            # 3. Contrôle de divergence avec Drive (S-3, S-4).
            if p["cible"] == "recette":
                try:
                    conflits = ctx.synchro.importer_externes(cible_ecriture=chemin)["conflits"]
                except Exception as erreur:  # noqa: BLE001 — Drive injoignable : on écrit quand même, c'est journalisé
                    ctx.synchro.journaliser(
                        "drive", "echec", erreur=f"Contrôle de divergence impossible : {erreur}"[:500]
                    )
                    avertissements.append(
                        "Contrôle de divergence avec Drive impossible ; il sera rejoué à la prochaine synchro."
                    )
            # 4. Le fichier a-t-il changé depuis la proposition ? Jamais d'écrasement silencieux (F-9).
            if depot.empreinte(chemin) != p["sha_base"] and not forcer:
                raise Refus(
                    409, "fichier_modifie",
                    "Le fichier a changé depuis la proposition. Vérifie le diff, puis confirme ou demande une correction.",
                    original=depot.lire(chemin),
                )  # fmt: skip
            # 5. Écriture et commit (F-8).
            if p["cible"] == "fiche":
                sha = ctx.references.ecrire_fiche(PurePosixPath(chemin).stem, contenu, message)
            else:
                sha = depot.ecrire(chemin, contenu, message)
            ctx.base.executer(
                "UPDATE propositions SET etat = 'validee', commit_sha = ?, erreur = NULL, traite_le = ? WHERE id = ?",
                (sha, maintenant(), identifiant),
            )
        return {
            "proposition": self.vue(identifiant),
            "commit": sha,
            "conflits": conflits,
            "avertissements": avertissements,
        }

    def _noter_erreur(self, identifiant: int, erreur: str) -> None:
        self.ctx.base.executer(
            "UPDATE propositions SET erreur = ? WHERE id = ?", (erreur[:1000], identifiant)
        )
