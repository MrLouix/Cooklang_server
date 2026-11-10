import subprocess

from app.propositions import BLOC, analyser_bloc

CHEMIN = "Boulangerie et viennoiserie/Brioche du dimanche.cook"


def git(depot, *args):
    return subprocess.run(["git", *args], cwd=depot, capture_output=True, text=True, check=True).stdout


def test_extraction_des_blocs():
    texte = "Avant\n\n```proposition\ncible: recette\ntype: création\nchemin: `Dessert/Flan.cook`\n---\n---\ntitle: Flan\n---\nCuire.\n```\n\nAprès"
    bloc = analyser_bloc(BLOC.search(texte).group(2))
    assert bloc == {"cible": "recette", "type": "creation", "chemin": "Dessert/Flan.cook", "contenu": "---\ntitle: Flan\n---\nCuire.\n"}
    assert analyser_bloc("cible: recette\nchemin: x.cook\ncontenu sans séparateur") is None
    imbrique = "````proposition\ncible: fiche\ntype: creation\nchemin: references/fiches/a.md\n---\n# A\n```\ncode\n```\n````"
    assert "```\ncode\n```" in analyser_bloc(BLOC.search(imbrique).group(2))["contenu"]


def test_rien_n_est_ecrit_sans_validation(client):
    """Critère d'acceptation : aucun fichier n'est écrit sans appui sur « Enregistrer »."""
    avant = git(client.ctx.recettes.racine, "status", "--porcelain"), client.ctx.recettes.tete()
    d, p = client.proposer()
    assert p["etat"] == "en_attente" and p["chemin"] == CHEMIN and p["existe"] is False
    assert "[[proposition:" in client.get(f"/api/discussions/{d}").json()["messages"][-1]["contenu"]
    assert (git(client.ctx.recettes.racine, "status", "--porcelain"), client.ctx.recettes.tete()) == avant
    assert not (client.ctx.recettes.racine / CHEMIN).exists()


def test_validation_ecrit_et_commite(client):
    d, p = client.proposer()
    r = client.post(f"/api/propositions/{p['id']}/valider").json()
    assert r["proposition"]["etat"] == "validee" and r["commit"]
    assert (client.ctx.recettes.racine / CHEMIN).read_text() == p["contenu"]
    message = git(client.ctx.recettes.racine, "log", "-1", "--format=%B")
    assert message.startswith(f"Création : {CHEMIN}") and d in message and "Brioche du dimanche" in message
    assert client.post(f"/api/propositions/{p['id']}/valider").status_code == 409
    # recette liée à la discussion (D-1) et discussions liées à la recette (D-6)
    assert client.get(f"/api/discussions/{d}").json()["recettes"] == [CHEMIN]
    assert client.get(f"/api/recettes/{CHEMIN}/discussions").json()[0]["id"] == d


def test_rejet(client):
    _, p = client.proposer()
    assert client.post(f"/api/propositions/{p['id']}/rejeter").json()["etat"] == "rejetee"
    assert client.post(f"/api/propositions/{p['id']}/valider").status_code == 409
    assert not (client.ctx.recettes.racine / CHEMIN).exists()


def test_cook_invalide_refuse(client):
    client.moteur.reponse = "```proposition\ncible: recette\ntype: creation\nchemin: Dessert/Raté.cook\n---\n---\ntitle: Raté\nservings: 2 parts\n---\nMélanger @farine{250%g\n```"
    d = client.discussion()
    p = dict(client.envoyer(d, "x"))["fin"]["message"]["propositions"][0]
    r = client.post(f"/api/propositions/{p['id']}/valider")
    assert r.status_code == 422 and r.json()["code"] == "syntaxe"
    assert any("servings" in e for e in r.json()["erreurs"]) and any("accolade" in e for e in r.json()["erreurs"])
    assert "Raté.cook" in r.json()["message_assistant"]
    assert not (client.ctx.recettes.racine / "Dessert/Raté.cook").exists()
    assert client.get(f"/api/propositions/{p['id']}").json()["etat"] == "en_attente"


def test_chemins_dangereux_ignores(client):
    for chemin in ("../evasion.cook", "/etc/passwd.cook", ".git/config.cook", "Dessert/x.txt", "racine.cook"):
        client.moteur.reponse = f"```proposition\ncible: recette\ntype: creation\nchemin: {chemin}\n---\nx\n```"
        fin = dict(client.envoyer(client.discussion(), "x"))["fin"]
        assert fin["message"]["propositions"] == [], chemin


def test_modification_diff_et_fichier_change(client):
    _, p = client.proposer()
    client.post(f"/api/propositions/{p['id']}/valider")
    _, modif = client.proposer("modifie ma brioche")
    assert modif["type"] == "modification" and modif["existe"] and "{30%g}" in modif["original"] and "{35%g}" in modif["contenu"]
    # le fichier change entre la proposition et la validation : pas d'écrasement silencieux (F-9)
    client.ctx.recettes.ecrire(CHEMIN, modif["original"] + "\n> note ajoutée à la main\n", "édition manuelle")
    r = client.post(f"/api/propositions/{modif['id']}/valider")
    assert r.status_code == 409 and r.json()["code"] == "fichier_modifie" and "note ajoutée" in r.json()["original"]
    assert client.post(f"/api/propositions/{modif['id']}/valider", params={"forcer": True}).status_code == 200
    assert "{35%g}" in (client.ctx.recettes.racine / CHEMIN).read_text()


def test_historique_et_restauration(client):
    _, p = client.proposer()
    client.post(f"/api/propositions/{p['id']}/valider")
    _, modif = client.proposer("modifie ma brioche")
    client.post(f"/api/propositions/{modif['id']}/valider")
    recette = client.get(f"/api/recettes/{CHEMIN}").json()
    assert len(recette["historique"]) == 2 and recette["historique"][0]["sujet"].startswith("Modification")
    ancienne = recette["historique"][1]["sha"]
    assert "{30%g}" in client.get(f"/api/recettes/{CHEMIN}/version/{ancienne}").json()["contenu"]
    r = client.post(f"/api/recettes/{CHEMIN}/restaurer", json={"sha": ancienne}).json()
    assert "{30%g}" in r["contenu"]
    assert len(client.get(f"/api/recettes/{CHEMIN}/historique").json()) == 3  # nouveau commit, historique intact


def test_navigation_recherche_et_contexte(client):
    _, p = client.proposer()
    client.post(f"/api/propositions/{p['id']}/valider")
    arbre = client.get("/api/recettes").json()["categories"]
    assert arbre[0]["nom"] == "Boulangerie et viennoiserie" and arbre[0]["recettes"][0]["nom"] == "Brioche du dimanche"
    assert client.get("/api/recettes", params={"q": "petrissage crochet"}).json()["categories"]
    assert client.get("/api/recettes", params={"q": "saumon"}).json()["categories"] == []
    assert client.get("/api/recettes/..%2F..%2Fetc/passwd").status_code in (400, 404)
    d = client.discussion(recette=CHEMIN)
    client.envoyer(d, "Que penses-tu du sucre ?")
    assert "Recette en contexte" in client.moteur.demandes[-1].message and CHEMIN in client.moteur.demandes[-1].message
    assert client.get(f"/api/discussions/{d}").json()["domaine"] == "Viennoiserie"


def test_pieces_jointes(client):
    r = client.post("/api/pieces", files={"fichier": ("recette.jpg", b"\xff\xd8\xff", "image/jpeg")})
    assert r.status_code == 201
    piece = r.json()
    assert client.post("/api/pieces", files={"fichier": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 415
    d = client.discussion()
    client.envoyer(d, "Regarde cette photo", pieces=[piece])
    assert f"pieces/{piece['fichier']}" in client.moteur.demandes[0].message
    assert client.get(f"/api/pieces/{piece['fichier']}").content == b"\xff\xd8\xff"
    assert client.post(f"/api/discussions/{d}/messages", json={"texte": "x", "pieces": [{"fichier": "../CLAUDE.md"}]}).status_code == 400
