import subprocess

import pytest

from app.config import Config
from app.main import creer_application
from tests.conftest import Client

CHEMIN = "Boulangerie et viennoiserie/Brioche du dimanche.cook"


@pytest.fixture
def distant(tmp_path):
    """Un dépôt Git nu (GitHub) et un dossier local servant de destination rclone (Drive)."""
    nu = tmp_path / "github.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(nu)], check=True)
    drive = tmp_path / "drive"
    drive.mkdir()
    return nu, drive


@pytest.fixture
def client(tmp_path, moteur, distant):
    nu, drive = distant
    config = Config(
        racine=tmp_path / "srv", moteur="factice", front=tmp_path / "absent",
        git_remote_recettes=str(nu), rclone_dest=str(drive), intervalle_controle=3600,
    )  # fmt: skip
    app = creer_application(config, moteur)
    with Client(app) as c:
        c.ctx, c.moteur, c.drive, c.nu = app.state.ctx, moteur, drive, nu
        yield c


def enregistrer(client, texte="Analyse ma brioche", **params):
    _, p = client.proposer(texte)
    r = client.post(f"/api/propositions/{p['id']}/valider", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_commit_pousse_et_miroir(client):
    """S-1, S-2 : après validation, le fichier est sur le dépôt distant et dans le miroir, en texte brut."""
    r = enregistrer(client)
    assert (client.drive / CHEMIN).read_text() == r["proposition"]["contenu"]
    assert not (client.drive / ".git").exists()
    log = subprocess.run(["git", "log", "--format=%s", "main"], cwd=client.nu, capture_output=True, text=True).stdout
    assert f"Création : {CHEMIN}" in log
    journal = client.get("/api/synchro").json()
    assert {j["cible"] for j in journal["journal"]} >= {"github", "drive"} and all(j["resultat"] == "ok" for j in journal["journal"])
    assert journal["etat"]["dernier_commit"] == journal["etat"]["dernier_commit_synchronise"]


def test_modification_externe_importee(client):
    """S-3 : un fichier modifié côté Drive est importé et commité avant toute écriture."""
    enregistrer(client)
    autre = client.drive / "Dessert" / "Flan.cook"
    autre.parent.mkdir()
    autre.write_text("---\ntitle: Flan\n---\nCuire le @lait{500%g}.\n")
    (client.drive / CHEMIN).write_text((client.drive / CHEMIN).read_text() + "\n> retouche faite sur le PC\n")
    bilan = client.post("/api/synchro").json()["bilan"]
    assert sorted(bilan["importes"]) == [CHEMIN, "Dessert/Flan.cook"] and bilan["conflits"] == []
    assert "retouche faite sur le PC" in (client.ctx.recettes.racine / CHEMIN).read_text()
    assert client.ctx.recettes.historique()[0]["sujet"].startswith("Modification externe")
    assert any(j["cible"] == "import" for j in client.get("/api/synchro").json()["journal"])


def test_conflit_conserve_les_deux_versions(client):
    """S-4 : le fichier cible a été modifié côté Drive ; rien n'est écrasé en silence."""
    enregistrer(client)
    (client.drive / CHEMIN).write_text("---\ntitle: Version du PC\n---\nPétrir la @farine{300%g}.\n")
    _, p = client.proposer("modifie ma brioche")
    r = client.post(f"/api/propositions/{p['id']}/valider").json()
    conflits = [f for f in client.ctx.recettes.fichiers() if ".conflit-" in f]
    assert r["conflits"] == conflits and len(conflits) == 1 and "Version du PC" in (client.ctx.recettes.racine / conflits[0]).read_text()
    assert "{35%g}" in (client.ctx.recettes.racine / CHEMIN).read_text()
    assert client.get("/api/synchro").json()["etat"]["conflits"] == conflits
    assert (client.drive / conflits[0]).exists()  # la copie de conflit est aussi dans le miroir


def test_echec_drive_n_annule_pas_le_commit(client):
    enregistrer(client)
    client.ctx.config.rclone_dest = "inexistant:dossier"
    r = enregistrer(client, "modifie ma brioche")
    assert r["commit"] and any("divergence" in a for a in r["avertissements"])
    etat = client.get("/api/synchro").json()
    assert any(j["resultat"] == "echec" for j in etat["journal"])
    assert etat["etat"]["dernier_commit"] != etat["etat"]["dernier_commit_synchronise"]
    # Drive revient : le serveur était en avance, pas de faux conflit, le miroir est rattrapé
    client.ctx.config.rclone_dest = str(client.drive)
    bilan = client.post("/api/synchro").json()["bilan"]
    assert bilan["ok"] and bilan["importes"] == [] and bilan["conflits"] == []
    assert "{35%g}" in (client.drive / CHEMIN).read_text()


def test_fichiers_de_l_appli_cook_preserves(client):
    """Les fichiers de l'appli (.bookmarks, .shopping-list) présents côté Drive ne sont ni importés ni supprimés."""
    enregistrer(client)
    (client.drive / ".shopping-list").write_text("farine")
    client.post("/api/synchro")
    assert not (client.ctx.recettes.racine / ".shopping-list").exists()
    assert (client.drive / ".shopping-list").exists()
