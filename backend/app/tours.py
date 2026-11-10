"""Tours de conversation : file d'attente (M-5), délai (M-7), diffusion SSE et reprise (P-3, D-4)."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator

from . import consignes
from .db import decoder, maintenant
from .moteur.base import MESSAGES_ERREUR, Demande, Evenement
from .parametres import detecter_domaine

journal = logging.getLogger("aide-culinaire.tours")

TRANSVERSAUX = ("Matériel", "Forme des réponses")
HISTORIQUE_MAX = 60_000


class Occupe(Exception):
    pass


class Tour:
    def __init__(self, message_id: int, discussion_id: str, question: str):
        self.message_id = message_id
        self.discussion_id = discussion_id
        self.question = question
        self.texte = ""
        self.outils: list[dict] = []
        self.abonnes: set[asyncio.Queue] = set()
        self.final: tuple[str, dict] | None = None
        self.debut = time.monotonic()

    def publier(self, genre: str, donnees: dict) -> None:
        if genre in ("fin", "erreur"):
            self.final = (genre, donnees)
        for file in self.abonnes:
            file.put_nowait((genre, donnees))


class Gestionnaire:
    def __init__(self, ctx):
        self.ctx = ctx
        self.file: asyncio.Queue[Tour] = asyncio.Queue()
        self.actifs: dict[str, Tour] = {}  # par discussion
        self._tache: asyncio.Task | None = None

    # --- cycle de vie -----------------------------------------------------
    def demarrer(self) -> None:
        # Un tour interrompu par un redémarrage ne reprendra pas : on le dit clairement.
        self.ctx.base.executer("UPDATE messages SET etat = 'erreur', erreur = 'interrompu' WHERE etat = 'en_cours'")
        self.file, self.actifs = asyncio.Queue(), {}
        self._tache = asyncio.create_task(self._boucle())

    async def arreter(self) -> None:
        if self._tache:
            self._tache.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._tache

    async def _boucle(self) -> None:
        while True:
            tour = await self.file.get()
            try:
                await self._executer(tour)
            except asyncio.CancelledError:
                raise
            except Exception as erreur:  # noqa: BLE001 — un tour raté ne doit pas arrêter la file
                journal.exception("Tour %s en échec", tour.message_id)
                self._echec(tour, Evenement("erreur", code="moteur", texte=str(erreur)))
            finally:
                self.actifs.pop(tour.discussion_id, None)

    # --- soumission -------------------------------------------------------
    def soumettre(self, discussion_id: str, texte: str, pieces: list[dict] | None = None) -> Tour:
        base = self.ctx.base
        discussion = base.ligne("SELECT * FROM discussions WHERE id = ?", (discussion_id,))
        if discussion is None:
            raise KeyError(discussion_id)
        if discussion_id in self.actifs:
            raise Occupe()
        pieces = pieces or []
        premier = base.ligne("SELECT count(*) AS n FROM messages WHERE discussion_id = ?", (discussion_id,))["n"] == 0
        instant = maintenant()
        curseur = base.executer(
            "INSERT INTO messages(discussion_id, role, contenu, pieces, cree_le) VALUES(?, 'user', ?, ?, ?)",
            (discussion_id, texte, json.dumps(pieces, ensure_ascii=False), instant),
        )
        base.executer("INSERT INTO messages_fts(rowid, contenu) VALUES(?, ?)", (curseur.lastrowid, texte))
        reponse = base.executer(
            "INSERT INTO messages(discussion_id, role, etat, cree_le) VALUES(?, 'assistant', 'en_cours', ?)",
            (discussion_id, instant),
        )
        base.executer("UPDATE discussions SET modifie_le = ? WHERE id = ?", (instant, discussion_id))
        if premier and discussion["titre_auto"]:
            provisoire = " ".join(texte.split())[:60] or "Nouvelle discussion"
            base.executer("UPDATE discussions SET titre = ? WHERE id = ?", (provisoire, discussion_id))
        if not discussion["domaine"]:
            domaine = detecter_domaine(f"{discussion['recette_contexte'] or ''} {texte}", self.ctx.parametres.domaines())
            if domaine:
                base.executer("UPDATE discussions SET domaine = ? WHERE id = ?", (domaine, discussion_id))
        tour = Tour(reponse.lastrowid, discussion_id, texte)
        tour.pieces = pieces
        tour.message_utilisateur = curseur.lastrowid
        self.actifs[discussion_id] = tour
        self.file.put_nowait(tour)
        return tour

    async def flux(self, tour: Tour) -> AsyncIterator[tuple[str, dict]]:
        """Événements d'un tour : d'abord l'état complet, puis le direct. On peut s'abonner à tout moment."""
        file: asyncio.Queue = asyncio.Queue()
        tour.abonnes.add(file)
        try:
            yield "etat", {
                "message_id": tour.message_id, "message_utilisateur": tour.message_utilisateur,
                "texte": tour.texte, "outils": tour.outils, "position": self._position(tour),
            }  # fmt: skip
            if tour.final:
                yield tour.final
                return
            while True:
                try:
                    genre, donnees = await asyncio.wait_for(file.get(), 15)
                except TimeoutError:
                    yield "attente", {"position": self._position(tour)}  # garde la connexion ouverte
                    continue
                yield genre, donnees
                if genre in ("fin", "erreur"):
                    return
        finally:
            tour.abonnes.discard(file)

    def _position(self, tour: Tour) -> int:
        """0 = en cours d'exécution, n = nombre de tours devant dans la file."""
        en_attente = list(self.file._queue)  # noqa: SLF001
        return en_attente.index(tour) + 1 if tour in en_attente else 0

    # --- exécution --------------------------------------------------------
    def _composer_message(self, tour: Tour, discussion: dict, avec_historique: bool) -> str:
        parties = []
        if avec_historique:
            historique = self._historique(tour)
            if historique:
                parties.append(
                    "La session précédente n'est plus disponible. Voici l'historique de cette discussion, "
                    "à reprendre comme si elle n'avait pas été interrompue :\n\n<historique>\n" + historique + "\n</historique>\n\nNouveau message de Louis :"
                )
        premier = self.ctx.base.ligne(
            "SELECT count(*) AS n FROM messages WHERE discussion_id = ? AND role = 'user' AND id < ?",
            (tour.discussion_id, tour.message_id),
        )["n"] == 1
        if discussion["recette_contexte"] and (premier or avec_historique):
            parties.append(
                f"Recette en contexte : `{self.ctx.config.recettes / discussion['recette_contexte']}` — lis-la avec Read avant de répondre."
            )
        parties.append(tour.question)
        if tour.pieces:
            parties.append("Pièces jointes à lire avec Read :\n" + "\n".join(f"- `pieces/{p['fichier']}` ({p['nom']})" for p in tour.pieces))
        return "\n\n".join(parties)

    def _historique(self, tour: Tour) -> str:
        messages = self.ctx.base.lignes(
            "SELECT role, contenu FROM messages WHERE discussion_id = ? AND id < ? AND id != ? AND contenu != '' ORDER BY id",
            (tour.discussion_id, tour.message_id, tour.message_utilisateur),
        )
        blocs = [
            ("Louis : " if m["role"] == "user" else "Assistant : ") + self.ctx.propositions.developper(m["contenu"]) for m in messages
        ]
        texte = "\n\n".join(blocs)
        return texte[-HISTORIQUE_MAX:]

    def _consignes(self, discussion: dict) -> str:
        parametres = self.ctx.parametres
        textes = parametres.lire()["textes_domaines"]
        return consignes.composer(
            self.ctx.config,
            discussion["domaine"] if discussion["domaine"] not in TRANSVERSAUX else None,
            parametres.texte_domaine(discussion["domaine"]),
            {nom: textes.get(nom, "") for nom in TRANSVERSAUX},
        )

    async def _derouler(self, tour: Tour, demande: Demande) -> Evenement:
        """Exécute le moteur et renvoie l'événement terminal (fin ou erreur)."""
        base, dernier_enregistrement = self.ctx.base, time.monotonic()
        try:
            async with asyncio.timeout(self.ctx.config.delai_tour):
                async with contextlib.aclosing(self.ctx.moteur.run(demande)) as flux:
                    async for ev in flux:
                        if ev.type == "texte":
                            tour.texte += ev.texte
                            tour.publier("texte", {"delta": ev.texte})
                            if time.monotonic() - dernier_enregistrement > 1:
                                base.executer("UPDATE messages SET contenu = ? WHERE id = ?", (tour.texte, tour.message_id))
                                dernier_enregistrement = time.monotonic()
                        elif ev.type == "outil":
                            outil = {"nom": ev.nom, "detail": ev.detail}
                            tour.outils.append(outil)
                            tour.publier("outil", outil)
                        elif ev.type == "session" and ev.session and not demande.ephemere:
                            base.executer("UPDATE discussions SET session_claude = ? WHERE id = ?", (ev.session, tour.discussion_id))
                        elif ev.type in ("fin", "erreur"):
                            return ev
        except TimeoutError:
            return Evenement("erreur", code="delai", texte=MESSAGES_ERREUR["delai"])
        return Evenement("erreur", code="moteur", texte="Le moteur s'est arrêté sans conclure.")

    async def _executer(self, tour: Tour) -> None:
        base = self.ctx.base
        discussion = base.ligne("SELECT * FROM discussions WHERE id = ?", (tour.discussion_id,))
        if discussion is None:  # supprimée entre-temps
            return
        tour.debut = time.monotonic()
        tour.publier("debut", {})
        session = discussion["session_claude"]
        demande = Demande(
            message=self._composer_message(tour, discussion, avec_historique=session is None),
            modele=discussion["modele"], session=session, consignes=self._consignes(discussion),
        )  # fmt: skip
        final = await self._derouler(tour, demande)
        if final.type == "erreur" and final.code == "session_introuvable" and not tour.texte:
            # D-4 : session perdue ou corrompue → nouvelle session, historique réinjecté, sans intervention.
            base.executer("UPDATE discussions SET session_claude = NULL WHERE id = ?", (tour.discussion_id,))
            demande = dataclasses.replace(
                demande, session=None, message=self._composer_message(tour, discussion, avec_historique=True)
            )
            final = await self._derouler(tour, demande)
        if final.type == "erreur":
            self._echec(tour, final)
            return

        contenu, propositions = self.ctx.propositions.extraire(tour.texte, tour.message_id, tour.discussion_id)
        cout = final.cout
        if discussion["titre_auto"] and self.ctx.config.titre_auto:
            deja = base.ligne(
                "SELECT count(*) AS n FROM messages WHERE discussion_id = ? AND role = 'assistant' AND etat = 'termine'",
                (tour.discussion_id,),
            )["n"]
            if deja == 0:
                cout += await self._titrer(tour)
        base.executer(
            "UPDATE messages SET contenu = ?, outils = ?, cout = ?, etat = 'termine', duree_ms = ? WHERE id = ?",
            (contenu, json.dumps(tour.outils, ensure_ascii=False), cout, int((time.monotonic() - tour.debut) * 1000), tour.message_id),
        )
        base.executer("INSERT INTO messages_fts(rowid, contenu) VALUES(?, ?)", (tour.message_id, contenu))
        base.executer(
            "UPDATE discussions SET modifie_le = ?, session_claude = coalesce(?, session_claude) WHERE id = ?",
            (maintenant(), final.session, tour.discussion_id),
        )
        tour.publier("fin", {
            "message": self.message(tour.message_id),
            "discussion": base.ligne("SELECT * FROM discussions WHERE id = ?", (tour.discussion_id,)),
        })  # fmt: skip

    async def _titrer(self, tour: Tour) -> float:
        """D-2 : titre généré après le premier échange, par un tour court sans outils ni session."""
        demande = Demande(
            message=consignes.TITRE + f"Louis : {tour.question[:600]}\n\nAssistant : {tour.texte[:600]}",
            modele=self.ctx.config.modele_titre, ephemere=True,
        )  # fmt: skip
        titre, cout = "", 0.0
        try:
            async with asyncio.timeout(45):
                async with contextlib.aclosing(self.ctx.moteur.run(demande)) as flux:
                    async for ev in flux:
                        if ev.type == "texte":
                            titre += ev.texte
                        elif ev.type == "fin":
                            cout = ev.cout
        except Exception:  # noqa: BLE001 — le titre provisoire reste en place
            return 0.0
        titre = " ".join(titre.split()).strip("\"'«» .")[:80]
        if titre:
            self.ctx.base.executer("UPDATE discussions SET titre = ? WHERE id = ? AND titre_auto = 1", (titre, tour.discussion_id))
        return cout

    def _echec(self, tour: Tour, ev: Evenement) -> None:
        base = self.ctx.base
        base.executer(
            "UPDATE messages SET contenu = ?, outils = ?, cout = ?, etat = 'erreur', erreur = ?, duree_ms = ? WHERE id = ?",
            (tour.texte, json.dumps(tour.outils, ensure_ascii=False), ev.cout, ev.code or "moteur",
             int((time.monotonic() - tour.debut) * 1000), tour.message_id),
        )  # fmt: skip
        if ev.code == "quota":
            base.definir_meta("quota_atteint", maintenant()[:7])
        journal.warning("Tour %s : erreur %s (%s)", tour.message_id, ev.code, ev.texte[:300])
        tour.publier("erreur", {
            "code": ev.code or "moteur",
            "message": MESSAGES_ERREUR.get(ev.code, MESSAGES_ERREUR["moteur"]),
            "detail": ev.texte[:500] if ev.code == "moteur" else "",
            "message_enregistre": self.message(tour.message_id),
        })  # fmt: skip

    # --- lecture ----------------------------------------------------------
    def message(self, identifiant: int) -> dict:
        m = decoder(self.ctx.base.ligne("SELECT * FROM messages WHERE id = ?", (identifiant,)), "pieces", "outils")
        m["propositions"] = self.ctx.propositions.du_message(identifiant)
        if m["erreur"]:
            m["erreur_message"] = MESSAGES_ERREUR.get(m["erreur"], MESSAGES_ERREUR["moteur"])
        return m


def nouvel_identifiant() -> str:
    return uuid.uuid4().hex[:12]
