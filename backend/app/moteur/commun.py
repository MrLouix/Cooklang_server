"""Ce que partagent les moteurs par API : prompt système reconstitué et sessions en fichiers JSON."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from ..config import Config

IMPORT = re.compile(r"(?m)^@(\S+)\s*$")


def developper_imports(texte: str, racine: Path, profondeur: int = 0) -> str:
    """Remplace les lignes `@chemin` de CLAUDE.md par le contenu du fichier, comme le fait le CLI."""

    def remplacer(trouve: re.Match) -> str:
        cible = (racine / trouve.group(1)).resolve()
        if profondeur >= 3 or not cible.is_file() or not cible.is_relative_to(racine.resolve()):
            return ""
        return developper_imports(cible.read_text(encoding="utf-8"), racine, profondeur + 1).strip()

    return IMPORT.sub(remplacer, texte)


def lister_skills(agent: Path) -> str:
    lignes = []
    for fichier in sorted((agent / ".claude" / "skills").glob("*/SKILL.md")):
        entete = fichier.read_text(encoding="utf-8").split("---", 2)
        champs = dict(
            re.findall(r'(?m)^(name|description):\s*"?(.*?)"?\s*$', entete[1] if len(entete) > 2 else "")
        )
        nom = champs.get("name", fichier.parent.name)
        lignes.append(
            f"- **{nom}** — {champs.get('description', '')} Fichier : `.claude/skills/{fichier.parent.name}/SKILL.md`"
        )
    if not lignes:
        return ""
    return (
        "# Skills disponibles\n\nQuand une demande correspond à un skill, lis son fichier en entier avec Read, "
        "puis suis-le. Il n'y a pas d'outil Skill ici.\n\n" + "\n".join(lignes)
    )


def composer_systeme(config: Config, consignes: str) -> str:
    """CLAUDE.md (imports développés), liste des skills, répertoire de travail, consignes du serveur."""
    agent = config.agent
    claude_md = agent / "CLAUDE.md"
    parties = [
        developper_imports(claude_md.read_text(encoding="utf-8"), agent) if claude_md.is_file() else ""
    ]
    parties += [lister_skills(agent), f"Répertoire de travail : `{agent}`.", consignes]
    return "\n\n".join(p.strip() for p in parties if p.strip())


class Sessions:
    """Une session = un fichier JSON, écrit seulement quand un tour aboutit."""

    def __init__(self, dossier: Path, prefixe: str):
        self.dossier, self.prefixe = dossier, prefixe

    def reconnait(self, session: str | None) -> bool:
        return bool(session) and session.startswith(self.prefixe)

    def nouvelle(self) -> str:
        return f"{self.prefixe}{uuid.uuid4()}"

    def _fichier(self, session: str) -> Path:
        if not re.fullmatch(rf"{re.escape(self.prefixe)}[0-9a-f-]{{36}}", session):
            raise FileNotFoundError(session)
        return self.dossier / f"{session}.json"

    def charger(self, session: str) -> dict:
        """Lève OSError ou JSONDecodeError si la session est absente ou illisible."""
        return json.loads(self._fichier(session).read_text(encoding="utf-8"))

    def enregistrer(self, session: str, etat: dict) -> None:
        self.dossier.mkdir(parents=True, exist_ok=True)
        provisoire = self._fichier(session).with_suffix(".tmp")
        provisoire.write_text(json.dumps(etat, ensure_ascii=False), encoding="utf-8")
        provisoire.replace(self._fichier(session))
