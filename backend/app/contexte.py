"""Assemblage des services de l'application."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .db import Base
from .depots import Depot
from .initialisation import initialiser
from .moteur.base import Engine
from .parametres import Parametres
from .propositions import Propositions
from .references import References
from .synchro import Synchro
from .tours import Gestionnaire


@dataclass
class Contexte:
    config: Config
    base: Base
    moteur: Engine
    recettes: Depot
    agent: Depot
    moteur_secours: Engine | None = None
    parametres: Parametres = None
    references: References = None
    synchro: Synchro = None
    propositions: Propositions = None
    tours: Gestionnaire = None


def creer_moteur(config: Config, nom: str | None = None) -> Engine:
    nom = nom or config.moteur
    if nom == "api":
        from .moteur.api_anthropic import MoteurAPI

        return MoteurAPI(config)
    if nom == "openai":
        from .moteur.openai_compat import MoteurOpenAI

        return MoteurOpenAI(config)
    if nom == "factice":
        from .moteur.factice import MoteurFactice

        return MoteurFactice(delai=0.03)
    from .moteur.claude_cli import MoteurClaudeCLI

    return MoteurClaudeCLI(config)


def creer_contexte(
    config: Config, moteur: Engine | None = None, moteur_secours: Engine | None = None
) -> Contexte:
    recettes, agent = initialiser(config)
    base = Base(config.base)
    ctx = Contexte(
        config=config, base=base, moteur=moteur or creer_moteur(config), recettes=recettes, agent=agent
    )
    if moteur_secours is None and config.moteur_secours and config.moteur_secours != config.moteur:
        moteur_secours = creer_moteur(config, config.moteur_secours)
    ctx.moteur_secours = moteur_secours
    ctx.parametres = Parametres(agent)
    ctx.parametres.initialiser()
    ctx.references = References(base, agent)
    ctx.references.reindexer_fiches()
    ctx.references.publier()
    ctx.synchro = Synchro(config, base, recettes, agent)
    ctx.propositions = Propositions(ctx)
    ctx.tours = Gestionnaire(ctx)
    return ctx
