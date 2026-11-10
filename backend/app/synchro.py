"""Synchronisation (section 7) : push Git, miroir rclone, contrôle de divergence, conflits, journal."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from .config import Config
from .db import Base, maintenant
from .depots import Depot, ErreurGit

# Ni le dépôt Git ni les fichiers cachés ne sont comparés ou copiés ; ceux de l'appli Cook
# (.bookmarks, .shopping-list…) restent donc intacts côté Drive, rclone ne supprimant pas les exclus.
FILTRES = ["--exclude", ".git/**", "--exclude", ".*", "--exclude", "**/.*"]


class Synchro:
    def __init__(self, config: Config, base: Base, recettes: Depot, agent: Depot):
        self.config = config
        self.base = base
        self.recettes = recettes
        self.agent = agent
        self.verrou = threading.RLock()  # sérialise écritures et synchronisations

    # --- état -------------------------------------------------------------
    @property
    def drive_actif(self) -> bool:
        return bool(self.config.rclone_dest) and shutil.which("rclone") is not None

    def journaliser(self, cible: str, resultat: str, fichiers: list[str] | None = None, erreur: str | None = None) -> None:
        self.base.executer(
            "INSERT INTO synchro(date, cible, fichiers, resultat, erreur) VALUES(?, ?, ?, ?, ?)",
            (maintenant(), cible, json.dumps(sorted(fichiers or []), ensure_ascii=False), resultat, erreur),
        )

    def journal(self, limite: int = 100) -> list[dict]:
        lignes = self.base.lignes("SELECT * FROM synchro ORDER BY id DESC LIMIT ?", (limite,))
        for ligne in lignes:
            ligne["fichiers"] = json.loads(ligne["fichiers"])
        return lignes

    def etat(self) -> dict:
        return {
            "github": self.recettes.a_un_distant(),
            "drive": self.drive_actif,
            "destination": self.config.rclone_dest or None,
            "dernier_commit": self.recettes.tete(),
            "dernier_commit_synchronise": self.base.meta("drive_synchro"),
            "conflits": [f for f in self.recettes.fichiers() if ".conflit-" in f],
        }

    # --- rclone -----------------------------------------------------------
    def _rclone(self, *args: str, delai: float = 300) -> subprocess.CompletedProcess:
        return subprocess.run(["rclone", *args], capture_output=True, text=True, timeout=delai)

    def comparer(self) -> dict[str, str]:
        """Différences local → Drive : {chemin: '*' différent | '+' absent du Drive | '-' absent en local}."""
        proc = self._rclone("check", str(self.recettes.racine), self.config.rclone_dest, "--combined", "-", *FILTRES)
        if proc.returncode != 0 and "differences found" not in proc.stderr:
            raise RuntimeError(proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "rclone check a échoué")
        differences = {}
        for ligne in proc.stdout.splitlines():
            if len(ligne) > 2 and ligne[0] in "*+-":
                differences[ligne[2:]] = ligne[0]
        return differences

    def _telecharger(self, chemin: str, cible: Path) -> None:
        cible.parent.mkdir(parents=True, exist_ok=True)
        proc = self._rclone("copyto", f"{self.config.rclone_dest.rstrip('/')}/{chemin}", str(cible))
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or f"Téléchargement impossible : {chemin}")

    def _drive_inchange(self, chemin: str) -> bool:
        """Vrai si le fichier du Drive est encore celui du dernier miroir réussi."""
        reference = self.base.meta("drive_synchro")
        if not reference:
            return False
        proc = self._rclone("cat", f"{self.config.rclone_dest.rstrip('/')}/{chemin}")
        return proc.returncode == 0 and proc.stdout == (self.recettes.version(chemin, reference) or "")

    def importer_externes(self, cible_ecriture: str | None = None) -> dict:
        """S-3 et S-4 : importe les modifications faites côté Drive avant toute écriture.

        Un fichier différent côté Drive est une modification externe, sauf s'il a été modifié
        localement depuis la dernière synchro réussie (le serveur est alors simplement en avance).
        Si la modification externe touche le fichier qu'on s'apprête à écrire, la version du
        Drive est conservée à côté, dans `<Nom>.conflit-<date>.cook`.
        """
        bilan = {"importes": [], "conflits": []}
        if not self.drive_actif:
            return bilan
        with self.verrou:
            differences = self.comparer()
            en_avance = self.recettes.modifies_depuis(self.base.meta("drive_synchro"))
            horodatage = datetime.now().strftime("%Y%m%d-%H%M%S")
            for chemin, signe in sorted(differences.items()):
                if signe == "+" or Path(chemin).name.startswith("."):
                    continue  # absent du Drive : sera renvoyé par le prochain miroir
                modifie_ici = chemin in en_avance
                if signe == "-" and modifie_ici:
                    continue  # supprimé ici depuis la dernière synchro
                if signe == "*" and modifie_ici and self._drive_inchange(chemin):
                    continue  # le serveur est simplement en avance sur ce fichier
                if chemin == cible_ecriture or (signe == "*" and modifie_ici):
                    p = Path(chemin)
                    conflit = str(p.with_name(f"{p.stem}.conflit-{horodatage}{p.suffix}"))
                    self._telecharger(chemin, self.recettes.racine / conflit)
                    bilan["conflits"].append(conflit)
                else:
                    self._telecharger(chemin, self.recettes.racine / chemin)
                    bilan["importes"].append(chemin)
            if bilan["importes"]:
                self.recettes.commiter_tout("Modification externe (Google Drive)\n\n" + "\n".join(bilan["importes"]))
                self.journaliser("import", "ok", bilan["importes"])
            if bilan["conflits"]:
                self.recettes.commiter_tout("Conflit : version Google Drive conservée\n\n" + "\n".join(bilan["conflits"]))
                self.journaliser("conflit", "conflit", bilan["conflits"], "Deux versions conservées : à départager.")
        return bilan

    # --- après commit -----------------------------------------------------
    def pousser(self, depot: Depot, cible: str) -> bool:
        if not depot.a_un_distant():
            return True
        try:
            depot.pousser()
            self.journaliser(cible, "ok")
            return True
        except (ErreurGit, subprocess.TimeoutExpired) as erreur:
            self.journaliser(cible, "echec", erreur=str(erreur)[:500])
            return False

    def miroir(self) -> bool:
        if not self.drive_actif:
            return True
        tete = self.recettes.tete()
        fichiers = sorted(self.recettes.modifies_depuis(self.base.meta("drive_synchro")))
        proc = self._rclone("sync", str(self.recettes.racine), self.config.rclone_dest, *FILTRES)
        if proc.returncode != 0:
            self.journaliser("drive", "echec", fichiers, proc.stderr.strip()[:500])
            return False
        if tete:
            self.base.definir_meta("drive_synchro", tete)
        self.journaliser("drive", "ok", fichiers)
        return True

    def apres_commit(self) -> bool:
        """S-1 puis S-2. Un échec n'annule jamais le commit local : il est journalisé et rejoué."""
        with self.verrou:
            ok = self.pousser(self.recettes, "github")
            ok = self.miroir() and ok
            return ok

    def apres_commit_agent(self) -> bool:
        with self.verrou:
            return self.pousser(self.agent, "github-agent")

    def resynchroniser(self) -> dict:
        """Bouton « Resynchroniser » (S-5) : importe les modifications externes puis rejoue push et miroir."""
        with self.verrou:
            try:
                bilan = self.importer_externes()
            except (RuntimeError, subprocess.TimeoutExpired) as erreur:
                self.journaliser("drive", "echec", erreur=str(erreur)[:500])
                bilan = {"importes": [], "conflits": [], "erreur": str(erreur)}
            bilan["ok"] = self.apres_commit() and self.apres_commit_agent() and "erreur" not in bilan
            return bilan
