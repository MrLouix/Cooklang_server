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
    parametres: Parametres = None
    references: References = None
    synchro: Synchro = None
    propositions: Propositions = None
    tours: Gestionnaire = None


def creer_moteur(config: Config) -> Engine:
    if config.moteur == "factice":
        from .moteur.factice import MoteurFactice

        return MoteurFactice(delai=0.03)
    from .moteur.claude_cli import MoteurClaudeCLI

    return MoteurClaudeCLI(config)


def creer_contexte(config: Config, moteur: Engine | None = None) -> Contexte:
    recettes, agent = initialiser(config)
    base = Base(config.base)
    ctx = Contexte(
        config=config, base=base, moteur=moteur or creer_moteur(config), recettes=recettes, agent=agent
    )
    ctx.parametres = Parametres(agent)
    ctx.parametres.initialiser()
    ctx.references = References(base, agent)
    ctx.references.reindexer_fiches()
    ctx.references.publier()
    ctx.synchro = Synchro(config, base, recettes, agent)
    ctx.propositions = Propositions(ctx)
    ctx.tours = Gestionnaire(ctx)
    return ctx
