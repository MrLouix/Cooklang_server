import asyncio

from app.main import creer_application
from tests.conftest import Client


def test_tour_complet_et_historique(client):
    client.moteur.delai = 0.01
    d = client.discussion()
    evenements = client.envoyer(d, "Bonjour, que faire avec 3 œufs ?")
    genres = [g for g, _ in evenements]
    assert genres[0] == "etat" and genres[-1] == "fin" and "texte" in genres
    fin = evenements[-1][1]
    assert fin["message"]["etat"] == "termine"
    assert fin["message"]["cout"] > 0
    historique = client.get(f"/api/discussions/{d}").json()
    assert [m["role"] for m in historique["messages"]] == ["user", "assistant"]
    assert historique["session_claude"]


def test_reprise_de_session(client):
    d = client.discussion()
    client.envoyer(d, "premier")
    session = client.get(f"/api/discussions/{d}").json()["session_claude"]
    client.envoyer(d, "second")
    assert client.moteur.demandes[-1].session == session
    assert "historique" not in client.moteur.demandes[-1].message


def test_session_perdue_apres_redemarrage(config, moteur):
    """D-4 : nouvelle session et historique réinjecté, sans intervention."""
    with Client(creer_application(config, moteur)) as c:
        d = c.discussion()
        c.envoyer(d, "Ma brioche est trop sèche")
    from app.moteur.factice import MoteurFactice

    neuf = MoteurFactice()  # ne connaît plus aucune session
    with Client(creer_application(config, neuf)) as c:
        fin = dict(c.envoyer(d, "Et si j'ajoute du lait ?"))["fin"]
        assert fin["message"]["etat"] == "termine"
        assert len(neuf.demandes) == 2 and neuf.demandes[0].session and neuf.demandes[1].session is None
        assert "<historique>" in neuf.demandes[1].message and "trop sèche" in neuf.demandes[1].message
        assert len(c.get(f"/api/discussions/{d}").json()["messages"]) == 4


def test_titre_automatique_puis_renommage(client):
    d = client.discussion()
    client.envoyer(d, "Analyse ma brioche")
    assert client.get(f"/api/discussions/{d}").json()["titre"] == "Brioche du dimanche"
    assert client.moteur.demandes[-1].ephemere
    client.patch(f"/api/discussions/{d}", json={"titre": "Mon titre"})
    client.envoyer(d, "encore")
    assert client.get(f"/api/discussions/{d}").json()["titre"] == "Mon titre"


def test_recherche_archive_suppression(client):
    a, b = client.discussion(), client.discussion()
    client.envoyer(a, "Parlons de pâte feuilletée")
    client.envoyer(b, "Un yaourt maison")
    trouves = client.get("/api/discussions", params={"q": "feuilletee"}).json()
    assert [d["id"] for d in trouves] == [a] and "**" in trouves[0]["extrait"]
    client.patch(f"/api/discussions/{a}", json={"archivee": True})
    assert [d["id"] for d in client.get("/api/discussions").json()] == [b]
    assert [d["id"] for d in client.get("/api/discussions", params={"archivees": True}).json()] == [a]
    assert client.delete(f"/api/discussions/{b}").status_code == 204
    assert client.get(f"/api/discussions/{b}").status_code == 404
    assert client.get("/api/discussions", params={"q": "yaourt"}).json() == []


def test_dupliquer_a_partir_d_un_message(client):
    d = client.discussion()
    client.envoyer(d, "un")
    client.envoyer(d, "deux")
    messages = client.get(f"/api/discussions/{d}").json()["messages"]
    copie = client.post(f"/api/discussions/{d}/dupliquer", json={"message_id": messages[1]["id"]}).json()
    assert len(client.get(f"/api/discussions/{copie['id']}").json()["messages"]) == 2
    client.envoyer(copie["id"], "suite")
    assert "<historique>" in client.moteur.demandes[-1].message


def test_erreurs_du_moteur(client):
    d = client.discussion()
    client.moteur.erreur = "quota"
    genre, donnees = client.envoyer(d, "bonjour")[-1]
    assert genre == "erreur" and donnees["code"] == "quota" and "crédit" in donnees["message"]
    assert client.get("/api/quota").json()["atteint"] is True
    client.moteur.erreur = "authentification"
    assert client.envoyer(d, "bonjour")[-1][1]["code"] == "authentification"
    assert client.get(f"/api/discussions/{d}").json()["messages"][-1]["etat"] == "erreur"


def test_delai_maximal(client):
    """M-7 : le tour est arrêté et le message porte l'erreur."""
    client.ctx.config.delai_tour = 0.2
    client.moteur.delai = 0.5
    d = client.discussion()
    genre, donnees = client.envoyer(d, "bonjour")[-1]
    assert genre == "erreur" and donnees["code"] == "delai"
    client.moteur.delai = 0
    client.ctx.config.delai_tour = 30
    assert client.envoyer(d, "bonjour")[-1][0] == "fin"  # la file n'est pas bloquée


def test_tour_survit_a_la_deconnexion(client):
    """P-3 : le client part en plein tour, la réponse complète est en base."""
    client.moteur.delai = 0.05
    client.moteur.reponse = "x" * 400
    d = client.discussion()
    with client.stream("POST", f"/api/discussions/{d}/messages", json={"texte": "long"}) as r:
        next(r.iter_lines())  # on lit une ligne puis on coupe
    assert client.post(f"/api/discussions/{d}/messages", json={"texte": "bis"}).status_code == 409
    dernier = client.attendre(lambda: (m := client.get(f"/api/discussions/{d}").json()["messages"][-1])["etat"] == "termine" and m)
    assert dernier["contenu"] == "x" * 400


def test_un_seul_tour_a_la_fois(client):
    """M-5 : deux discussions envoyées ensemble s'exécutent l'une après l'autre."""
    client.moteur.delai = 0.02
    a, b = client.discussion(), client.discussion()
    ordre = []
    original = client.ctx.tours._executer

    async def espion(tour):
        ordre.append(("debut", tour.discussion_id))
        await original(tour)
        ordre.append(("fin", tour.discussion_id))

    client.ctx.tours._executer = espion
    with client.stream("POST", f"/api/discussions/{a}/messages", json={"texte": "a" * 200}) as ra:
        next(ra.iter_lines())
        client.envoyer(b, "b")
    assert ordre[:2] == [("debut", a), ("fin", a)] and ordre[2] == ("debut", b)


def test_message_interrompu_marque_au_redemarrage(config, moteur):
    app = creer_application(config, moteur)
    ctx = app.state.ctx
    with Client(app) as c:
        d = c.discussion()
    ctx.base.executer("INSERT INTO messages(discussion_id, role, etat, cree_le) VALUES(?, 'assistant', 'en_cours', 'x')", (d,))
    with Client(app) as c:
        m = c.get(f"/api/discussions/{d}").json()["messages"][-1]
        assert m["etat"] == "erreur" and "redémarré" in m["erreur_message"]


def test_interpretation_stream_json():
    from app.moteur.claude_cli import interpreter

    etat = {"texte": "", "resultat": False}
    lignes = [
        {"type": "system", "subtype": "init", "session_id": "s1"},
        {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Bon"}}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "WebSearch", "input": {"query": "brioche"}}]}},
        {"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "text"}}},
        {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "jour"}}},
        {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.5, "session_id": "s1", "result": "x"},
    ]
    evs = [e for ligne in lignes for e in interpreter(ligne, etat)]
    assert [e.type for e in evs] == ["session", "texte", "outil", "texte", "texte", "fin"]
    assert etat["texte"] == "Bon\n\njour" and evs[2].detail == "brioche" and evs[-1].cout == 0.5
    erreur = interpreter({"type": "result", "is_error": True, "errors": ["No conversation found with session ID: x"]}, etat)
    assert erreur[0].code == "session_introuvable"


def test_arguments_du_cli(config):
    from app.moteur.base import Demande
    from app.moteur.claude_cli import MoteurClaudeCLI

    args = MoteurClaudeCLI(config).arguments(Demande("m", "sonnet", session="abc", consignes="c"))
    assert args[args.index("--resume") + 1] == "abc"
    assert args[args.index("--tools") + 1] == "Read,Glob,Grep,Skill,WebSearch,WebFetch"
    autorises = args[args.index("--allowedTools") + 1]
    assert "Read" not in autorises and "Write" in args[args.index("--disallowedTools") + 1]
    assert asyncio.run(MoteurClaudeCLI(config).version())
