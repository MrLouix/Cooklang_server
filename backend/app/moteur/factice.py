"""Moteur factice : réponses scénarisées pour les tests et le mode démonstration."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

from .base import Demande, Evenement

BRIOCHE = """---
title: Brioche du dimanche
locale: fr
servings: 8
course: viennoiserie
difficulty: moyen
time.prep: 40 minutes
time.cook: 30 minutes
tags: [brioche, viennoiserie]
description: Brioche au beurre, version de démonstration. Rendement 560 g.
---

[- Pourcentages du boulanger (farine = 100 %)
   Farine 250 g = 100 % | Œufs 150 g = 60 % | Beurre 125 g = 50 % | Sucre 30 g = 12 %
   Calcul exemple : beurre 125 ÷ 250 × 100 = 50 % -]

== Pétrissage ==

Mélanger @farine T45{250%g}, @sucre{30%g}, @sel{5%g} et @levure fraîche{10%g} dans le #bol du robot{}.

Ajouter @œufs{150%g} et pétrir au crochet vitesse 2 pendant ~pétrissage{8%minutes}.

Incorporer @beurre{125%g} froid en dés, puis pétrir encore ~beurrage{10%minutes}.

== Cuisson ==

Cuire à 170 °C en chaleur statique ~cuisson{30%minutes} jusqu'à 92 °C à cœur.
"""


class MoteurFactice:
    nom = "factice"

    def __init__(self, delai: float = 0.0):
        self.delai = delai  # pause entre deux morceaux de texte
        self.sessions: set[str] = set()
        self.demandes: list[Demande] = []
        self.erreur: str | None = None  # code d'erreur à renvoyer au prochain tour
        self.reponse: str | None = None  # réponse imposée au prochain tour

    def composer(self, demande: Demande) -> str:
        message = demande.message
        bas = message.lower()
        if demande.ephemere:
            return "Brioche du dimanche" if "brioche" in bas else "Discussion culinaire"
        if "retiens" in bas:
            return (
                "Je propose d'ajouter cette préférence à la mémoire.\n\n"
                "```proposition\ncible: memoire\ntype: modification\nchemin: memoire/preferences.md\n---\n"
                "# Préférences\n\n- Huile neutre plutôt que beurre fondu.\n- Pas de fleur d'oranger.\n```\n"
            )
        if "fiche" in bas:
            from ..references import GABARIT_FICHE

            return (
                "Voici une fiche de référence.\n\n````proposition\ncible: fiche\ntype: creation\n"
                "chemin: references/fiches/brioche.md\n---\n"
                + GABARIT_FICHE.replace("{titre}", "Brioche")
                + "````\n"
            )
        if "brioche" in bas or "enregistre" in bas:
            chemin = "Boulangerie et viennoiserie/Brioche du dimanche.cook"
            genre = "modification" if "modifie" in bas else "creation"
            contenu = BRIOCHE.replace("{30%g}", "{35%g}") if genre == "modification" else BRIOCHE
            return (
                "## Diagnostic\n\n- Hydratation correcte, sucre à 12 %.\n\n"
                "| Ingrédient | g | % |\n|---|---|---|\n| Farine | 250 | 100 |\n| Œufs | 150 (≈ 3 œufs) | 60 |\n| Beurre | 125 | 50 |\n\n"
                f"```proposition\ncible: recette\ntype: {genre}\nchemin: {chemin}\n---\n{contenu}```\n\n"
                "Appuie sur **Enregistrer** pour l'ajouter au dossier."
            )
        return f"Réponse de démonstration à : {message[-200:]}"

    async def run(self, demande: Demande) -> AsyncIterator[Evenement]:
        self.demandes.append(demande)
        if self.erreur:
            code, self.erreur = self.erreur, None
            yield Evenement("erreur", code=code, texte=f"erreur simulée : {code}")
            return
        if demande.session and demande.session not in self.sessions:
            yield Evenement(
                "erreur", code="session_introuvable", texte="No conversation found with session ID"
            )
            return
        session = demande.session or str(uuid.uuid4())
        if not demande.ephemere:
            self.sessions.add(session)
        yield Evenement("session", session=session)
        texte, self.reponse = (self.reponse or self.composer(demande)), None
        if "cherche" in demande.message.lower():
            yield Evenement("outil", nom="WebSearch", detail="recette de référence")
        for i in range(0, len(texte), 40):
            if self.delai:
                await asyncio.sleep(self.delai)
            yield Evenement("texte", texte=texte[i : i + 40])
        yield Evenement("fin", session=session, cout=0.0123)

    @staticmethod
    def reconnait(session: str | None) -> bool:
        return bool(session) and not session.startswith("api-")

    async def version(self) -> str:
        return "factice"
