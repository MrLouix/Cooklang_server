"""Base documentaire (section 12) : documents, liens, fiches de référence, index plein texte."""

from __future__ import annotations

import html
import ipaddress
import json
import re
import shutil
import socket
import subprocess
import tempfile
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .db import Base, maintenant, requete_fts
from .depots import Depot

CHAMPS_FICHE = [
    "Fourchettes en % du boulanger",
    "Température de pâte en fin de pétrissage",
    "Four",
    "Température à cœur en fin de cuisson",
    "Repères visuels",
    "Sources",
]

GABARIT_FICHE = """# {titre}

## Fourchettes en % du boulanger

| Ingrédient | Fourchette | Source |
|---|---|---|
| Hydratation |  |  |
| Sucre |  |  |
| Matière grasse |  |  |
| Sel |  |  |
| Levure |  |  |

## Température de pâte en fin de pétrissage

## Four

## Température à cœur en fin de cuisson

## Repères visuels

## Sources
"""

EXTENSIONS = {".pdf", ".epub", ".md", ".markdown", ".txt"}


class ErreurReference(ValueError):
    pass


def valider_fiche(contenu: str) -> list[str]:
    titres = {t.strip().lower() for t in re.findall(r"(?m)^##\s+(.+)$", contenu)}
    erreurs = [f"Rubrique manquante : « {c} »." for c in CHAMPS_FICHE if c.lower() not in titres]
    if not re.search(r"(?m)^#\s+\S", contenu):
        erreurs.insert(0, "La fiche doit commencer par un titre `# Nom`.")
    return erreurs


def nom_sur(nom: str) -> str:
    propre = re.sub(r"[^\w\- ]", "", nom, flags=re.UNICODE).strip().lower().replace(" ", "-")
    if not propre:
        raise ErreurReference("Nom de fiche invalide.")
    return propre[:80]


# --- conversion -------------------------------------------------------------


class _Texte(HTMLParser):
    IGNORES = {"script", "style", "nav", "footer", "header", "noscript", "svg", "form", "aside"}
    BLOCS = {"p", "div", "br", "li", "tr", "section", "article", "h1", "h2", "h3", "h4", "h5", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.morceaux: list[str] = []
        self.titre = ""
        self._ignore = 0
        self._dans_titre = False

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORES:
            self._ignore += 1
        elif tag == "title":
            self._dans_titre = True
        elif tag in ("h1", "h2", "h3", "h4"):
            self.morceaux.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.morceaux.append("\n- ")
        elif tag in ("td", "th"):
            self.morceaux.append(" | ")
        elif tag in self.BLOCS:
            self.morceaux.append("\n")

    def handle_endtag(self, tag):
        if tag in self.IGNORES and self._ignore:
            self._ignore -= 1
        elif tag == "title":
            self._dans_titre = False
        elif tag in self.BLOCS:
            self.morceaux.append("\n")

    def handle_data(self, data):
        if self._dans_titre:
            self.titre += data
        elif not self._ignore:
            self.morceaux.append(data)


def html_en_markdown(source: str) -> tuple[str, str]:
    analyseur = _Texte()
    analyseur.feed(source)
    texte = "".join(analyseur.morceaux)
    texte = re.sub(r"[ \t]+", " ", texte)
    texte = re.sub(r" ?\n ?", "\n", texte)
    return html.unescape(analyseur.titre).strip(), re.sub(r"\n{3,}", "\n\n", texte).strip()


def _ocr_page(pdf: Path, numero: int) -> str:
    """OCR d'une page scannée, si tesseract et pdftoppm sont installés."""
    if not (shutil.which("tesseract") and shutil.which("pdftoppm")):
        return ""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "page"
        rendu = subprocess.run(
            ["pdftoppm", "-r", "200", "-f", str(numero), "-l", str(numero), "-png", "-singlefile", str(pdf), str(base)],
            capture_output=True, timeout=120,
        )  # fmt: skip
        if rendu.returncode != 0:
            return ""
        ocr = subprocess.run(
            ["tesseract", f"{base}.png", "-", "-l", "fra+eng"], capture_output=True, text=True, timeout=180
        )
        return ocr.stdout.strip() if ocr.returncode == 0 else ""


def pdf_en_pages(chemin: Path) -> tuple[list[tuple[int, str]], int]:
    """Renvoie [(page, texte)] et le nombre de pages restées sans texte (OCR indisponible ou vide)."""
    from pypdf import PdfReader

    pages, vides = [], 0
    for numero, page in enumerate(PdfReader(str(chemin)).pages, 1):
        texte = (page.extract_text() or "").strip()
        if len(texte) < 20:
            texte = _ocr_page(chemin, numero) or texte
        if texte:
            pages.append((numero, texte))
        else:
            vides += 1
    return pages, vides


def epub_en_pages(chemin: Path) -> list[tuple[int, str]]:
    pages = []
    with zipfile.ZipFile(chemin) as archive:
        noms = [n for n in archive.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))]
        for numero, nom in enumerate(sorted(noms), 1):
            _, texte = html_en_markdown(archive.read(nom).decode("utf-8", errors="replace"))
            if texte:
                pages.append((numero, texte))
    return pages


def decouper(texte: str, taille: int = 1500) -> list[str]:
    """Découpe un texte en passages d'environ `taille` caractères, aux fins de paragraphe."""
    passages, courant = [], ""
    for paragraphe in re.split(r"\n\s*\n", texte):
        if courant and len(courant) + len(paragraphe) > taille:
            passages.append(courant.strip())
            courant = ""
        courant += paragraphe + "\n\n"
    if courant.strip():
        passages.append(courant.strip())
    return passages


def url_publique(url: str) -> None:
    """B-11 : URL http(s) vers un hôte public (pas d'adresse locale ni privée)."""
    parties = urlparse(url)
    if parties.scheme not in ("http", "https") or not parties.hostname:
        raise ErreurReference("L'URL doit commencer par http:// ou https://.")
    try:
        adresses = {info[4][0] for info in socket.getaddrinfo(parties.hostname, None)}
    except OSError as erreur:
        raise ErreurReference(f"Hôte introuvable : {parties.hostname}") from erreur
    for adresse in adresses:
        ip = ipaddress.ip_address(adresse)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ErreurReference("L'URL doit pointer vers un site public.")


class References:
    def __init__(
        self, base: Base, depot: Depot, client: httpx.Client | None = None, verifier_hote: bool = True
    ):
        self.base = base
        self.depot = depot
        self.racine = depot.racine / "references"
        self.client = client or httpx.Client(
            follow_redirects=True,
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (compatible; lecteur-de-references)"},
        )
        self.verifier_hote = verifier_hote

    # --- sources ----------------------------------------------------------
    def lister(self) -> list[dict]:
        sources = self.base.lignes("SELECT * FROM sources ORDER BY id DESC")
        for source in sources:
            source["actif"] = bool(source["actif"])
            source["passages"] = self.base.ligne(
                "SELECT count(*) AS n FROM passages WHERE source_id = ?", (str(source["id"]),)
            )["n"]
        return sources

    def source(self, identifiant: int) -> dict:
        ligne = self.base.ligne("SELECT * FROM sources WHERE id = ?", (identifiant,))
        if not ligne:
            raise ErreurReference("Source introuvable.")
        return ligne

    def _creer(self, type_: str, titre: str, **champs) -> int:
        curseur = self.base.executer(
            "INSERT INTO sources(type, titre, chemin, url, mode, etat, ajoutee_le) VALUES(?, ?, ?, ?, ?, ?, ?)",
            (
                type_,
                titre,
                champs.get("chemin"),
                champs.get("url"),
                champs.get("mode"),
                champs.get("etat", "en_attente"),
                maintenant(),
            ),
        )
        return curseur.lastrowid

    def _etat(self, identifiant: int, etat: str, erreur: str | None = None, **champs) -> None:
        self.base.executer(
            "UPDATE sources SET etat = ?, erreur = ? WHERE id = ?", (etat, erreur, identifiant)
        )
        for cle, valeur in champs.items():
            self.base.executer(f"UPDATE sources SET {cle} = ? WHERE id = ?", (valeur, identifiant))

    def _indexer(self, identifiant: int, titre: str, pages: list[tuple[int | None, str]]) -> int:
        self.base.executer("DELETE FROM passages WHERE source_id = ?", (str(identifiant),))
        total = 0
        for page, texte in pages:
            for passage in decouper(texte):
                self.base.executer(
                    "INSERT INTO passages(source_id, titre, page, texte) VALUES(?, ?, ?, ?)",
                    (str(identifiant), titre, page, passage),
                )
                total += 1
        return total

    def activer(self, identifiant: int, actif: bool) -> None:
        self.source(identifiant)
        self.base.executer("UPDATE sources SET actif = ? WHERE id = ?", (int(actif), identifiant))
        self.publier()

    def supprimer(self, identifiant: int) -> None:
        source = self.source(identifiant)
        if source["type"] == "fiche":
            raise ErreurReference("Une fiche se supprime depuis l'éditeur de fiches.")
        self.base.executer("DELETE FROM passages WHERE source_id = ?", (str(identifiant),))
        self.base.executer("DELETE FROM sources WHERE id = ?", (identifiant,))
        dossier = self.racine / ("documents" if source["type"] == "document" else "liens") / str(identifiant)
        shutil.rmtree(dossier, ignore_errors=True)
        self.publier()

    # --- documents (B-2) --------------------------------------------------
    def enregistrer_document(self, nom: str, contenu: bytes) -> int:
        """Range l'original ; la conversion se fait ensuite dans `convertir_document`."""
        extension = Path(nom).suffix.lower()
        if extension not in EXTENSIONS:
            raise ErreurReference("Formats acceptés : PDF, EPUB, Markdown, texte.")
        identifiant = self._creer("document", Path(nom).stem, etat="en_attente")
        dossier = self.racine / "documents" / str(identifiant)
        dossier.mkdir(parents=True, exist_ok=True)
        (dossier / f"original{extension}").write_bytes(contenu)
        self._etat(identifiant, "en_attente", chemin=f"references/documents/{identifiant}/texte.md")
        return identifiant

    def convertir_document(self, identifiant: int) -> None:
        source = self.source(identifiant)
        dossier = self.racine / "documents" / str(identifiant)
        try:
            original = next(dossier.glob("original.*"))
            avis = None
            if original.suffix == ".pdf":
                pages, vides = pdf_en_pages(original)
                if vides:
                    avis = f"{vides} page(s) sans texte (scan sans OCR disponible)."
            elif original.suffix == ".epub":
                pages = epub_en_pages(original)
            else:
                pages = [(None, original.read_text(encoding="utf-8", errors="replace"))]
            if not pages:
                raise ErreurReference("Aucun texte extrait du document.")
            corps = "\n\n".join((f"<!-- page {p} -->\n\n{t}" if p else t) for p, t in pages)
            (dossier / "texte.md").write_text(f"# {source['titre']}\n\n{corps}\n", encoding="utf-8")
            self._indexer(identifiant, source["titre"], pages)
            self._etat(identifiant, "indexe", avis)
        except Exception as erreur:  # noqa: BLE001 — l'état d'indexation porte l'erreur
            self._etat(identifiant, "erreur", str(erreur)[:300])
        self.publier()

    # --- liens (B-3, B-11) ------------------------------------------------
    def _telecharger(self, url: str) -> httpx.Response:
        if urlparse(url).scheme not in ("http", "https"):
            raise ErreurReference("L'URL doit commencer par http:// ou https://.")
        if self.verifier_hote:
            url_publique(url)
        try:
            reponse = self.client.get(url)
        except httpx.HTTPError as erreur:
            raise ErreurReference(f"L'URL ne répond pas : {erreur}") from erreur
        if reponse.status_code in (401, 402, 403):
            raise ErreurReference(f"L'URL exige un compte ou un paiement (HTTP {reponse.status_code}).")
        if reponse.status_code >= 400:
            raise ErreurReference(f"L'URL ne répond pas (HTTP {reponse.status_code}).")
        return reponse

    def ajouter_lien(self, url: str, mode: str, titre: str | None = None) -> int:
        if mode not in ("copie_locale", "a_la_demande"):
            raise ErreurReference("Mode inconnu.")
        reponse = self._telecharger(url)  # vérifie que l'URL répond avant d'enregistrer
        titre_page = ""
        if "html" in reponse.headers.get("content-type", ""):
            titre_page, _ = html_en_markdown(reponse.text)
        identifiant = self._creer(
            "lien", titre or titre_page or urlparse(url).hostname, url=url, mode=mode, etat="accessible"
        )
        if mode == "copie_locale":
            self._copier_lien(identifiant, reponse)
        self.publier()
        return identifiant

    def _copier_lien(self, identifiant: int, reponse: httpx.Response) -> None:
        source = self.source(identifiant)
        dossier = self.racine / "liens" / str(identifiant)
        dossier.mkdir(parents=True, exist_ok=True)
        if "pdf" in reponse.headers.get("content-type", "") or source["url"].lower().endswith(".pdf"):
            (dossier / "original.pdf").write_bytes(reponse.content)
            pages, _ = pdf_en_pages(dossier / "original.pdf")
        else:
            pages = [(None, html_en_markdown(reponse.text)[1])]
        corps = "\n\n".join((f"<!-- page {p} -->\n\n{t}" if p else t) for p, t in pages)
        (dossier / "texte.md").write_text(
            f"# {source['titre']}\n\nSource : {source['url']}\n\n{corps}\n", encoding="utf-8"
        )
        self._indexer(identifiant, source["titre"], pages)
        self._etat(identifiant, "indexe", chemin=f"references/liens/{identifiant}/texte.md")

    def rafraichir(self, identifiant: int) -> dict:
        """Revérifie un lien ; rafraîchit la copie locale le cas échéant."""
        source = self.source(identifiant)
        if source["type"] != "lien":
            raise ErreurReference("Seul un lien se rafraîchit.")
        try:
            reponse = self._telecharger(source["url"])
            if source["mode"] == "copie_locale":
                self._copier_lien(identifiant, reponse)
            else:
                self._etat(identifiant, "accessible")
        except ErreurReference as erreur:
            self._etat(identifiant, "inaccessible", str(erreur)[:300])
        return self.source(identifiant)

    def verifier_liens(self) -> None:
        for source in self.base.lignes("SELECT id FROM sources WHERE type = 'lien'"):
            self.rafraichir(source["id"])

    # --- fiches (B-8) -----------------------------------------------------
    def fiches(self) -> list[dict]:
        dossier = self.racine / "fiches"
        return [
            {"nom": f.stem, "chemin": f"references/fiches/{f.name}"} for f in sorted(dossier.glob("*.md"))
        ]

    def lire_fiche(self, nom: str) -> str | None:
        return self.depot.lire(f"references/fiches/{nom_sur(nom)}.md")

    def ecrire_fiche(self, nom: str, contenu: str, message: str | None = None) -> str | None:
        erreurs = valider_fiche(contenu)
        if erreurs:
            raise ErreurReference(" ".join(erreurs))
        nom = nom_sur(nom)
        sha = self.depot.ecrire(
            f"references/fiches/{nom}.md", contenu, message or f"Fiche de référence : {nom}"
        )
        self.indexer_fiche(nom)
        self.publier()
        return sha

    def supprimer_fiche(self, nom: str) -> None:
        nom = nom_sur(nom)
        self.depot.supprimer(f"references/fiches/{nom}.md", f"Fiche supprimée : {nom}")
        self.base.executer("DELETE FROM passages WHERE source_id = ?", (f"fiche:{nom}",))
        self.publier()

    def indexer_fiche(self, nom: str) -> None:
        contenu = self.lire_fiche(nom) or ""
        self.base.executer("DELETE FROM passages WHERE source_id = ?", (f"fiche:{nom}",))
        for passage in decouper(contenu):
            self.base.executer(
                "INSERT INTO passages(source_id, titre, page, texte) VALUES(?, ?, NULL, ?)",
                (f"fiche:{nom}", f"Fiche {nom}", passage),
            )

    def reindexer_fiches(self) -> None:
        for fiche in self.fiches():
            self.indexer_fiche(fiche["nom"])

    # --- recherche (B-4) --------------------------------------------------
    def rechercher(self, question: str, limite: int = 20) -> list[dict]:
        requete = requete_fts(question)
        if not requete:
            return []
        lignes = self.base.lignes(
            "SELECT source_id, titre, page, snippet(passages, 3, '**', '**', '…', 24) AS extrait "
            "FROM passages WHERE passages MATCH ? ORDER BY (source_id LIKE 'fiche:%') DESC, rank LIMIT ?",
            (requete, limite * 3),
        )
        inactives = {str(s["id"]) for s in self.base.lignes("SELECT id FROM sources WHERE actif = 0")}
        resultats = [ligne for ligne in lignes if ligne["source_id"] not in inactives][:limite]
        for ligne in resultats:
            ligne["type"] = "fiche" if ligne["source_id"].startswith("fiche:") else "source"
        return resultats

    # --- consignes générées (B-5 à B-7) et liste versionnée des liens (B-9)
    def publier(self) -> None:
        sources = [s for s in self.lister() if s["actif"]]
        liens = [s for s in self.lister() if s["type"] == "lien"]
        liste = [
            {"titre": s["titre"], "url": s["url"], "mode": s["mode"], "actif": s["actif"]} for s in liens
        ]
        self.depot.ecrire(
            "references/liens.json",
            json.dumps(liste, ensure_ascii=False, indent=2) + "\n",
            "Liste des liens de référence",
        )
        lignes = [
            "# Base documentaire",
            "",
            "Appuie tes chiffres (hydratation, ratios, températures de cuisson et à cœur) sur cette base, dans cet ordre de priorité : "
            "1) fiches de référence, 2) documents, 3) liens enregistrés, 4) recherche web générale, 5) tes connaissances.",
            "",
            "- Chaque valeur chiffrée d'un diagnostic ou d'une correction porte sa source : nom de la fiche, document et page, ou URL.",
            "- Une valeur qui ne vient d'aucune source de la base ni d'une page lue est marquée « non sourcé ».",
            "- Si deux sources se contredisent, donne les deux valeurs et leurs sources, sans trancher en silence.",
            "- Les fichiers se lisent avec Read ; cherche dans `references/` avec Grep avant de répondre sur un chiffre.",
            "",
            "## Fiches de référence (font foi)",
            "",
        ]
        fiches = self.fiches()
        lignes += [f"- `{f['chemin']}`" for f in fiches] or ["- Aucune fiche pour l'instant."]
        documents = [s for s in sources if s["chemin"] and s["etat"] == "indexe"]
        if documents:
            lignes += ["", "## Documents et copies locales", ""]
            lignes += [
                f"- {s['titre']} : `{s['chemin']}`" + (f" (source : {s['url']})" if s["url"] else "")
                for s in documents
            ]
        demande = [s for s in sources if s["type"] == "lien" and s["mode"] == "a_la_demande"]
        if demande:
            lignes += ["", "## Sites à interroger en priorité lors d'une recherche web", ""]
            lignes += [f"- {s['titre']} : {s['url']}" for s in demande]
        self.depot.ecrire(
            "memoire/references.md", "\n".join(lignes) + "\n", "Consignes de la base documentaire régénérées"
        )
