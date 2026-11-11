"""Création des dossiers de données et du répertoire de travail du CLI (agent/)."""

from __future__ import annotations

import json
import shutil

from .config import Config
from .depots import Depot

MARQUEUR = "<!-- Ajouts du serveur Aide Culinaire : ne pas modifier sous cette ligne -->"

IMPORTS = [
    "memoire/materiel.md",
    "memoire/preferences.md",
    "memoire/essais.md",
    "memoire/parametres.md",
    "memoire/references.md",
]

MEMOIRE_INITIALE = {
    "materiel.md": """# Matériel

- Robot pâtissier KitchenAid Classic 5K45SS (tête inclinable, bol 4,3 L, batteur plat, crochet, fouet).
- Four domestique peu précis : montée en température lente, régulation imprécise, chaleur inégale.
- Thermomètre de cuisson numérique à sonde.
- Yaourtière express.
""",
    "preferences.md": """# Préférences

- Huile neutre plutôt que beurre fondu quand la recette le permet.
- Règle « proposition avant écriture » : toute recette est d'abord proposée dans la conversation ; rien n'est enregistré sans accord explicite.
""",
    "essais.md": """# Essais

Résultats d'essais à retenir (date, recette, variable modifiée, résultat).
""",
}

FICHIERS_MEMOIRE = list(MEMOIRE_INITIALE)

IGNORER_AGENT = ["references/documents/", "references/liens/", "pieces/"]

# Le LLM n'a ni shell ni écriture (M-3) ; ces règles doublent les options de la ligne de commande.
REGLAGES_CLI = {
    "permissions": {
        "deny": [
            "Write",
            "Edit",
            "Bash",
            "NotebookEdit",
            "Read(//**/.env)",
            "Read(~/.ssh/**)",
            "Read(~/.claude/**)",
            "Read(//run/secrets/**)",
        ],
    }
}


def composer_claude_md(original: str) -> str:
    base = original.split(MARQUEUR)[0].rstrip()
    imports = "\n".join(f"@{chemin}" for chemin in IMPORTS)
    return f"{base}\n\n{MARQUEUR}\n\n## Mémoire, paramètres et références\n\n{imports}\n"


def initialiser(config: Config) -> tuple[Depot, Depot]:
    """Idempotent : ne remplace jamais un fichier existant, hormis le bloc d'imports de CLAUDE.md."""
    config.data.mkdir(parents=True, exist_ok=True)
    (config.data / "pieces").mkdir(exist_ok=True)

    recettes = Depot(config.recettes, config.git_auteur, config.git_courriel)
    recettes.initialiser()
    recettes.configurer_distant(config.git_remote_recettes)

    agent = config.agent
    agent.mkdir(parents=True, exist_ok=True)
    modele = config.agent_modele
    if modele.is_dir():
        for source in modele.rglob("*"):
            cible = agent / source.relative_to(modele)
            if source.is_dir():
                cible.mkdir(parents=True, exist_ok=True)
            elif not cible.exists():
                cible.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, cible)
    claude_md = agent / "CLAUDE.md"
    original = claude_md.read_text(encoding="utf-8") if claude_md.exists() else ""
    attendu = composer_claude_md(original)
    if attendu != original:
        claude_md.write_text(attendu, encoding="utf-8")

    (agent / "memoire").mkdir(exist_ok=True)
    for nom, contenu in MEMOIRE_INITIALE.items():
        if not (agent / "memoire" / nom).exists():
            (agent / "memoire" / nom).write_text(contenu, encoding="utf-8")
    for nom in ("parametres.md", "references.md"):
        if not (agent / "memoire" / nom).exists():
            (agent / "memoire" / nom).write_text("", encoding="utf-8")
    for dossier in (
        "references/fiches",
        "references/documents",
        "references/liens",
        "pieces",
        ".claude/skills",
    ):
        (agent / dossier).mkdir(parents=True, exist_ok=True)
    reglages = agent / ".claude" / "settings.json"
    if not reglages.exists():
        reglages.write_text(json.dumps(REGLAGES_CLI, indent=2) + "\n")

    depot_agent = Depot(agent, config.git_auteur, config.git_courriel)
    depot_agent.initialiser(ignorer=IGNORER_AGENT)
    depot_agent.configurer_distant(config.git_remote_agent)
    return recettes, depot_agent
