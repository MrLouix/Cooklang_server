"""Configuration lue dans les variables d'environnement (préfixe AC_)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

RACINE_CODE = Path(__file__).resolve().parents[2]

OUTILS_AUTORISES = ["Read", "Glob", "Grep", "Skill", "WebSearch", "WebFetch"]
OUTILS_INTERDITS = ["Write", "Edit", "Bash", "NotebookEdit"]
MODELES = ["sonnet", "opus", "haiku"]


def _env(nom: str, defaut: str = "") -> str:
    return os.environ.get(f"AC_{nom}", defaut)


@dataclass
class Config:
    racine: Path = field(default_factory=lambda: Path(_env("RACINE", "/srv/aide-culinaire")))
    moteur: str = field(default_factory=lambda: _env("MOTEUR", "claude"))
    modele_defaut: str = field(default_factory=lambda: _env("MODELE_DEFAUT", "sonnet"))
    modele_titre: str = field(default_factory=lambda: _env("MODELE_TITRE", "haiku"))
    titre_auto: bool = field(default_factory=lambda: _env("TITRE_AUTO", "1") == "1")
    delai_tour: float = field(default_factory=lambda: float(_env("DELAI_TOUR", "300")))
    credit_mensuel: float = field(default_factory=lambda: float(_env("CREDIT_MENSUEL", "20")))
    mot_de_passe: str = field(default_factory=lambda: _env("MOT_DE_PASSE"))
    # Synchronisation : vides = étape désactivée.
    git_remote_recettes: str = field(default_factory=lambda: _env("GIT_REMOTE_RECETTES"))
    git_remote_agent: str = field(default_factory=lambda: _env("GIT_REMOTE_AGENT"))
    rclone_dest: str = field(default_factory=lambda: _env("RCLONE_DEST"))
    intervalle_controle: float = field(default_factory=lambda: float(_env("INTERVALLE_CONTROLE", "600")))
    git_auteur: str = field(default_factory=lambda: _env("GIT_AUTEUR", "Aide Culinaire"))
    git_courriel: str = field(default_factory=lambda: _env("GIT_COURRIEL", "aide-culinaire@localhost"))
    # Moteur de secours : pris automatiquement quand le moteur principal signale un crédit épuisé.
    moteur_secours: str = field(default_factory=lambda: _env("MOTEUR_SECOURS"))
    secours_reessai_h: float = field(default_factory=lambda: float(_env("SECOURS_REESSAI_H", "6")))
    cle_api_fichier: str = field(
        default_factory=lambda: _env("CLE_API_FICHIER", "/run/secrets/anthropic_api_key")
    )
    api_effort: str = field(default_factory=lambda: _env("API_EFFORT"))
    claude_bin: str = field(default_factory=lambda: _env("CLAUDE_BIN", "claude"))
    jeton_fichier: str = field(default_factory=lambda: _env("JETON_FICHIER", "/run/secrets/claude_token"))
    front: Path = field(default_factory=lambda: Path(_env("FRONT", str(RACINE_CODE / "frontend" / "dist"))))
    agent_modele: Path = field(default_factory=lambda: Path(_env("AGENT_MODELE", str(RACINE_CODE / "agent"))))
    outils_node: Path = field(
        default_factory=lambda: Path(_env("OUTILS_NODE", str(RACINE_CODE / "backend" / "outils")))
    )

    @property
    def recettes(self) -> Path:
        return self.racine / "recettes"

    @property
    def agent(self) -> Path:
        return self.racine / "agent"

    @property
    def data(self) -> Path:
        return self.racine / "data"

    @property
    def base(self) -> Path:
        return self.data / "app.db"
