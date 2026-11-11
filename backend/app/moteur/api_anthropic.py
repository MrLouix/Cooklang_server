"""Moteur de secours par clé API Anthropic (M-1) : même interface que le moteur CLI.

Différences avec le CLI, assumées :
- le serveur exécute lui-même les outils de lecture (outils_lecture.py) ; la recherche et la
  lecture web sont des outils hébergés par Anthropic ;
- pas d'outil Skill : les skills de `.claude/skills/` sont listés dans le prompt système et lus avec Read ;
- les sessions sont des fichiers JSON dans `data/sessions_api/`, en ajout seul : le prompt système
  est figé à la création de la session, et une consigne qui change ensuite (paramètres, mémoire)
  est ajoutée comme message système en cours de conversation. C'est ce qui garde valides le cache
  de prompt et les blocs de réflexion rejoués.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import anthropic

from ..config import Config
from .base import Demande, Evenement
from .outils_lecture import DEFINITIONS, OutilsLecture

PREFIXE_SESSION = "api-"
MODELES_API = {"sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5", "haiku": "claude-haiku-5-5"}
# Repli côté serveur sur refus d'un classifieur de sécurité : sans objet sur Haiku 5.5.
AVEC_REPLI = {"claude-sonnet-5-5", "claude-opus-5-5"}
BETA_REPLI = "server-side-fallback-2026-07-01"
# $ par million de jetons (entrée, sortie, lecture de cache). Écriture de cache 5 min : 1,25 × l'entrée.
TARIFS = {
    "claude-sonnet-5-5": (2.00, 10.00, 0.10),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}
OUTILS_WEB = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 8},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 8},
]
NOMS_AFFICHES = {"web_search": "WebSearch", "web_fetch": "WebFetch"}
MAX_ITERATIONS = 30
IMPORT = re.compile(r"(?m)^@(\S+)\s*$")


def cout_estime(modele: str, usage) -> float:
    """Coût d'une requête d'après `usage`. Hors frais de recherche web, facturés à la requête."""
    entree, sortie, lecture = TARIFS.get(modele, TARIFS["claude-opus-5-5"])
    jetons = lambda nom: getattr(usage, nom, 0) or 0  # noqa: E731
    total = (
        jetons("input_tokens") * entree
        + jetons("cache_creation_input_tokens") * entree * 1.25
        + jetons("cache_read_input_tokens") * lecture
        + jetons("output_tokens") * sortie
    )
    return total / 1_000_000


def developper_imports(texte: str, racine: Path, profondeur: int = 0) -> str:
    """Remplace les lignes `@chemin` de CLAUDE.md par le contenu du fichier, comme le fait le CLI."""

    def remplacer(trouve: re.Match) -> str:
        cible = (racine / trouve.group(1)).resolve()
        if profondeur >= 3 or not cible.is_file() or not cible.is_relative_to(racine.resolve()):
            return ""
        return developper_imports(cible.read_text(encoding="utf-8"), racine, profondeur + 1).strip()

    return IMPORT.sub(remplacer, texte)


def lister_skills(agent: Path) -> str:
    lignes = []
    for fichier in sorted((agent / ".claude" / "skills").glob("*/SKILL.md")):
        entete = fichier.read_text(encoding="utf-8").split("---", 2)
        champs = dict(
            re.findall(r'(?m)^(name|description):\s*"?(.*?)"?\s*$', entete[1] if len(entete) > 2 else "")
        )
        nom = champs.get("name", fichier.parent.name)
        lignes.append(
            f"- **{nom}** — {champs.get('description', '')} Fichier : `.claude/skills/{fichier.parent.name}/SKILL.md`"
        )
    if not lignes:
        return ""
    return (
        "# Skills disponibles\n\nQuand une demande correspond à un skill, lis son fichier en entier avec Read, "
        "puis suis-le. Il n'y a pas d'outil Skill ici.\n\n" + "\n".join(lignes)
    )


class MoteurAPI:
    nom = "api"

    def __init__(self, config: Config, client: anthropic.AsyncAnthropic | None = None):
        self.config = config
        self._client = client
        self.outils = OutilsLecture(config.agent, config.recettes)
        self.sessions = config.data / "sessions_api"

    @staticmethod
    def reconnait(session: str | None) -> bool:
        return bool(session) and session.startswith(PREFIXE_SESSION)

    @property
    def client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            cle = Path(self.config.cle_api_fichier)
            # Sans fichier de clé, le SDK résout lui-même ANTHROPIC_API_KEY ou un profil `ant auth login`.
            self._client = (
                anthropic.AsyncAnthropic(api_key=cle.read_text().strip())
                if cle.is_file()
                else anthropic.AsyncAnthropic()
            )
        return self._client

    # --- sessions ---------------------------------------------------------
    def _fichier(self, session: str) -> Path:
        if not re.fullmatch(rf"{PREFIXE_SESSION}[0-9a-f-]{{36}}", session):
            raise FileNotFoundError(session)
        return self.sessions / f"{session}.json"

    def _charger(self, session: str) -> dict:
        return json.loads(self._fichier(session).read_text(encoding="utf-8"))

    def _enregistrer(self, session: str, etat: dict) -> None:
        self.sessions.mkdir(parents=True, exist_ok=True)
        provisoire = self._fichier(session).with_suffix(".tmp")
        provisoire.write_text(json.dumps(etat, ensure_ascii=False), encoding="utf-8")
        provisoire.replace(self._fichier(session))

    # --- prompt système ---------------------------------------------------
    def systeme(self, consignes: str) -> str:
        agent = self.config.agent
        claude_md = agent / "CLAUDE.md"
        parties = [
            developper_imports(claude_md.read_text(encoding="utf-8"), agent) if claude_md.is_file() else ""
        ]
        parties += [lister_skills(agent), f"Répertoire de travail : `{agent}`.", consignes]
        return "\n\n".join(p.strip() for p in parties if p.strip())

    # --- exécution --------------------------------------------------------
    def _parametres(self, modele: str, etat: dict, ephemere: bool) -> dict:
        parametres = {
            "model": modele,
            "max_tokens": 1024 if ephemere else 64000,
            "thinking": {"type": "adaptive"},
            "messages": etat["messages"],
            "betas": [],
        }
        if self.config.api_effort and not ephemere:
            parametres["output_config"] = {"effort": self.config.api_effort}
        if etat["systeme"]:
            # Préfixe stable (outils puis système) mis en cache ; le marqueur de niveau requête couvre l'historique.
            parametres["system"] = [
                {"type": "text", "text": etat["systeme"], "cache_control": {"type": "ephemeral"}}
            ]
        if not ephemere:
            parametres["tools"] = DEFINITIONS + OUTILS_WEB
            parametres["cache_control"] = {"type": "ephemeral"}
        if modele in AVEC_REPLI:
            parametres["betas"].append(BETA_REPLI)
            parametres["fallbacks"] = "default"
        return parametres

    async def run(self, demande: Demande) -> AsyncIterator[Evenement]:
        modele = MODELES_API.get(demande.modele, demande.modele)
        systeme = "" if demande.ephemere else self.systeme(demande.consignes)
        if demande.session:
            try:
                etat = self._charger(demande.session)
            except (OSError, json.JSONDecodeError):
                yield Evenement(
                    "erreur", code="session_introuvable", texte="No conversation found with session ID"
                )
                return
            session = demande.session
        else:
            session = f"{PREFIXE_SESSION}{uuid.uuid4()}"
            etat = {"systeme": systeme, "consignes": systeme, "messages": []}
        etat["messages"].append({"role": "user", "content": demande.message})
        if systeme != etat.get("consignes"):
            # Paramètres ou mémoire modifiés depuis le début de la session : on ajoute, on ne réécrit pas.
            etat["messages"].append(
                {
                    "role": "system",
                    "content": "Les consignes ont été mises à jour. Elles remplacent les précédentes :\n\n"
                    + systeme,
                }
            )
            etat["consignes"] = systeme
        if not demande.ephemere:
            yield Evenement("session", session=session)

        cout, texte = 0.0, ""
        try:
            for _ in range(MAX_ITERATIONS):
                async with self.client.beta.messages.stream(
                    **self._parametres(modele, etat, demande.ephemere)
                ) as flux:
                    async for ev in flux:
                        if ev.type == "content_block_start" and ev.content_block.type == "text":
                            if texte and not texte.endswith("\n"):
                                texte += "\n\n"
                                yield Evenement("texte", texte="\n\n")
                        elif ev.type == "text":
                            texte += ev.text
                            yield Evenement("texte", texte=ev.text)
                        elif ev.type == "content_block_stop" and ev.content_block.type == "server_tool_use":
                            bloc = ev.content_block
                            entree = bloc.input if isinstance(bloc.input, dict) else {}
                            yield Evenement(
                                "outil",
                                nom=NOMS_AFFICHES.get(bloc.name, bloc.name),
                                detail=str(entree.get("query") or entree.get("url") or "")[:300],
                            )
                    reponse = await flux.get_final_message()
                cout += cout_estime(modele, reponse.usage)
                # Le contenu est rejoué tel quel aux tours suivants : blocs de réflexion, d'outils et de repli compris.
                etat["messages"].append(
                    {"role": "assistant", "content": [bloc.to_dict() for bloc in reponse.content]}
                )

                if reponse.stop_reason == "refusal":
                    categorie = getattr(reponse.stop_details, "category", None) or "non précisée"
                    yield Evenement("erreur", code="refus", texte=f"catégorie : {categorie}", cout=cout)
                    return
                if reponse.stop_reason == "pause_turn":
                    continue  # outil hébergé interrompu : renvoyer tel quel, le serveur reprend
                appels = [bloc for bloc in reponse.content if bloc.type == "tool_use"]
                if reponse.stop_reason == "max_tokens":
                    if appels:  # entrée d'outil tronquée : ne rien exécuter
                        yield Evenement(
                            "erreur",
                            code="moteur",
                            texte="Réponse tronquée en plein appel d'outil.",
                            cout=cout,
                        )
                        return
                    avis = "\n\n*[Réponse interrompue : longueur maximale atteinte. Demande la suite.]*"
                    yield Evenement("texte", texte=avis)
                    break
                if not appels:
                    break
                resultats = []
                for appel in appels:
                    yield Evenement("outil", nom=appel.name, detail=self._detail(appel.input))
                    contenu, erreur = self.outils.executer(appel.name, appel.input)
                    resultats.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": appel.id,
                            "content": contenu,
                            "is_error": erreur,
                        }
                    )
                # Tous les résultats dans un seul message utilisateur.
                etat["messages"].append({"role": "user", "content": resultats})
            else:
                yield Evenement(
                    "erreur", code="moteur", texte="Trop d'appels d'outils dans un même tour.", cout=cout
                )
                return
        except anthropic.AuthenticationError as erreur:
            yield Evenement("erreur", code="authentification_api", texte=erreur.message, cout=cout)
            return
        except anthropic.PermissionDeniedError as erreur:
            yield Evenement("erreur", code="authentification_api", texte=erreur.message, cout=cout)
            return
        except anthropic.RateLimitError as erreur:
            yield Evenement("erreur", code="debit", texte=erreur.message, cout=cout)
            return
        except anthropic.APIStatusError as erreur:
            if erreur.type == "billing_error" or "credit balance" in erreur.message.lower():
                code = "credit_api"
            elif erreur.status_code >= 500:
                code = "surcharge"
            else:
                code = "moteur"
            yield Evenement(
                "erreur", code=code, texte=f"HTTP {erreur.status_code} : {erreur.message}", cout=cout
            )
            return
        except anthropic.APIConnectionError as erreur:
            yield Evenement("erreur", code="reseau", texte=str(erreur), cout=cout)
            return
        except anthropic.AnthropicError as erreur:  # identifiants introuvables, entre autres
            yield Evenement("erreur", code="authentification_api", texte=str(erreur), cout=cout)
            return

        if not demande.ephemere:
            self._enregistrer(session, etat)
        yield Evenement("fin", session=None if demande.ephemere else session, cout=cout)

    @staticmethod
    def _detail(entree: object) -> str:
        if not isinstance(entree, dict):
            return ""
        return str(entree.get("file_path") or entree.get("pattern") or "")[:300]

    async def version(self) -> str:
        return f"SDK anthropic {anthropic.__version__}"
