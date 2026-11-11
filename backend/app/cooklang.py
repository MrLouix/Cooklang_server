"""Validation Cooklang (F-7) : parseur officiel cooklang-rs (WASM) + règles du skill recette-cook."""

from __future__ import annotations

import html
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Analyse:
    erreurs: list[str] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)
    ingredients: list[dict] = field(default_factory=list)
    metadonnees: dict = field(default_factory=dict)

    @property
    def valide(self) -> bool:
        return not self.erreurs


_BALISE = re.compile(r"<[^>]+>")
_ACCOLADE_OUVERTE = re.compile(r"[@#~][^{}@#~\n]*\{[^}\n]*$")
_MINUTEUR = re.compile(r"~([^{}\s]*)\{([^}%]*)(?:%([^}]*))?\}")


def _entrees_rapport(rapport: str) -> list[tuple[str, str]]:
    texte = html.unescape(_BALISE.sub("", rapport))
    entrees: list[tuple[str, str]] = []
    for bloc in re.split(r"(?m)^(?=Warning:|Error:)", texte):
        bloc = bloc.strip()
        if bloc.startswith(("Warning:", "Error:")):
            genre, _, reste = bloc.partition(":")
            lignes = [ligne.strip(" ╰▶") for ligne in reste.strip().splitlines()]
            utiles = [
                ligne
                for ligne in lignes
                if ligne and not ligne.startswith(("╭", "──", "Help:")) and "│" not in ligne
            ]
            entrees.append((genre, " — ".join(utiles)))
    return entrees


def analyser(source: str, outils: Path, exiger_titre: bool = True) -> Analyse:
    analyse = Analyse()
    try:
        proc = subprocess.run(
            ["node", "--no-warnings", str(outils / "valider_cook.mjs")],
            input=source, capture_output=True, text=True, timeout=30,
        )  # fmt: skip
        resultat = json.loads(proc.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as erreur:
        analyse.erreurs.append(f"Parseur Cooklang indisponible : {erreur}")
        return analyse
    if "exception" in resultat:
        analyse.erreurs.append(f"Erreur du parseur : {resultat['exception']}")
        return analyse

    analyse.ingredients = resultat["ingredients"]
    analyse.metadonnees = resultat["metadonnees"]
    # Le skill vise zéro avertissement : tout message du parseur est bloquant.
    for genre, message in _entrees_rapport(resultat.get("rapport", "")):
        analyse.erreurs.append(f"{'Erreur' if genre == 'Error' else 'Avertissement'} du parseur : {message}")
    if resultat["etapes"] == 0:
        analyse.erreurs.append("La recette ne contient aucune étape.")
    if exiger_titre and not analyse.metadonnees.get("title"):
        analyse.erreurs.append("Le front matter doit contenir un champ `title`.")
    if re.search(r"(?m)^yield\s*:", source.split("\n---", 2)[0] if source.startswith("---") else ""):
        analyse.erreurs.append("Le champ `yield` est rejeté : indiquer le rendement dans `description`.")
    for numero, ligne in enumerate(source.splitlines(), 1):
        if _ACCOLADE_OUVERTE.search(ligne):
            analyse.erreurs.append(f"Ligne {numero} : accolade non fermée.")
        for nom, valeur, unite in _MINUTEUR.findall(ligne):
            if not re.fullmatch(r"\d+", valeur.strip()):
                analyse.avertissements.append(
                    f"Ligne {numero} : le minuteur ~{nom} doit avoir une valeur entière unique."
                )
            if not (unite or "").strip():
                analyse.avertissements.append(f"Ligne {numero} : le minuteur ~{nom} n'a pas d'unité.")
    for ingredient in analyse.ingredients:
        if isinstance(ingredient.get("quantite"), str) and ingredient.get("unite"):
            analyse.avertissements.append(f"Quantité non numérique pour « {ingredient['nom']} ».")
    return analyse
