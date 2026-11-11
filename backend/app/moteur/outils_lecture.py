"""Outils de lecture du moteur API : Read, Glob, Grep, bornés à agent/ et recettes/ (M-3).

Le CLI Claude fournit ces outils lui-même ; avec l'API, c'est le serveur qui les exécute.
Aucun outil d'écriture ni de shell n'existe ici : le modèle ne peut que lire.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

IMAGES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
TEXTES = {".cook", ".md", ".markdown", ".txt", ".json", ".yaml", ".yml"}
LIGNES_MAX = 2000
RESULTATS_MAX = 200
IMAGE_MAX = 5 * 1024 * 1024

DEFINITIONS = [
    {
        "name": "Read",
        "description": (
            "Lit un fichier des dossiers autorisés (recettes, mémoire, références, pièces jointes, skills). "
            "Texte : renvoie les lignes numérotées ; image : renvoie l'image ; PDF : renvoie le texte extrait. "
            f"Au-delà de {LIGNES_MAX} lignes, lire par tranches avec offset et limit."
        ),
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Chemin absolu, ou relatif au répertoire de travail.",
                },
                "offset": {"type": "integer", "description": "Première ligne à lire (1 par défaut)."},
                "limit": {"type": "integer", "description": "Nombre de lignes à lire."},
            },
            "required": ["file_path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "Glob",
        "description": "Liste les fichiers correspondant à un motif (ex. `**/*.cook`, `Dessert/Flan*.cook`) sous un dossier autorisé.",
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {
                    "type": "string",
                    "description": "Dossier de départ ; par défaut le répertoire de travail.",
                },
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
    {
        "name": "Grep",
        "description": "Cherche une expression régulière dans les fichiers texte d'un dossier autorisé. Renvoie `chemin:ligne: texte`.",
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Expression régulière."},
                "path": {
                    "type": "string",
                    "description": "Fichier ou dossier ; par défaut le répertoire de travail.",
                },
                "glob": {"type": "string", "description": "Filtre de noms de fichiers, ex. `*.cook`."},
                "ignore_case": {"type": "boolean"},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
]


class Refus(Exception):
    pass


class OutilsLecture:
    def __init__(self, agent: Path, recettes: Path):
        self.agent = agent.resolve()
        self.racines = [self.agent, recettes.resolve()]

    # --- périmètre --------------------------------------------------------
    def resoudre(self, chemin: str) -> Path:
        """Chemin absolu à l'intérieur d'une racine autorisée ; le chemin vient du modèle, donc non fiable."""
        if not isinstance(chemin, str) or not chemin.strip():
            raise Refus("Chemin manquant.")
        p = Path(chemin)
        cible = (p if p.is_absolute() else self.agent / p).resolve()
        for racine in self.racines:
            if cible.is_relative_to(racine):
                relatif = cible.relative_to(racine).parts
                caches = [part for part in relatif if part.startswith(".")]
                # Seul dossier caché lisible : les skills. Ni .git, ni réglages, ni fichiers de l'appli Cook.
                if caches and relatif[:2] != (".claude", "skills"):
                    raise Refus("Accès refusé : fichier ou dossier caché.")
                return cible
        raise Refus("Accès refusé : en dehors des dossiers autorisés.")

    def _visibles(self, base: Path, motif: str):
        for fichier in sorted(base.glob(motif)):
            if not fichier.is_file():
                continue
            try:
                self.resoudre(str(fichier))
            except Refus:
                continue
            yield fichier

    # --- outils -----------------------------------------------------------
    def read(self, file_path: str, offset: int | None = None, limit: int | None = None) -> str | list[dict]:
        cible = self.resoudre(file_path)
        if not cible.is_file():
            raise Refus(f"Fichier introuvable : {file_path}")
        extension = cible.suffix.lower()
        if extension in IMAGES:
            if cible.stat().st_size > IMAGE_MAX:
                raise Refus("Image trop volumineuse (5 Mo au plus).")
            donnees = base64.standard_b64encode(cible.read_bytes()).decode()
            return [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": IMAGES[extension], "data": donnees},
                }
            ]
        if extension == ".pdf":
            from ..references import pdf_en_pages

            pages, _ = pdf_en_pages(cible)
            texte = "\n\n".join(f"[page {numero}]\n{contenu}" for numero, contenu in pages)
        else:
            try:
                texte = cible.read_text(encoding="utf-8")
            except UnicodeDecodeError as erreur:
                raise Refus("Ce fichier n'est pas un fichier texte.") from erreur
        lignes = texte.splitlines()
        debut = max(1, offset or 1)
        nombre = min(limit or LIGNES_MAX, LIGNES_MAX)
        tranche = lignes[debut - 1 : debut - 1 + nombre]
        sortie = "\n".join(f"{debut + i:>5}\t{ligne}" for i, ligne in enumerate(tranche))
        reste = len(lignes) - (debut - 1 + len(tranche))
        if reste > 0:
            # Jamais de troncature silencieuse : le modèle sait qu'il reste des lignes et comment les lire.
            sortie += f"\n\n[{reste} ligne(s) non affichée(s) : relire avec offset={debut + len(tranche)}]"
        return sortie or "[fichier vide]"

    def glob(self, pattern: str, path: str | None = None) -> str:
        base = self.resoudre(path) if path else self.agent
        motif = pattern
        if Path(pattern).is_absolute():  # motif absolu : on le ramène à sa racine autorisée
            for racine in self.racines:
                if pattern.startswith(str(racine) + "/"):
                    base, motif = racine, pattern[len(str(racine)) + 1 :]
                    break
            else:
                raise Refus("Accès refusé : en dehors des dossiers autorisés.")
        try:
            trouves = [str(f) for f in self._visibles(base, motif)]
        except (ValueError, NotImplementedError) as erreur:
            raise Refus(f"Motif invalide : {erreur}") from erreur
        if not trouves:
            return "Aucun fichier."
        suite = (
            f"\n[{len(trouves) - RESULTATS_MAX} autre(s) : préciser le motif]"
            if len(trouves) > RESULTATS_MAX
            else ""
        )
        return "\n".join(trouves[:RESULTATS_MAX]) + suite

    def grep(
        self, pattern: str, path: str | None = None, glob: str | None = None, ignore_case: bool = False
    ) -> str:
        try:
            expression = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
        except re.error as erreur:
            raise Refus(f"Expression régulière invalide : {erreur}") from erreur
        base = self.resoudre(path) if path else self.agent
        fichiers = [base] if base.is_file() else self._visibles(base, f"**/{glob or '*'}")
        lignes: list[str] = []
        for fichier in fichiers:
            if fichier.suffix.lower() not in TEXTES:
                continue
            try:
                contenu = fichier.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for numero, ligne in enumerate(contenu.splitlines(), 1):
                if expression.search(ligne):
                    lignes.append(f"{fichier}:{numero}: {ligne.strip()[:300]}")
        if not lignes:
            return "Aucune occurrence."
        suite = (
            f"\n[{len(lignes) - RESULTATS_MAX} autre(s) : préciser la recherche]"
            if len(lignes) > RESULTATS_MAX
            else ""
        )
        return "\n".join(lignes[:RESULTATS_MAX]) + suite

    def executer(self, nom: str, entree: object) -> tuple[str | list[dict], bool]:
        """Exécute un outil. Renvoie (contenu, est_une_erreur) ; ne lève jamais."""
        if not isinstance(entree, dict):
            return "Entrée invalide : un objet JSON est attendu.", True
        try:
            if nom == "Read":
                self._verifier(entree, {"file_path": str}, {"offset": int, "limit": int})
                return self.read(**entree), False
            if nom == "Glob":
                self._verifier(entree, {"pattern": str}, {"path": str})
                return self.glob(**entree), False
            if nom == "Grep":
                self._verifier(entree, {"pattern": str}, {"path": str, "glob": str, "ignore_case": bool})
                return self.grep(**entree), False
            return f"Outil inconnu : {nom}", True
        except Refus as refus:
            return str(refus), True
        except OSError as erreur:
            return f"Lecture impossible : {erreur}", True

    @staticmethod
    def _verifier(entree: dict, requis: dict, optionnels: dict) -> None:
        """Avec le streaming au fil de l'eau, l'API ne valide plus l'entrée : on le fait ici."""
        attendus = requis | optionnels
        for cle, valeur in entree.items():
            if cle not in attendus:
                raise Refus(f"Paramètre inconnu : {cle}")
            if not isinstance(valeur, attendus[cle]) or (attendus[cle] is int and isinstance(valeur, bool)):
                raise Refus(f"Paramètre invalide : {cle}")
        for cle in requis:
            if cle not in entree:
                raise Refus(f"Paramètre manquant : {cle}")
