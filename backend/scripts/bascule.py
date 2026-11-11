"""Bascule (section 7) : import unique du dossier Google Drive dans le dépôt Git des recettes.

    uv run python -m scripts.bascule [--simuler]

À lancer une seule fois, à la mise en service, avec AC_RCLONE_DEST configuré. Après ce commit
initial, le serveur est le seul à créer et modifier les .cook.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from app import cooklang
from app.config import Config
from app.db import Base
from app.initialisation import initialiser
from app.synchro import FILTRES


def principal() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument(
        "--simuler", action="store_true", help="liste ce qui serait importé, sans rien copier"
    )
    args = analyseur.parse_args()
    config = Config()
    if not config.rclone_dest:
        print("AC_RCLONE_DEST n'est pas défini.", file=sys.stderr)
        return 2
    recettes, _ = initialiser(config)
    deja = [f for f in recettes.fichiers() if f.endswith(".cook")]
    if deja and not args.simuler:
        print(
            f"Le dépôt contient déjà {len(deja)} recette(s) : la bascule ne se fait qu'une fois.",
            file=sys.stderr,
        )
        return 2

    commande = ["rclone", "copy", config.rclone_dest, str(config.recettes), *FILTRES]
    if args.simuler:
        commande.append("--dry-run")
    resultat = subprocess.run(commande, capture_output=True, text=True)
    if resultat.returncode != 0:
        print(resultat.stderr, file=sys.stderr)
        return 1
    if args.simuler:
        print(resultat.stderr)
        return 0

    sha = recettes.commiter_tout("Import initial depuis Google Drive")
    fichiers = [f for f in recettes.fichiers() if f.endswith(".cook")]
    print(f"{len(fichiers)} recette(s) importée(s), commit {sha[:8] if sha else '(rien à commiter)'}.")

    anomalies = 0
    for chemin in fichiers:
        analyse = cooklang.analyser(recettes.lire(chemin) or "", config.outils_node, exiger_titre=False)
        for message in analyse.erreurs:
            anomalies += 1
            print(f"  ! {chemin} : {message}")
    print(
        f"{anomalies} anomalie(s) Cooklang."
        if anomalies
        else "Toutes les recettes passent le parseur Cooklang."
    )

    if sha:
        # Le Drive est par construction identique à ce commit : c'est la référence du prochain contrôle de divergence.
        Base(config.base).definir_meta("drive_synchro", sha)
        if recettes.a_un_distant():
            recettes.pousser()
            print("Dépôt poussé vers le distant.")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
