"""Moteur compatible OpenAI : le SDK réel parle à un faux fournisseur, aucun appel réseau."""

import asyncio
import json

import httpx
import openai
import pytest

from app.config import Config
from app.main import creer_application
from app.moteur.base import Demande
from app.moteur.openai_compat import MoteurOpenAI, lire_modeles, lire_tarifs
from app.moteur.outils_web import LectureWeb
from tests.conftest import Client


def flux(
    texte: str = "", appels: list[dict] | None = None, arret: str = "stop", usage: dict | None = None
) -> bytes:
    """Réponse en streaming au format chat.completions : fragments de texte, puis appels d'outils, puis usage."""
    morceaux = []

    def bloc(delta=None, fin=None, **extra):
        choix = (
            []
            if delta is None and fin is None
            else [{"index": 0, "delta": delta or {}, "finish_reason": fin}]
        )
        morceaux.append(
            {
                "id": "c1",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "m",
                "choices": choix,
                **extra,
            }
        )

    bloc({"role": "assistant", "content": ""})
    for i in range(0, len(texte), 6):
        bloc({"content": texte[i : i + 6]})
    for index, appel in enumerate(appels or []):
        arguments = json.dumps(appel["arguments"])
        bloc(
            {
                "tool_calls": [
                    {
                        "index": index,
                        "id": appel["id"],
                        "type": "function",
                        "function": {"name": appel["nom"], "arguments": ""},
                    }
                ]
            }
        )
        for i in range(0, len(arguments), 9):  # les arguments arrivent en fragments
            bloc({"tool_calls": [{"index": index, "function": {"arguments": arguments[i : i + 9]}}]})
    bloc({}, fin="tool_calls" if appels and arret == "stop" else arret)
    bloc(usage={"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500} | (usage or {}))
    return ("".join(f"data: {json.dumps(m)}\n\n" for m in morceaux) + "data: [DONE]\n\n").encode()


class FauxFournisseur:
    def __init__(self):
        self.reponses: list = []
        self.requetes: list[dict] = []
        self.entetes: list = []
        self.urls: list[str] = []

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        self.requetes.append(json.loads(requete.content))
        self.entetes.append(requete.headers)
        self.urls.append(str(requete.url))
        reponse = self.reponses.pop(0)
        if isinstance(reponse, bytes):
            return httpx.Response(200, content=reponse, headers={"content-type": "text/event-stream"})
        return reponse

    def client(self) -> openai.AsyncOpenAI:
        return openai.AsyncOpenAI(
            api_key="cle-de-test", base_url="https://fournisseur.example/api/v1", max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(self)),
        )  # fmt: skip


def page_web(requete: httpx.Request) -> httpx.Response:
    if requete.url.host == "recettes.example":
        return httpx.Response(
            200,
            html="<html><head><title>Brioche</title></head><body><p>250 g de farine T45.</p></body></html>",
        )
    return httpx.Response(404)


@pytest.fixture
def fournisseur():
    return FauxFournisseur()


@pytest.fixture
def config(tmp_path):
    return Config(
        racine=tmp_path / "srv", moteur="openai", front=tmp_path / "absent",
        openai_modeles="rapide=mistralai/mistral-small, openai/gpt-5, sonnet=anthropic/claude-sonnet-4.5",
        openai_tarifs="openai/gpt-5=1.25/10",
    )  # fmt: skip


@pytest.fixture
def moteur_openai(config, fournisseur):
    from app.initialisation import initialiser

    recettes, _ = initialiser(config)
    recettes.ecrire("Dessert/Flan.cook", "---\ntitle: Flan\n---\nCuire le @lait{500%g}.\n", "essai")
    web = LectureWeb(httpx.AsyncClient(transport=httpx.MockTransport(page_web)), verifier_hote=False)
    return MoteurOpenAI(config, fournisseur.client(), web)


def derouler(moteur, demande) -> list:
    async def collecter():
        return [ev async for ev in moteur.run(demande)]

    return asyncio.run(collecter())


def test_configuration_des_modeles_et_tarifs(moteur_openai):
    assert lire_modeles("a=x/y, z ,") == {"a": "x/y", "z": "z"}
    assert lire_tarifs("x/y=1.5/6, mauvais, z=2") == {"x/y": (1.5, 6.0), "z": (2.0, 2.0)}
    assert moteur_openai.modeles() == ["rapide", "openai/gpt-5", "sonnet"]
    assert moteur_openai.resoudre_modele("rapide") == "mistralai/mistral-small"
    assert moteur_openai.resoudre_modele("openai/gpt-5") == "openai/gpt-5"
    assert (
        moteur_openai.resoudre_modele("haiku") == "mistralai/mistral-small"
    )  # alias inconnu : premier modèle configuré


def test_tour_simple_requete_standard(moteur_openai, fournisseur):
    fournisseur.reponses = [flux("Bonjour Louis, voici.")]
    evs = derouler(moteur_openai, Demande("Salut", "openai/gpt-5", consignes="CONSIGNES DU SERVEUR"))
    assert [e.type for e in evs][0] == "session" and evs[-1].type == "fin"
    assert "".join(e.texte for e in evs if e.type == "texte") == "Bonjour Louis, voici."
    assert evs[0].session.startswith("oai-")
    assert evs[-1].cout == pytest.approx((1000 * 1.25 + 500 * 10) / 1e6)  # tarif configuré

    requete = fournisseur.requetes[0]
    assert fournisseur.urls[0] == "https://fournisseur.example/api/v1/chat/completions"
    assert fournisseur.entetes[0]["authorization"] == "Bearer cle-de-test"
    assert (
        requete["model"] == "openai/gpt-5"
        and requete["stream"] is True
        and requete["stream_options"] == {"include_usage": True}
    )
    assert "max_tokens" not in requete and "temperature" not in requete
    systeme, utilisateur = requete["messages"]
    assert systeme["role"] == "system" and utilisateur == {"role": "user", "content": "Salut"}
    for attendu in (
        "chef pâtissier-formateur",
        "KitchenAid Classic 5K45SS",
        "recette-cook",
        "CONSIGNES DU SERVEUR",
    ):
        assert attendu in systeme["content"], attendu
    # uniquement des outils de lecture, au format `function`
    assert [o["function"]["name"] for o in requete["tools"]] == ["Read", "Glob", "Grep", "WebFetch"]
    assert all(
        o["type"] == "function" and "eager_input_streaming" not in o["function"] for o in requete["tools"]
    )
    assert requete["tools"][0]["function"]["parameters"]["required"] == ["file_path"]


def test_outils_fragmentes_resultats_et_reprise(moteur_openai, fournisseur, config):
    chemin = str(config.recettes / "Dessert/Flan.cook")
    fournisseur.reponses = [
        flux(
            "Je regarde.",
            appels=[
                {"id": "call_1", "nom": "Read", "arguments": {"file_path": chemin}},
                {"id": "call_2", "nom": "Read", "arguments": {"file_path": "/etc/passwd"}},
                {"id": "call_3", "nom": "WebFetch", "arguments": {"url": "https://recettes.example/brioche"}},
                {"id": "call_4", "nom": "Bash", "arguments": {"command": "rm -rf /"}},
            ],
        ),
        flux("Il faut 500 g de lait."),
        flux("Du flan."),
    ]
    evs = derouler(moteur_openai, Demande("Combien de lait ?", "rapide"))
    assert [(e.nom, e.detail) for e in evs if e.type == "outil"] == [
        ("Read", chemin), ("Read", "/etc/passwd"), ("WebFetch", "https://recettes.example/brioche"), ("Bash", ""),
    ]  # fmt: skip
    assert "".join(e.texte for e in evs if e.type == "texte") == "Je regarde.\n\nIl faut 500 g de lait."

    messages = fournisseur.requetes[1]["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "tool", "tool", "tool", "tool"]
    appels = messages[2]["tool_calls"]
    assert [a["id"] for a in appels] == ["call_1", "call_2", "call_3", "call_4"]
    assert json.loads(appels[0]["function"]["arguments"]) == {"file_path": chemin}  # fragments réassemblés
    lu, refuse, page, inconnu = messages[3:]
    assert lu["tool_call_id"] == "call_1" and "@lait{500%g}" in lu["content"]
    assert "refusé" in refuse["content"] and "root:" not in refuse["content"]
    assert (
        "250 g de farine T45" in page["content"]
        and "Source : https://recettes.example/brioche" in page["content"]
    )
    assert inconnu["content"] == "Outil inconnu : Bash"  # ni shell ni écriture, quel que soit le modèle

    # reprise : l'historique vient du fichier de session, le prompt système est reconstruit
    derouler(
        moteur_openai,
        Demande("De quoi parlait-on ?", "rapide", session=evs[0].session, consignes="NOUVEAU RÉGLAGE"),
    )
    suite = fournisseur.requetes[2]["messages"]
    assert suite[1:7] == messages[1:] and suite[-1] == {"role": "user", "content": "De quoi parlait-on ?"}
    assert "NOUVEAU RÉGLAGE" in suite[0]["content"]  # PA-2 : appliqué dès le tour suivant
    assert [m["role"] for m in suite].count("system") == 1


def test_image_arguments_invalides_et_vision(moteur_openai, fournisseur, config):
    (config.agent / "pieces" / "photo.png").write_bytes(b"\x89PNG")
    lecture = {"id": "c1", "nom": "Read", "arguments": {"file_path": "pieces/photo.png"}}
    fournisseur.reponses = [flux(appels=[lecture]), flux("Vu.")]
    derouler(moteur_openai, Demande("Regarde la photo", "rapide"))
    messages = fournisseur.requetes[1]["messages"]
    assert messages[-2]["role"] == "tool" and messages[-1]["role"] == "user"
    assert messages[-1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")

    moteur_openai.config.openai_vision = False
    fournisseur.reponses = [flux(appels=[lecture]), flux("Tant pis.")]
    derouler(moteur_openai, Demande("Regarde la photo", "rapide"))
    assert "ne lit pas les images" in fournisseur.requetes[3]["messages"][-1]["content"]

    # arguments JSON illisibles : résultat d'erreur, pas d'exception
    casse = flux(appels=[{"id": "c9", "nom": "Read", "arguments": {}}]).replace(
        b'"arguments": "{}"', b'"arguments": "{file_path"'
    )
    fournisseur.reponses = [casse, flux("Je reformule.")]
    evs = derouler(moteur_openai, Demande("x", "rapide"))
    assert evs[-1].type == "fin" and "illisibles" in fournisseur.requetes[5]["messages"][-1]["content"]


def test_cout_annonce_corps_extra_et_tour_ephemere(config, fournisseur):
    config.openai_corps_extra = '{"plugins": [{"id": "web"}], "provider": {"sort": "price"}}'
    config.openai_max_tokens = 4000
    moteur = MoteurOpenAI(config, fournisseur.client())
    fournisseur.reponses = [flux("ok", usage={"cost": 0.0042}), flux("Brioche trop sèche")]
    evs = derouler(moteur, Demande("x", "rapide"))
    assert evs[-1].cout == pytest.approx(
        0.0042
    )  # coût annoncé par le fournisseur, prioritaire sur les tarifs
    requete = fournisseur.requetes[0]
    assert (
        requete["plugins"] == [{"id": "web"}]
        and requete["provider"] == {"sort": "price"}
        and requete["max_tokens"] == 4000
    )

    evs = derouler(moteur, Demande("Donne un titre", "haiku", ephemere=True))
    titre = fournisseur.requetes[1]
    assert "tools" not in titre and [m["role"] for m in titre["messages"]] == ["user"]
    assert evs[-1].session is None and evs[-1].cout == 0.0  # modèle sans tarif connu : coût non estimé


def test_arrets_et_erreurs(moteur_openai, fournisseur, config):
    fournisseur.reponses = [flux("Début", arret="length")]
    evs = derouler(moteur_openai, Demande("x", "rapide"))
    assert evs[-1].type == "fin" and "longueur maximale" in evs[-2].texte
    fournisseur.reponses = [flux("", arret="content_filter")]
    assert derouler(moteur_openai, Demande("x", "rapide"))[-1].code == "refus"
    fournisseur.reponses = [flux("")]
    assert derouler(moteur_openai, Demande("x", "rapide"))[-1].code == "moteur"  # réponse vide

    def erreur(statut, message):
        return httpx.Response(statut, json={"error": {"message": message, "code": statut}})

    cas = [
        (erreur(401, "No auth credentials found"), "authentification_api"),
        (erreur(402, "Insufficient credits"), "credit_api"),
        (erreur(429, "Rate limit exceeded"), "debit"),
        (erreur(429, "You exceeded your current quota"), "credit_api"),
        (erreur(503, "Provider unavailable"), "surcharge"),
        (erreur(400, "bad tool schema"), "moteur"),
    ]
    for reponse, code in cas:
        fournisseur.reponses = [reponse]
        assert derouler(moteur_openai, Demande("x", "rapide"))[-1].code == code, code
    assert (
        derouler(moteur_openai, Demande("x", "rapide", session="oai-" + "0" * 36))[-1].code
        == "session_introuvable"
    )
    # une session d'un autre moteur n'est pas reconnue
    assert not moteur_openai.reconnait("api-" + "0" * 36) and moteur_openai.reconnait("oai-x")

    sans_modele = MoteurOpenAI(Config(racine=config.racine, openai_modeles=""), fournisseur.client())
    assert "AC_OPENAI_MODELES" in derouler(sans_modele, Demande("x", "sonnet"))[-1].texte


def test_application_complete_sur_un_fournisseur_openai(config, fournisseur):
    """AC_MOTEUR=openai : modèles du fournisseur dans l'interface, même pipeline de propositions."""
    bloc = "```proposition\ncible: recette\ntype: creation\nchemin: Dessert/Riz au lait.cook\n---\n---\ntitle: Riz au lait\n---\nCuire le @riz{100%g}.\n```"
    fournisseur.reponses = [flux("Voici.\n\n" + bloc, usage={"cost": 0.01}), flux("Riz au lait")]
    with Client(creer_application(config, MoteurOpenAI(config, fournisseur.client()))) as c:
        sante = c.get("/api/sante").json()
        assert sante["moteur"] == "openai" and sante["modeles"] == ["rapide", "openai/gpt-5", "sonnet"]
        assert sante["modele_defaut"] == "sonnet"  # AC_MODELE_DEFAUT quand il figure dans la liste
        assert c.post("/api/discussions", json={"modele": "opus"}).status_code == 400
        d = c.post("/api/discussions", json={"modele": "openai/gpt-5"}).json()["id"]
        fin = dict(c.envoyer(d, "Une recette de riz au lait, enregistre"))["fin"]
        assert fournisseur.requetes[0]["model"] == "openai/gpt-5"
        assert fin["message"]["moteur"] == "openai" and fin["discussion"]["titre"] == "Riz au lait"
        proposition = fin["message"]["propositions"][0]
        assert c.post(f"/api/propositions/{proposition['id']}/valider").status_code == 200
        quota = c.get("/api/quota").json()
        assert quota["cout_api"] == pytest.approx(0.01) and quota["cout"] == 0


def test_secours_openai_derriere_le_cli(tmp_path, moteur, fournisseur):
    """Le moteur OpenAI sert aussi de secours : l'alias du CLI (« sonnet ») est traduit par le catalogue."""
    config = Config(racine=tmp_path / "srv", moteur="factice", front=tmp_path / "absent",
                    openai_modeles="sonnet=anthropic/claude-sonnet-4.5,haiku=google/gemini-flash")  # fmt: skip
    with Client(creer_application(config, moteur, MoteurOpenAI(config, fournisseur.client()))) as c:
        d = c.discussion()
        c.envoyer(d, "Ma brioche est trop sèche")
        moteur.erreur = "quota"
        fournisseur.reponses = [flux("Ajoute 20 g de lait.")]
        fin = dict(c.envoyer(d, "Et si j'ajoute du lait ?"))["fin"]
        assert fin["message"]["moteur"] == "openai" and fin["message"]["contenu"] == "Ajoute 20 g de lait."
        requete = fournisseur.requetes[0]
        assert (
            requete["model"] == "anthropic/claude-sonnet-4.5"
            and "<historique>" in requete["messages"][1]["content"]
        )
        assert fin["discussion"]["session_claude"].startswith("oai-")
        assert c.get("/api/sante").json()["modeles"] == [
            "sonnet",
            "opus",
            "haiku",
        ]  # l'interface garde ceux du moteur principal
