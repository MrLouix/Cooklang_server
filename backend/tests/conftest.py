import json
import time

import pytest
from fastapi.testclient import TestClient

from app.config import Config
from app.main import creer_application
from app.moteur.factice import MoteurFactice


def lire_sse(reponse) -> list[tuple[str, dict]]:
    evenements, genre = [], None
    for ligne in reponse.iter_lines():
        if ligne.startswith("event: "):
            genre = ligne[7:]
        elif ligne.startswith("data: "):
            evenements.append((genre, json.loads(ligne[6:])))
    return evenements


class Client(TestClient):
    def envoyer(self, discussion: str, texte: str, pieces=None) -> list[tuple[str, dict]]:
        with self.stream(
            "POST", f"/api/discussions/{discussion}/messages", json={"texte": texte, "pieces": pieces or []}
        ) as r:
            assert r.status_code == 200, r.read()
            return lire_sse(r)

    def discussion(self, **corps) -> str:
        return self.post("/api/discussions", json=corps).json()["id"]

    def proposer(self, texte: str = "Analyse ma brioche") -> tuple[str, dict]:
        """Crée une discussion, envoie un message et renvoie la proposition produite."""
        d = self.discussion()
        fin = dict(self.envoyer(d, texte))["fin"]
        return d, fin["message"]["propositions"][0]

    def attendre(self, condition, delai: float = 5.0):
        limite = time.monotonic() + delai
        while time.monotonic() < limite:
            valeur = condition()
            if valeur:
                return valeur
            time.sleep(0.05)
        raise AssertionError("condition non remplie")


@pytest.fixture
def config(tmp_path):
    return Config(
        racine=tmp_path / "srv",
        moteur="factice",
        front=tmp_path / "absent",
        jeton_fichier=str(tmp_path / "jeton"),
    )


@pytest.fixture
def moteur():
    return MoteurFactice()


@pytest.fixture
def client(config, moteur):
    app = creer_application(config, moteur)
    with Client(app) as c:
        c.ctx = app.state.ctx
        c.moteur = moteur
        yield c
