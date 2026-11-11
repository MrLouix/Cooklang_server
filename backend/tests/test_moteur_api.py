"""Moteur API : le SDK Anthropic réel parle à un faux serveur HTTP, aucun appel réseau."""

import asyncio
import json

import anthropic
import httpx2 as httpx
import pytest

from app.main import creer_application
from app.moteur.api_anthropic import MoteurAPI, cout_estime, developper_imports
from app.moteur.base import Demande
from app.moteur.outils_lecture import OutilsLecture
from tests.conftest import Client


def sse(
    blocs: list[dict], arret: str = "end_turn", usage: dict | None = None, modele: str = "claude-sonnet-5-5"
) -> bytes:
    """Flux SSE d'une réponse dont le contenu est `blocs` (texte, tool_use, server_tool_use, thinking)."""
    usage = {
        "input_tokens": 1000,
        "output_tokens": 500,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    } | (usage or {})
    evenements = [
        ("message_start", {"type": "message_start", "message": {
            "id": "msg_1", "type": "message", "role": "assistant", "model": modele, "content": [],
            "stop_reason": None, "stop_sequence": None, "usage": usage | {"output_tokens": 0}}}),
    ]  # fmt: skip
    for i, bloc in enumerate(blocs):
        if bloc["type"] == "text":
            depart, deltas = (
                {"type": "text", "text": ""},
                [{"type": "text_delta", "text": m} for m in (bloc["text"][:5], bloc["text"][5:]) if m],
            )
        elif bloc["type"] == "thinking":
            depart, deltas = (
                {"type": "thinking", "thinking": "", "signature": ""},
                [{"type": "signature_delta", "signature": bloc["signature"]}],
            )
        else:
            depart = {**bloc, "input": {}}
            deltas = [{"type": "input_json_delta", "partial_json": json.dumps(bloc["input"])}]
        evenements.append(
            ("content_block_start", {"type": "content_block_start", "index": i, "content_block": depart})
        )
        for delta in deltas:
            evenements.append(
                ("content_block_delta", {"type": "content_block_delta", "index": i, "delta": delta})
            )
        evenements.append(("content_block_stop", {"type": "content_block_stop", "index": i}))
    evenements.append(("message_delta", {"type": "message_delta", "delta": {"stop_reason": arret, "stop_sequence": None},
                                         "usage": {"output_tokens": usage["output_tokens"]}}))  # fmt: skip
    evenements.append(("message_stop", {"type": "message_stop"}))
    return "".join(f"event: {nom}\ndata: {json.dumps(donnees)}\n\n" for nom, donnees in evenements).encode()


class FauxServeur:
    """Rejoue des réponses préparées et garde les requêtes reçues."""

    def __init__(self):
        self.reponses: list[httpx.Response | bytes] = []
        self.requetes: list[dict] = []
        self.entetes: list[httpx.Headers] = []

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        self.requetes.append(json.loads(requete.content))
        self.entetes.append(requete.headers)
        reponse = self.reponses.pop(0)
        if isinstance(reponse, bytes):
            return httpx.Response(200, content=reponse, headers={"content-type": "text/event-stream"})
        return reponse

    def client(self) -> anthropic.AsyncAnthropic:
        return anthropic.AsyncAnthropic(
            api_key="cle-de-test",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(self)),
        )


@pytest.fixture
def serveur():
    return FauxServeur()


@pytest.fixture
def moteur_api(config, serveur):
    from app.initialisation import initialiser

    recettes, _ = initialiser(config)
    recettes.ecrire("Dessert/Flan.cook", "---\ntitle: Flan\n---\nCuire le @lait{500%g}.\n", "essai")
    return MoteurAPI(config, serveur.client())


def derouler(moteur, demande) -> list:
    async def collecter():
        return [ev async for ev in moteur.run(demande)]

    return asyncio.run(collecter())


def test_tour_simple_requete_et_cout(moteur_api, serveur):
    serveur.reponses = [
        sse([{"type": "text", "text": "Bonjour Louis."}], usage={"cache_read_input_tokens": 2000})
    ]
    evs = derouler(moteur_api, Demande("Salut", "sonnet", consignes="CONSIGNES DU SERVEUR"))
    assert [e.type for e in evs] == ["session", "texte", "texte", "fin"]
    assert "".join(e.texte for e in evs if e.type == "texte") == "Bonjour Louis."
    assert evs[0].session.startswith("api-") and evs[-1].session == evs[0].session
    # 1000 × 2 $ + 2000 × 0,10 $ + 500 × 10 $, par million
    assert evs[-1].cout == pytest.approx((1000 * 2 + 2000 * 0.10 + 500 * 10) / 1e6)

    requete = serveur.requetes[0]
    assert (
        requete["model"] == "claude-sonnet-5-5"
        and requete["stream"] is True
        and requete["max_tokens"] == 64000
    )
    assert (
        requete["thinking"] == {"type": "adaptive"}
        and "temperature" not in requete
        and "tool_choice" not in requete
    )
    assert (
        requete["fallbacks"] == "default"
        and "server-side-fallback-2026-07-01" in serveur.entetes[0]["anthropic-beta"]
    )
    systeme = requete["system"][0]
    assert systeme["cache_control"] == {"type": "ephemeral"} and requete["cache_control"] == {
        "type": "ephemeral"
    }
    # CLAUDE.md, mémoire importée, skill listé, consignes du serveur : tout est dans le prompt système
    for attendu in (
        "chef pâtissier-formateur",
        "KitchenAid Classic 5K45SS",
        "recette-cook",
        "SKILL.md",
        "CONSIGNES DU SERVEUR",
    ):
        assert attendu in systeme["text"], attendu
    assert "@memoire/" not in systeme["text"]
    noms = [o["name"] for o in requete["tools"]]
    assert noms == ["Read", "Glob", "Grep", "web_search", "web_fetch"]  # aucun outil d'écriture ni de shell
    assert (
        requete["tools"][3]["type"] == "web_search_20260209"
        and requete["tools"][0]["eager_input_streaming"] is True
    )


def test_boucle_d_outils_et_reprise_de_session(moteur_api, serveur, config):
    chemin = str(config.recettes / "Dessert/Flan.cook")
    serveur.reponses = [
        sse(
            [
                {"type": "thinking", "signature": "sig-1"},
                {"type": "text", "text": "Je lis la recette."},
                {"type": "tool_use", "id": "toolu_1", "name": "Read", "input": {"file_path": chemin}},
                {"type": "tool_use", "id": "toolu_2", "name": "Read", "input": {"file_path": "/etc/passwd"}},
            ],
            arret="tool_use",
        ),
        sse([{"type": "text", "text": "Il faut 500 g de lait."}]),
        sse([{"type": "text", "text": "Du flan."}]),
    ]
    evs = derouler(moteur_api, Demande("Combien de lait ?", "sonnet"))
    assert [(e.nom, e.detail) for e in evs if e.type == "outil"] == [
        ("Read", chemin),
        ("Read", "/etc/passwd"),
    ]
    assert (
        "".join(e.texte for e in evs if e.type == "texte") == "Je lis la recette.\n\nIl faut 500 g de lait."
    )
    assert evs[-1].cout == pytest.approx(2 * (1000 * 2 + 500 * 10) / 1e6)

    seconde = serveur.requetes[1]["messages"]
    assert [m["role"] for m in seconde] == ["user", "assistant", "user"]
    # le tour de l'assistant est rejoué tel quel, bloc de réflexion et signature compris
    assert [b["type"] for b in seconde[1]["content"]] == ["thinking", "text", "tool_use", "tool_use"]
    assert seconde[1]["content"][0]["signature"] == "sig-1"
    # les deux résultats reviennent dans un seul message ; la lecture hors périmètre est une erreur
    lu, refuse = seconde[2]["content"]
    assert lu["tool_use_id"] == "toolu_1" and "@lait{500%g}" in lu["content"] and lu["is_error"] is False
    assert refuse["tool_use_id"] == "toolu_2" and refuse["is_error"] is True and "refusé" in refuse["content"]

    # tour suivant : l'historique est repris depuis le fichier de session, en ajout seul
    session = evs[0].session
    derouler(moteur_api, Demande("De quoi parlait-on ?", "sonnet", session=session))
    troisieme = serveur.requetes[2]
    assert troisieme["messages"][:3] == seconde and troisieme["messages"][-1] == {
        "role": "user",
        "content": "De quoi parlait-on ?",
    }
    assert (
        troisieme["system"] == serveur.requetes[0]["system"]
    )  # préfixe identique : cache et blocs de réflexion valides


def test_consignes_modifiees_ajoutees_sans_reecrire_le_prefixe(moteur_api, serveur):
    """PA-2 avec l'API : un réglage changé en cours de discussion arrive comme message système ajouté."""
    serveur.reponses = [sse([{"type": "text", "text": "un"}]), sse([{"type": "text", "text": "deux"}])]
    session = derouler(moteur_api, Demande("a", "opus", consignes="Œufs en grammes ET en nombre."))[0].session
    derouler(moteur_api, Demande("b", "opus", session=session, consignes="Œufs en grammes uniquement."))
    premiere, seconde = serveur.requetes
    assert seconde["system"] == premiere["system"] and "ET en nombre" in seconde["system"][0]["text"]
    assert [m["role"] for m in seconde["messages"]] == ["user", "assistant", "user", "system"]
    assert (
        "grammes uniquement" in seconde["messages"][-1]["content"]
        and "remplacent" in seconde["messages"][-1]["content"]
    )
    assert seconde["model"] == "claude-opus-5-5"


def test_outil_heberge_pause_refus_et_troncature(moteur_api, serveur):
    recherche = {
        "type": "server_tool_use",
        "id": "srvtoolu_1",
        "name": "web_search",
        "input": {"query": "brioche hydratation"},
    }
    serveur.reponses = [sse([recherche], arret="pause_turn"), sse([{"type": "text", "text": "Voilà."}])]
    evs = derouler(moteur_api, Demande("cherche", "sonnet"))
    assert [(e.nom, e.detail) for e in evs if e.type == "outil"] == [("WebSearch", "brioche hydratation")]
    # tour en pause : renvoyé tel quel, sans message « continue »
    assert [m["role"] for m in serveur.requetes[1]["messages"]] == ["user", "assistant"]
    assert evs[-1].type == "fin"

    refus = sse([], arret="refusal")
    serveur.reponses = [refus]
    evs = derouler(moteur_api, Demande("x", "sonnet"))
    assert evs[-1].type == "erreur" and evs[-1].code == "refus"

    serveur.reponses = [sse([{"type": "text", "text": "Début de réponse"}], arret="max_tokens")]
    evs = derouler(moteur_api, Demande("x", "sonnet"))
    assert evs[-1].type == "fin" and "longueur maximale" in evs[-2].texte


def test_haiku_sans_repli_et_tour_ephemere(moteur_api, serveur):
    serveur.reponses = [sse([{"type": "text", "text": "Brioche trop sèche"}], modele="claude-haiku-5-5")]
    evs = derouler(moteur_api, Demande("Donne un titre", "haiku", ephemere=True))
    requete = serveur.requetes[0]
    assert (
        requete["model"] == "claude-haiku-5-5"
        and "fallbacks" not in requete
        and "tools" not in requete
        and "system" not in requete
    )
    assert (
        "anthropic-beta" not in serveur.entetes[0] or "fallback" not in serveur.entetes[0]["anthropic-beta"]
    )
    assert [e.type for e in evs] == ["texte", "texte", "fin"] and evs[-1].session is None
    assert not moteur_api.sessions.dossier.exists()  # aucun fichier de session pour un titre


def test_erreurs_de_l_api(moteur_api, serveur):
    def erreur(statut, genre, message):
        return httpx.Response(statut, json={"type": "error", "error": {"type": genre, "message": message}})

    cas = [
        (erreur(401, "authentication_error", "invalid x-api-key"), "authentification_api"),
        (erreur(403, "permission_error", "no access"), "authentification_api"),
        (erreur(429, "rate_limit_error", "slow down"), "debit"),
        (erreur(400, "invalid_request_error", "Your credit balance is too low"), "credit_api"),
        (erreur(402, "billing_error", "payment required"), "credit_api"),
        (erreur(529, "overloaded_error", "overloaded"), "surcharge"),
        (erreur(400, "invalid_request_error", "bad field"), "moteur"),
    ]
    for reponse, code in cas:
        serveur.reponses = [reponse]
        evs = derouler(moteur_api, Demande("x", "sonnet"))
        assert evs[-1].type == "erreur" and evs[-1].code == code, code
    assert not list(moteur_api.sessions.dossier.glob("*.json"))  # un tour en échec ne laisse pas de session
    assert (
        derouler(moteur_api, Demande("x", "sonnet", session="api-" + "0" * 36))[-1].code
        == "session_introuvable"
    )
    assert (
        derouler(moteur_api, Demande("x", "sonnet", session="../../etc/passwd"))[-1].code
        == "session_introuvable"
    )


def test_outils_de_lecture_bornes(config, moteur_api):
    outils = OutilsLecture(config.agent, config.recettes)
    assert "Flan.cook" in outils.executer("Glob", {"pattern": "**/*.cook", "path": str(config.recettes)})[0]
    assert "Flan.cook" in outils.executer("Glob", {"pattern": str(config.recettes / "Dessert/*.cook")})[0]
    assert (
        "Flan.cook:4:"
        in outils.executer("Grep", {"pattern": "LAIT", "path": str(config.recettes), "ignore_case": True})[0]
    )
    assert "KitchenAid" in outils.executer("Read", {"file_path": "memoire/materiel.md"})[0]
    assert "recette-cook" in outils.executer("Read", {"file_path": ".claude/skills/recette-cook/SKILL.md"})[0]
    (config.racine / "secret.txt").write_text("MOT-SECRET")
    (config.agent / "pieces" / "lien").symlink_to(config.racine / "secret.txt")
    refuses = [
        {"file_path": str(config.racine / "secret.txt")}, {"file_path": "../secret.txt"}, {"file_path": "pieces/lien"},
        {"file_path": ".git/config"}, {"file_path": ".claude/settings.json"}, {"file_path": str(config.base)},
        {"file_path": "memoire/materiel.md", "commande": "rm"}, {"file_path": 3}, {},
    ]  # fmt: skip
    for entree in refuses:
        contenu, erreur = outils.executer("Read", entree)
        assert erreur is True and "MOT-SECRET" not in contenu, entree
    assert outils.executer("Glob", {"pattern": "/etc/*"})[1] is True
    assert ".git" not in outils.executer("Glob", {"pattern": "**/*"})[0].replace(".gitignore", "")
    assert outils.executer("Write", {"file_path": "x"}) == ("Outil inconnu : Write", True)
    # fichier long : la suite est annoncée, jamais coupée en silence
    (config.agent / "references" / "long.md").write_text("\n".join(f"ligne {i}" for i in range(2500)))
    long, _ = outils.executer("Read", {"file_path": "references/long.md"})
    assert "500 ligne(s) non affichée(s) : relire avec offset=2001" in long
    (config.agent / "pieces" / "photo.png").write_bytes(b"\x89PNG")
    assert (
        outils.executer("Read", {"file_path": "pieces/photo.png"})[0][0]["source"]["media_type"]
        == "image/png"
    )


def test_imports_et_tarifs(tmp_path):
    (tmp_path / "a.md").write_text("contenu A\n@b.md\n")
    (tmp_path / "b.md").write_text("contenu B")
    assert (
        developper_imports("Titre\n@a.md\n@absent.md\n@../dehors.md\nfin", tmp_path)
        == "Titre\ncontenu A\ncontenu B\n\n\nfin"
    )

    class Usage:
        input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens = (
            1_000_000,
            1_000_000,
            1_000_000,
            1_000_000,
        )

    assert cout_estime("claude-opus-5-5", Usage) == pytest.approx(4 + 20 + 5 + 0.20)
    assert cout_estime("claude-haiku-5-5", Usage) == pytest.approx(0.10 + 0.50 + 0.125 + 0.01)


def test_bascule_automatique_sur_le_moteur_de_secours(config, moteur, serveur):
    """Risque n° 1 de la spécification : crédit CLI épuisé → le tour repart sur l'API, historique réinjecté."""
    secours = MoteurAPI(config, serveur.client())
    with Client(creer_application(config, moteur, secours)) as c:
        ctx = c.app.state.ctx
        d = c.discussion()
        c.envoyer(d, "Ma brioche est trop sèche")  # premier tour sur le moteur principal
        avant = c.get("/api/quota").json()
        assert avant["secours"] == "api" and avant["secours_actif"] is False and avant["cout_api"] == 0

        moteur.erreur = "quota"
        serveur.reponses = [
            sse([{"type": "text", "text": "Ajoute 20 g de lait."}]),
            sse([{"type": "text", "text": "Oui."}]),
        ]
        fin = dict(c.envoyer(d, "Et si j'ajoute du lait ?"))["fin"]
        assert fin["message"]["etat"] == "termine" and fin["message"]["moteur"] == "api"
        assert fin["message"]["contenu"] == "Ajoute 20 g de lait."
        envoye = serveur.requetes[0]["messages"][0]["content"]
        assert "<historique>" in envoye and "trop sèche" in envoye and "Et si j'ajoute du lait ?" in envoye
        assert fin["discussion"]["session_claude"].startswith("api-")

        # tant que le crédit est épuisé, les tours suivants vont droit au secours et reprennent sa session
        appels_principal = len(moteur.demandes)
        c.envoyer(d, "Sûr ?")
        assert (
            len(moteur.demandes) == appels_principal
            and "<historique>" not in serveur.requetes[1]["messages"][-1]["content"]
        )
        quota = c.get("/api/quota").json()
        assert (
            quota["atteint"]
            and quota["secours_actif"]
            and quota["cout_api"] > 0
            and quota["cout"] == pytest.approx(0.0123 * 2)
        )

        # passé le délai de réessai, le moteur principal reprend, avec l'historique réinjecté
        ctx.base.definir_meta("quota_atteint", "2020-01-01T00:00:00Z")
        fin = dict(c.envoyer(d, "Merci"))["fin"]
        assert fin["message"]["moteur"] == "factice" and "<historique>" in moteur.demandes[-1].message
        assert c.get("/api/quota").json()["secours_actif"] is False


def test_moteur_api_seul_dans_l_application(config, serveur):
    """AC_MOTEUR=api : même pipeline de propositions qu'avec le CLI."""
    bloc = "```proposition\ncible: recette\ntype: creation\nchemin: Dessert/Riz au lait.cook\n---\n---\ntitle: Riz au lait\n---\nCuire le @riz{100%g}.\n```"
    serveur.reponses = [
        sse([{"type": "text", "text": "Voici.\n\n" + bloc}]),
        sse([{"type": "text", "text": "Riz au lait"}]),
    ]
    with Client(creer_application(config, MoteurAPI(config, serveur.client()))) as c:
        d = c.discussion()
        fin = dict(c.envoyer(d, "Une recette de riz au lait, enregistre"))["fin"]
        proposition = fin["message"]["propositions"][0]
        assert (
            proposition["chemin"] == "Dessert/Riz au lait.cook"
            and fin["discussion"]["titre"] == "Riz au lait"
        )
        assert c.post(f"/api/propositions/{proposition['id']}/valider").status_code == 200
        assert c.get("/api/sante").json()["moteur"] == "api"
        assert "Enregistrer un fichier = émettre un bloc" in serveur.requetes[0]["system"][0]["text"]
