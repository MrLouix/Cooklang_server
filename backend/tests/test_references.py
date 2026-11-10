import io
import zipfile

import httpx
import pytest

from app.references import GABARIT_FICHE, decouper, html_en_markdown

PAGE = """<html><head><title>Baker's percentage</title><script>alert(1)</script></head><body>
<nav>Menu</nav><h1>Desired dough temperature</h1><p>Aim for a dough temperature of 24&nbsp;°C to 26 °C.</p>
<ul><li>Salt: 1.8 to 2 %</li></ul></body></html>"""


@pytest.fixture
def client(client):
    def repondre(requete: httpx.Request) -> httpx.Response:
        if requete.url.host == "ok.example":
            return httpx.Response(200, html=PAGE)
        if requete.url.host == "payant.example":
            return httpx.Response(402)
        return httpx.Response(404)

    client.ctx.references.client = httpx.Client(transport=httpx.MockTransport(repondre))
    client.ctx.references.verifier_hote = False
    return client


def pdf_simple(texte: str) -> bytes:
    """Un PDF minimal d'une page contenant `texte`."""
    flux = f"BT /F1 12 Tf 72 720 Td ({texte}) Tj ET".encode()
    objets = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(flux) + flux + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    sortie, positions = io.BytesIO(), []
    sortie.write(b"%PDF-1.4\n")
    for i, objet in enumerate(objets, 1):
        positions.append(sortie.tell())
        sortie.write(b"%d 0 obj\n" % i + objet + b"\nendobj\n")
    xref = sortie.tell()
    sortie.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objets) + 1))
    for position in positions:
        sortie.write(b"%010d 00000 n \n" % position)
    sortie.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objets) + 1, xref))
    return sortie.getvalue()


def test_conversion_html():
    titre, texte = html_en_markdown(PAGE)
    assert titre == "Baker's percentage" and "# Desired dough temperature" in texte
    assert "- Salt: 1.8 to 2 %" in texte and "alert" not in texte and "Menu" not in texte
    assert len(decouper("a" * 1000 + "\n\n" + "b" * 1000)) == 2


def test_documents_import_indexation_recherche(client):
    md = "# Notes brioche\n\nHydratation totale d'une brioche : 55 à 65 %.\n\nTempérature à cœur : 92 °C."
    r = client.post("/api/references", files={"fichier": ("notes brioche.md", md.encode(), "text/markdown")})
    assert r.status_code == 201
    pdf = client.post("/api/references", files={"fichier": ("cristallisation.pdf", pdf_simple("Chocolat noir tempere a 31 degres"), "application/pdf")}).json()
    epub = io.BytesIO()
    with zipfile.ZipFile(epub, "w") as z:
        z.writestr("ch1.xhtml", "<html><body><h1>Farines</h1><p>La T45 contient 9 % de protéines.</p></body></html>")
    client.post("/api/references", files={"fichier": ("ingredients.epub", epub.getvalue(), "application/epub+zip")})
    assert client.post("/api/references", files={"fichier": ("x.docx", b"x", "x")}).status_code == 422
    sources = client.get("/api/references").json()["sources"]
    assert {s["etat"] for s in sources} == {"indexe"} and all(s["passages"] >= 1 for s in sources)
    dossier = client.ctx.config.agent / "references" / "documents" / str(pdf["id"])
    assert (dossier / "original.pdf").exists() and "<!-- page 1 -->" in (dossier / "texte.md").read_text()  # original conservé, pages repérées
    trouves = client.get("/api/references/recherche", params={"q": "température coeur"}).json()
    assert trouves and "92" in trouves[0]["extrait"] and trouves[0]["titre"] == "notes brioche"
    assert client.get("/api/references/recherche", params={"q": "tempere"}).json()[0]["page"] == 1
    assert client.get("/api/references/recherche", params={"q": "protéines"}).json()
    # B-9 : les documents importés ne sont pas versionnés
    assert not [f for f in client.ctx.agent.fichiers() if f.startswith("references/documents")]
    # désactivation puis suppression
    identifiant = r.json()["id"]
    client.patch(f"/api/references/{identifiant}", json={"actif": False})
    assert client.get("/api/references/recherche", params={"q": "température coeur"}).json() == []
    assert client.delete(f"/api/references/{identifiant}").status_code == 204
    assert not (client.ctx.config.agent / "references" / "documents" / str(identifiant)).exists()


def test_liens_verification_et_modes(client):
    """B-3, B-11 : l'URL doit répondre, sans compte ni paiement."""
    assert client.post("/api/references", data={"url": "https://absent.example/x", "mode": "a_la_demande"}).status_code == 422
    r = client.post("/api/references", data={"url": "https://payant.example/x", "mode": "a_la_demande"})
    assert r.status_code == 422 and "paiement" in r.json()["detail"]
    assert client.post("/api/references", data={"url": "ftp://ok.example", "mode": "a_la_demande"}).status_code == 422
    demande = client.post("/api/references", data={"url": "https://ok.example/pro", "mode": "a_la_demande"}).json()
    assert demande["titre"] == "Baker's percentage" and demande["etat"] == "accessible"
    copie = client.post("/api/references", data={"url": "https://ok.example/ddt", "mode": "copie_locale", "titre": "Températures de pâte"}).json()
    assert copie["etat"] == "indexe"
    assert client.get("/api/references/recherche", params={"q": "dough temperature"}).json()[0]["titre"] == "Températures de pâte"
    consignes = (client.ctx.config.agent / "memoire" / "references.md").read_text()
    assert "https://ok.example/pro" in consignes and f"references/liens/{copie['id']}/texte.md" in consignes
    assert "non sourcé" in consignes and "sans trancher en silence" in consignes
    assert "references/liens.json" in client.ctx.agent.fichiers()  # la liste des liens est versionnée, pas les copies
    # un lien devenu inaccessible est signalé
    client.ctx.base.executer("UPDATE sources SET url = 'https://absent.example/x' WHERE id = ?", (demande["id"],))
    assert client.post(f"/api/references/{demande['id']}/rafraichir").json()["etat"] == "inaccessible"


def test_url_privee_refusee():
    from app.references import ErreurReference, url_publique

    for url in ("http://127.0.0.1/x", "http://localhost:8000/", "http://192.168.1.10/"):
        with pytest.raises(ErreurReference):
            url_publique(url)


def test_fiches_gabarit_edition_et_proposition(client):
    assert client.put("/api/references/fiches/brioche", json={"contenu": "# Brioche\n\nlibre"}).status_code == 422
    fiche = GABARIT_FICHE.replace("{titre}", "Brioche").replace("| Hydratation |  |  |", "| Hydratation | 55-65 % | King Arthur |")
    assert client.put("/api/references/fiches/Brioche", json={"contenu": fiche}).status_code == 200
    assert client.get("/api/references").json()["fiches"] == [{"nom": "brioche", "chemin": "references/fiches/brioche.md"}]
    assert "references/fiches/brioche.md" in client.ctx.agent.fichiers()  # versionnée (B-9)
    trouves = client.get("/api/references/recherche", params={"q": "hydratation"}).json()
    assert trouves[0]["type"] == "fiche"  # les fiches passent en premier (B-5)
    assert "`references/fiches/brioche.md`" in (client.ctx.config.agent / "memoire" / "references.md").read_text()
    client.delete("/api/references/fiches/brioche")
    assert client.get("/api/references/fiches/brioche").status_code == 404
    # proposée par l'assistant : rien n'entre dans les fiches sans validation (B-8)
    _, p = client.proposer("propose une fiche")
    assert p["cible"] == "fiche" and client.get("/api/references").json()["fiches"] == []
    assert client.post(f"/api/propositions/{p['id']}/valider").status_code == 200
    assert client.get("/api/references/fiches/brioche").json()["contenu"].startswith("# Brioche")
