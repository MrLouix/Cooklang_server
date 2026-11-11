"""Opérations Git sur un dépôt de données (recettes ou agent)."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


class ErreurGit(RuntimeError):
    pass


class CheminInvalide(ValueError):
    pass


def empreinte(contenu: bytes | str | None) -> str | None:
    if contenu is None:
        return None
    if isinstance(contenu, str):
        contenu = contenu.encode()
    return hashlib.sha256(contenu).hexdigest()


class Depot:
    def __init__(
        self, racine: Path, auteur: str = "Aide Culinaire", courriel: str = "aide-culinaire@localhost"
    ):
        self.racine = Path(racine)
        self.auteur = auteur
        self.courriel = courriel

    # --- bas niveau -------------------------------------------------------
    def git(self, *args: str, verifier: bool = True, delai: float = 120) -> str:
        proc = subprocess.run(
            ["git", "-c", f"user.name={self.auteur}", "-c", f"user.email={self.courriel}",
             "-c", "core.quotepath=false", "-c", "commit.gpgsign=false", *args],
            cwd=self.racine, capture_output=True, text=True, timeout=delai,
        )  # fmt: skip
        if verifier and proc.returncode != 0:
            raise ErreurGit((proc.stderr or proc.stdout).strip())
        return proc.stdout

    def initialiser(self, ignorer: list[str] | None = None) -> None:
        self.racine.mkdir(parents=True, exist_ok=True)
        if not (self.racine / ".git").exists():
            self.git("init", "-q", "-b", "main")
        if ignorer:
            fichier = self.racine / ".gitignore"
            lignes = fichier.read_text().splitlines() if fichier.exists() else []
            manquantes = [i for i in ignorer if i not in lignes]
            if manquantes:
                fichier.write_text("\n".join(lignes + manquantes) + "\n")
        self.commiter_tout("Initialisation")

    def resoudre(self, chemin: str) -> Path:
        """Chemin absolu sûr à l'intérieur du dépôt."""
        p = Path(chemin)
        if (
            p.is_absolute()
            or not chemin.strip()
            or any(part in ("..", "") or part.startswith(".") for part in p.parts)
        ):
            raise CheminInvalide(f"Chemin refusé : {chemin}")
        cible = (self.racine / p).resolve()
        if not cible.is_relative_to(self.racine.resolve()):
            raise CheminInvalide(f"Chemin refusé : {chemin}")
        return cible

    # --- lecture ----------------------------------------------------------
    def lire(self, chemin: str) -> str | None:
        cible = self.resoudre(chemin)
        return cible.read_text(encoding="utf-8") if cible.is_file() else None

    def empreinte(self, chemin: str) -> str | None:
        cible = self.resoudre(chemin)
        return empreinte(cible.read_bytes()) if cible.is_file() else None

    def tete(self) -> str | None:
        sortie = self.git("rev-parse", "-q", "--verify", "HEAD", verifier=False).strip()
        return sortie or None

    def historique(self, chemin: str | None = None, limite: int = 50) -> list[dict]:
        if not self.tete():
            return []
        args = ["log", f"-{limite}", "--format=%H%x1f%aI%x1f%s%x1f%b%x1e"]
        if chemin:
            args += ["--follow", "--", chemin]
        entrees = []
        for bloc in self.git(*args).split("\x1e"):
            champs = bloc.strip("\n").split("\x1f")
            if len(champs) == 4:
                entrees.append(
                    {"sha": champs[0], "date": champs[1], "sujet": champs[2], "corps": champs[3].strip()}
                )
        return entrees

    def version(self, chemin: str, sha: str) -> str | None:
        self.resoudre(chemin)
        proc_sortie = self.git("show", f"{sha}:{chemin}", verifier=False)
        return proc_sortie if proc_sortie or self._existe_dans(sha, chemin) else None

    def _existe_dans(self, sha: str, chemin: str) -> bool:
        return bool(self.git("ls-tree", sha, "--", chemin, verifier=False).strip())

    def modifies_depuis(self, sha: str | None) -> set[str]:
        """Fichiers modifiés entre `sha` et HEAD (tous les fichiers suivis si `sha` est vide)."""
        if not self.tete():
            return set()
        if not sha or not self.git("cat-file", "-t", sha, verifier=False).strip():
            return set(self.git("ls-files", "-z").split("\0")) - {""}
        return set(self.git("diff", "--name-only", "-z", sha, "HEAD").split("\0")) - {""}

    def fichiers(self) -> list[str]:
        return sorted(f for f in self.git("ls-files", "-z").split("\0") if f)

    # --- écriture ---------------------------------------------------------
    def commiter_tout(self, message: str) -> str | None:
        self.git("add", "-A")
        if not self.git("status", "--porcelain").strip():
            return None
        self.git("commit", "-q", "-m", message)
        return self.tete()

    def ecrire(self, chemin: str, contenu: str | bytes, message: str) -> str | None:
        cible = self.resoudre(chemin)
        cible.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(contenu, str):
            cible.write_text(contenu, encoding="utf-8")
        else:
            cible.write_bytes(contenu)
        self.git("add", "--", chemin)
        if not self.git("status", "--porcelain", "--", chemin).strip():
            return self.tete()
        self.git("commit", "-q", "-m", message, "--", chemin)
        return self.tete()

    def supprimer(self, chemin: str, message: str) -> str | None:
        cible = self.resoudre(chemin)
        if not cible.exists():
            return None
        cible.unlink()
        return self.commiter_tout(message)

    def restaurer(self, chemin: str, sha: str) -> str | None:
        contenu = self.version(chemin, sha)
        if contenu is None:
            raise ErreurGit(f"{chemin} est absent de la version {sha[:8]}")
        return self.ecrire(chemin, contenu, f"Restauration : {chemin}\n\nVersion restaurée : {sha}")

    # --- distant ----------------------------------------------------------
    def configurer_distant(self, url: str) -> None:
        if not url:
            return
        if "origin" in self.git("remote").split():
            self.git("remote", "set-url", "origin", url)
        else:
            self.git("remote", "add", "origin", url)

    def a_un_distant(self) -> bool:
        return "origin" in self.git("remote").split()

    def pousser(self) -> None:
        self.git("push", "-q", "-u", "origin", "HEAD:main", delai=90)
