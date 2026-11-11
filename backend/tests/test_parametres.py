from app import parametres as P
from app.config import Config
from app.main import creer_application
from tests.conftest import Client


def lire_md(client, nom="parametres.md"):
    return (client.ctx.config.agent / "memoire" / nom).read_text()


def test_defauts_et_schema(client):
    r = client.get("/api/parametres").json()
    assert (
        r["valeurs"]["oeufs"] == "grammes_nombre"
        and r["valeurs"]["poids_oeuf"] == 50
        and r["valeurs"] == r["defauts"]
    )
    schema = client.get("/api/parametres/schema").json()
    assert [s["cle"] for s in schema["sections"]] == ["unites", "alimentation", "domaines"]
    md = lire_md(client)
    assert "grammes ET en nombre" in md and "toujours écrits en grammes" in md and "demande explicite" in md


def test_reglage_oeufs_applique_au_tour_suivant(client):
    """Critère : changer le réglage « Œufs » modifie la présentation dès la réponse suivante (PA-2)."""
    valeurs = client.get("/api/parametres").json()["valeurs"]
    valeurs["oeufs"] = "grammes"
    assert client.put("/api/parametres", json=valeurs).status_code == 200
    md = lire_md(client)
    assert "grammes uniquement" in md and "grammes ET en nombre" not in md
    claude_md = (client.ctx.config.agent / "CLAUDE.md").read_text()
    assert "@memoire/parametres.md" in claude_md  # importé, donc relu par le CLI au tour suivant
    assert "Paramètres modifiés" in [h["sujet"] for h in client.ctx.agent.historique()]


def test_valeurs_refusees(client):
    for mauvais in (
        {"oeufs": "douzaine"},
        {"poids_oeuf": 90},
        {"exclusions": {"porc": "parfois"}},
        {"substitutions": ["x"]},
    ):
        assert client.put("/api/parametres", json=mauvais).status_code == 422, mauvais


def test_claude_md_garde_le_texte_d_origine(client, config):
    original = (config.agent_modele / "CLAUDE.md").read_text()
    assert (config.agent / "CLAUDE.md").read_text().startswith(original.rstrip())
    skill = ".claude/skills/recette-cook/SKILL.md"
    assert (config.agent / skill).read_text() == (config.agent_modele / skill).read_text()


def consignes(client) -> str:
    return [d for d in client.moteur.demandes if not d.ephemere][-1].consignes


def test_texte_de_domaine_injecte_selon_la_discussion(client):
    """PA-4 : le texte libre d'un domaine n'est injecté que si la discussion porte dessus."""
    valeurs = client.get("/api/parametres").json()["valeurs"]
    valeurs["textes_domaines"]["Viennoiserie"] = "Toujours une pousse lente au froid."
    valeurs["textes_domaines"]["Forme des réponses"] = "Pas de smileys."
    valeurs["textes_domaines"]["Barbecue"] = "Cuisson au charbon."
    client.put("/api/parametres", json=valeurs)
    a, b, c = client.discussion(), client.discussion(), client.discussion()
    client.envoyer(a, "Mes croissants manquent de feuilletage")
    assert "pousse lente au froid" in consignes(client)
    client.envoyer(b, "Un yaourt plus ferme ?")
    assert "pousse lente" not in consignes(client)
    assert "Pas de smileys" in consignes(client)  # domaine transversal
    client.envoyer(c, "Des idées pour le barbecue ?")
    assert "charbon" in consignes(client)
    assert client.get(f"/api/discussions/{b}").json()["domaine"] == "Yaourts et fermentations"
    client.patch(f"/api/discussions/{b}", json={"domaine": "Viennoiserie"})
    client.envoyer(b, "suite")
    assert "pousse lente au froid" in consignes(client)


def test_exclusion_stricte_bloque_la_validation(client):
    """Critère : un ingrédient en exclusion stricte déclenche l'avertissement, levé par confirmation (PA-5)."""
    valeurs = client.get("/api/parametres").json()["valeurs"]
    valeurs["exclusions"] = {"lactose": "stricte", "alcool": "souple"}
    valeurs["ingredients_a_eviter"] = [{"nom": "levure fraîche", "niveau": "stricte"}]
    client.put("/api/parametres", json=valeurs)
    assert "Exclusion stricte : lactose" in lire_md(client) and "À éviter : alcool" in lire_md(client)
    _, p = client.proposer()
    r = client.post(f"/api/propositions/{p['id']}/valider")
    assert r.status_code == 409 and r.json()["code"] == "exclusions"
    assert {(a["ingredient"], a["exclusion"]) for a in r.json()["alertes"]} == {
        ("beurre", "lactose"),
        ("levure fraîche", "levure fraîche"),
    }
    assert not (client.ctx.recettes.racine / p["chemin"]).exists()
    assert (
        client.post(f"/api/propositions/{p['id']}/valider", params={"confirmer_exclusions": True}).status_code
        == 200
    )


def test_correspondance_des_exclusions():
    v = P.defauts() | {
        "exclusions": {"fruits à coque": "stricte", "lactose": "stricte", "gluten": "stricte"},
        "regime": "vegetarien",
    }
    ingredients = [{"nom": n} for n in ("noix de coco râpée", "lait d'amande", "Noisettes torréfiées", "beurre de cacao",
                                        "farine de riz", "lardons fumés", "Crème liquide 30 %", "sel")]  # fmt: skip
    trouves = {
        (a["ingredient"], a["exclusion"]) for a in P.verifier_exclusions(v, ingredients, P.SYNONYMES_DEFAUT)
    }
    assert trouves == {
        ("Noisettes torréfiées", "fruits à coque"),
        ("lardons fumés", "régime (porc)"),
        ("Crème liquide 30 %", "lactose"),
    }


def test_detection_du_domaine():
    domaines = P.DOMAINES_DEFAUT
    assert P.detecter_domaine("Ma brioche ne lève pas", domaines) == "Viennoiserie"
    assert P.detecter_domaine("Pain au levain trop dense", domaines) == "Boulangerie"
    assert P.detecter_domaine("Bonjour", domaines) is None


def test_memoire_lecture_edition_et_proposition(client):
    fichiers = {m["fichier"]: m["contenu"] for m in client.get("/api/memoire").json()}
    assert (
        "KitchenAid Classic 5K45SS" in fichiers["materiel.md"]
        and "yaourtière" in fichiers["materiel.md"].lower()
    )
    assert (
        "huile neutre" in fichiers["preferences.md"].lower()
        and "proposition avant écriture" in fichiers["preferences.md"]
    )
    r = client.put(
        "/api/memoire/essais.md", json={"contenu": "# Essais\n\n- Brioche à 60 % d'œufs : réussie."}
    )
    assert "réussie" in r.json()["contenu"]
    assert client.put("/api/memoire/parametres.md", json={"contenu": "x"}).status_code == 404
    assert client.get("/api/memoire/..%2FCLAUDE.md").status_code == 404
    # proposition de mémoire : même mécanisme que les recettes (F-12)
    _, p = client.proposer("retiens que je n'aime pas la fleur d'oranger")
    assert p["cible"] == "memoire" and p["existe"]
    assert "fleur d'oranger" not in client.get("/api/memoire/preferences.md").json()["contenu"]
    client.post(f"/api/propositions/{p['id']}/valider")
    assert "fleur d'oranger" in client.get("/api/memoire/preferences.md").json()["contenu"]


def test_mot_de_passe(tmp_path, moteur):
    """X-2 : mot de passe optionnel, session par cookie ; aucune route de l'API n'est ouverte sans lui."""
    config = Config(
        racine=tmp_path / "srv", moteur="factice", front=tmp_path / "absent", mot_de_passe="secret"
    )
    with Client(creer_application(config, moteur), base_url="https://testserver") as c:
        assert c.get("/api/session").json() == {"protege": True, "connecte": False}
        for chemin in ("/api/discussions", "/api/recettes", "/api/sante", "/api/memoire", "/api/parametres"):
            assert c.get(chemin).status_code == 401
        assert c.post("/api/connexion", json={"mot_de_passe": "faux"}).status_code == 401
        assert c.post("/api/connexion", json={"mot_de_passe": "secret"}).status_code == 200
        assert c.get("/api/discussions").status_code == 200
        c.post("/api/deconnexion")
        c.cookies.clear()
        assert c.get("/api/discussions").status_code == 401


def test_sante_ne_revele_aucun_secret(client, config):
    """X-4 : les secrets ne sont jamais renvoyés par l'API."""
    from pathlib import Path

    Path(config.jeton_fichier).write_text("sk-secret-jeton")
    client.ctx.config.mot_de_passe = ""
    for chemin in ("/api/sante", "/api/synchro", "/api/quota", "/api/parametres"):
        assert "sk-secret" not in client.get(chemin).text
    from app.moteur.claude_cli import MoteurClaudeCLI

    assert MoteurClaudeCLI(config).environnement()["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-secret-jeton"
