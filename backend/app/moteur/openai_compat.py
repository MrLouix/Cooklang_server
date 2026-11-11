"""Moteur pour tout fournisseur compatible avec l'API OpenAI (chat completions) : OpenRouter,
OpenAI, Mistral, Groq, Together, un serveur local (Ollama, LM Studio, vLLM)…

Seul le standard est utilisé : messages, outils de type `function`, streaming avec
`stream_options.include_usage`. Ce qui varie d'un fournisseur à l'autre se règle par configuration :
URL de base, modèles, tarifs, et champs supplémentaires du corps de requête (AC_OPENAI_CORPS_EXTRA).

Comme pour le moteur Anthropic, le modèle n'a que des outils de lecture, exécutés par le serveur.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import openai

from ..config import Config
from .base import Demande, Evenement
from .commun import Sessions, composer_systeme
from .outils_lecture import DEFINITIONS, OutilsLecture
from .outils_web import DEFINITION as DEFINITION_WEB
from .outils_web import LectureWeb

PREFIXE_SESSION = "oai-"
MAX_ITERATIONS = 30


def en_fonction(definition: dict) -> dict:
    """Définition d'outil au format OpenAI."""
    return {
        "type": "function",
        "function": {
            "name": definition["name"],
            "description": definition["description"],
            "parameters": definition["input_schema"],
        },
    }


def lire_modeles(texte: str) -> dict[str, str]:
    """`alias=identifiant, identifiant2` → {nom affiché: identifiant chez le fournisseur}, dans l'ordre."""
    modeles: dict[str, str] = {}
    for entree in filter(None, (e.strip() for e in texte.split(","))):
        alias, _, identifiant = entree.partition("=")
        modeles[alias.strip()] = (identifiant or alias).strip()
    return modeles


def lire_tarifs(texte: str) -> dict[str, tuple[float, float]]:
    """`identifiant=entrée/sortie` en $ par million de jetons."""
    tarifs = {}
    for entree in filter(None, (e.strip() for e in texte.split(","))):
        identifiant, _, prix = entree.rpartition("=")
        try:
            entree_prix, _, sortie_prix = prix.partition("/")
            tarifs[identifiant.strip()] = (float(entree_prix), float(sortie_prix or entree_prix))
        except ValueError:
            continue
    return tarifs


class MoteurOpenAI:
    nom = "openai"

    def __init__(
        self, config: Config, client: openai.AsyncOpenAI | None = None, web: LectureWeb | None = None
    ):
        self.config = config
        self._client = client
        self.outils = OutilsLecture(config.agent, config.recettes)
        self.web = web or LectureWeb()
        self.sessions = Sessions(config.data / "sessions_openai", PREFIXE_SESSION)
        self.catalogue = lire_modeles(config.openai_modeles)
        self.tarifs = lire_tarifs(config.openai_tarifs)
        try:
            self.corps_extra = (
                json.loads(config.openai_corps_extra) if config.openai_corps_extra.strip() else {}
            )
        except json.JSONDecodeError:
            self.corps_extra = {}

    def reconnait(self, session: str | None) -> bool:
        return self.sessions.reconnait(session)

    def modeles(self) -> list[str]:
        return list(self.catalogue)

    def resoudre_modele(self, demande: str) -> str | None:
        """Nom affiché ou identifiant connu ; sinon le premier modèle configuré (alias du CLI, par exemple)."""
        if demande in self.catalogue:
            return self.catalogue[demande]
        if demande in self.catalogue.values():
            return demande
        return next(iter(self.catalogue.values()), None)

    @property
    def client(self) -> openai.AsyncOpenAI:
        if self._client is None:
            fichier = Path(self.config.openai_cle_fichier)
            # Sans fichier de clé, le SDK lit la variable d'environnement OPENAI_API_KEY.
            cle = fichier.read_text().strip() if fichier.is_file() else None
            self._client = openai.AsyncOpenAI(api_key=cle, base_url=self.config.openai_url)
        return self._client

    def cout(self, modele: str, usage) -> float:
        """Coût annoncé par le fournisseur (OpenRouter renseigne `usage.cost`), sinon d'après les tarifs configurés."""
        if usage is None:
            return 0.0
        annonce = getattr(usage, "cost", None)
        if isinstance(annonce, int | float):
            return float(annonce)
        if modele in self.tarifs:
            entree, sortie = self.tarifs[modele]
            return ((usage.prompt_tokens or 0) * entree + (usage.completion_tokens or 0) * sortie) / 1_000_000
        return 0.0

    async def _appeler_outil(self, nom: str, arguments: str) -> tuple[str, bool, dict | None]:
        """Renvoie (texte du résultat, est une erreur, image éventuelle à joindre)."""
        try:
            entree = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return "Arguments illisibles : un objet JSON valide est attendu.", True, None
        if nom == "WebFetch":
            return (*await self.web.executer(entree), None)
        contenu, erreur = self.outils.executer(nom, entree)
        if isinstance(
            contenu, list
        ):  # image : les messages `tool` sont textuels, elle part dans un message utilisateur
            if not self.config.openai_vision:
                return "Ce modèle ne lit pas les images.", True, None
            source = contenu[0]["source"]
            image = {
                "type": "image_url",
                "image_url": {"url": f"data:{source['media_type']};base64,{source['data']}"},
            }
            return "Image jointe dans le message suivant.", False, image
        return contenu, erreur, None

    async def run(self, demande: Demande) -> AsyncIterator[Evenement]:
        modele = self.resoudre_modele(demande.modele)
        if modele is None:
            yield Evenement(
                "erreur", code="moteur", texte="Aucun modèle configuré : renseigner AC_OPENAI_MODELES."
            )
            return
        if demande.session:
            try:
                etat = self.sessions.charger(demande.session)
            except (OSError, json.JSONDecodeError):
                yield Evenement(
                    "erreur", code="session_introuvable", texte="No conversation found with session ID"
                )
                return
            session = demande.session
        else:
            session, etat = self.sessions.nouvelle(), {"messages": []}
        etat["messages"].append({"role": "user", "content": demande.message})
        if not demande.ephemere:
            yield Evenement("session", session=session)

        # Le prompt système est reconstruit à chaque tour : un réglage modifié s'applique au tour suivant (PA-2).
        entete = (
            []
            if demande.ephemere
            else [{"role": "system", "content": composer_systeme(self.config, demande.consignes)}]
        )
        parametres: dict = {"model": modele, "stream": True, "stream_options": {"include_usage": True}}
        if not demande.ephemere:
            parametres["tools"] = [en_fonction(d) for d in [*DEFINITIONS, DEFINITION_WEB]]
        if self.config.openai_max_tokens:
            parametres["max_tokens"] = self.config.openai_max_tokens
        if self.corps_extra:
            parametres["extra_body"] = self.corps_extra

        cout, texte = 0.0, ""
        try:
            for _ in range(MAX_ITERATIONS):
                morceaux, appels, arret, usage = "", {}, None, None
                flux = await self.client.chat.completions.create(
                    messages=entete + etat["messages"], **parametres
                )
                async for bloc in flux:
                    usage = getattr(bloc, "usage", None) or usage
                    if not bloc.choices:
                        continue
                    choix = bloc.choices[0]
                    arret = choix.finish_reason or arret
                    delta = choix.delta
                    if delta is None:
                        continue
                    if delta.content:
                        if not morceaux and texte and not texte.endswith("\n"):
                            texte += "\n\n"
                            yield Evenement("texte", texte="\n\n")
                        morceaux += delta.content
                        texte += delta.content
                        yield Evenement("texte", texte=delta.content)
                    for fragment in delta.tool_calls or []:
                        appel = appels.setdefault(fragment.index, {"id": "", "nom": "", "arguments": ""})
                        appel["id"] = fragment.id or appel["id"]
                        if fragment.function:
                            appel["nom"] += fragment.function.name or ""
                            appel["arguments"] += fragment.function.arguments or ""
                cout += self.cout(modele, usage)

                if arret == "content_filter":
                    yield Evenement(
                        "erreur", code="refus", texte="filtre de contenu du fournisseur", cout=cout
                    )
                    return
                if arret == "length":
                    if appels:  # arguments d'outil tronqués : ne rien exécuter
                        yield Evenement(
                            "erreur",
                            code="moteur",
                            texte="Réponse tronquée en plein appel d'outil.",
                            cout=cout,
                        )
                        return
                    etat["messages"].append({"role": "assistant", "content": morceaux})
                    yield Evenement(
                        "texte",
                        texte="\n\n*[Réponse interrompue : longueur maximale atteinte. Demande la suite.]*",
                    )
                    break
                if not appels:
                    if not morceaux and not texte:
                        yield Evenement(
                            "erreur",
                            code="moteur",
                            texte="Le fournisseur a renvoyé une réponse vide.",
                            cout=cout,
                        )
                        return
                    etat["messages"].append({"role": "assistant", "content": morceaux})
                    break

                ordonnes = [appels[i] for i in sorted(appels)]
                etat["messages"].append({
                    "role": "assistant",
                    "content": morceaux or None,
                    "tool_calls": [
                        {"id": a["id"], "type": "function", "function": {"name": a["nom"], "arguments": a["arguments"] or "{}"}}
                        for a in ordonnes
                    ],
                })  # fmt: skip
                images = []
                for appel in ordonnes:
                    resultat, _erreur, image = await self._appeler_outil(appel["nom"], appel["arguments"])
                    yield Evenement("outil", nom=appel["nom"], detail=self._detail(appel["arguments"]))
                    etat["messages"].append(
                        {"role": "tool", "tool_call_id": appel["id"], "content": resultat}
                    )
                    if image:
                        images.append(image)
                if images:
                    etat["messages"].append(
                        {"role": "user", "content": [{"type": "text", "text": "Image(s) lue(s) :"}, *images]}
                    )
            else:
                yield Evenement(
                    "erreur", code="moteur", texte="Trop d'appels d'outils dans un même tour.", cout=cout
                )
                return
        except (openai.AuthenticationError, openai.PermissionDeniedError) as erreur:
            yield Evenement("erreur", code="authentification_api", texte=erreur.message, cout=cout)
            return
        except openai.RateLimitError as erreur:
            # Certains fournisseurs signalent aussi par un 429 un quota ou un solde épuisé.
            epuise = any(mot in erreur.message.lower() for mot in ("quota", "credit", "billing", "balance"))
            yield Evenement(
                "erreur", code="credit_api" if epuise else "debit", texte=erreur.message, cout=cout
            )
            return
        except openai.APIStatusError as erreur:
            if erreur.status_code == 402:
                code = "credit_api"
            elif erreur.status_code >= 500:
                code = "surcharge"
            else:
                code = "moteur"
            yield Evenement(
                "erreur", code=code, texte=f"HTTP {erreur.status_code} : {erreur.message}", cout=cout
            )
            return
        except openai.APIConnectionError as erreur:
            yield Evenement("erreur", code="reseau", texte=str(erreur), cout=cout)
            return
        except openai.APIError as erreur:  # erreur transmise au milieu du flux, notamment
            yield Evenement("erreur", code="moteur", texte=str(erreur), cout=cout)
            return
        except openai.OpenAIError as erreur:  # clé absente, entre autres
            yield Evenement("erreur", code="authentification_api", texte=str(erreur), cout=cout)
            return

        if not demande.ephemere:
            self.sessions.enregistrer(session, etat)
        yield Evenement("fin", session=None if demande.ephemere else session, cout=cout)

    @staticmethod
    def _detail(arguments: str) -> str:
        try:
            entree = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return ""
        if not isinstance(entree, dict):
            return ""
        return str(entree.get("file_path") or entree.get("pattern") or entree.get("url") or "")[:300]

    async def version(self) -> str:
        return f"{self.config.openai_url} (SDK openai {openai.__version__})"
