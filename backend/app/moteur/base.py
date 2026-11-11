"""Interface du moteur LLM (M-1) : un tour = un flux d'événements typés."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass
class Demande:
    message: str
    modele: str
    session: str | None = None  # identifiant de session à reprendre
    consignes: str = ""  # ajout au prompt système
    ephemere: bool = False  # tour sans outils ni session conservée (titres)


@dataclass
class Evenement:
    """type : session | texte | outil | fin | erreur."""

    type: str
    texte: str = ""
    nom: str = ""
    detail: str = ""
    session: str | None = None
    cout: float = 0.0
    code: str = ""  # erreur : session_introuvable | authentification | quota | delai | moteur


class Engine(Protocol):
    nom: str

    def run(self, demande: Demande) -> AsyncIterator[Evenement]: ...

    def modeles(self) -> list[str]:
        """Noms de modèles proposés dans l'interface."""
        ...

    def reconnait(self, session: str | None) -> bool:
        """Vrai si l'identifiant de session a été émis par ce moteur."""
        ...

    async def version(self) -> str: ...


def classer_erreur(texte: str) -> str:
    t = texte.lower()
    if "no conversation found" in t:
        return "session_introuvable"
    if any(m in t for m in ("401", "authentication", "oauth", "invalid api key", "/login", "unauthorized")):
        return "authentification"
    if any(m in t for m in ("usage limit", "rate limit", "quota", "credit", "limit reached", "429")):
        return "quota"
    return "moteur"


MESSAGES_ERREUR = {
    "session_introuvable": "La session Claude est introuvable.",
    "authentification": "Le jeton d'authentification du CLI Claude est absent ou expiré. Renouvelle-le avec `claude setup-token` (voir la documentation d'exploitation).",
    "quota": "Le crédit mensuel du mode non interactif est épuisé. L'assistant sera de nouveau disponible au renouvellement du crédit.",
    "delai": "Le tour a dépassé le délai maximal et a été arrêté.",
    "moteur": "Le moteur a renvoyé une erreur.",
    "authentification_api": "La clé API est absente, invalide ou sans droit sur ce modèle.",
    "credit_api": "Le solde ou le quota du compte API est épuisé.",
    "debit": "Limite de débit de l'API atteinte. Réessaie dans une minute.",
    "surcharge": "Le fournisseur du modèle est momentanément indisponible. Réessaie dans un instant.",
    "reseau": "Connexion au fournisseur du modèle impossible. Vérifie le réseau du serveur et l'URL configurée.",
    "refus": "Le modèle a décliné cette demande (filtre de sécurité). Reformule ou change de modèle.",
    "interrompu": "Le serveur a redémarré pendant la génération de cette réponse.",
}
