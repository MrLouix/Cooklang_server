"""Application FastAPI : API, tâches de fond et PWA statique."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Config
from .contexte import creer_contexte
from .moteur.base import Engine
from .routes import discussions, divers, recettes, references

journal = logging.getLogger("aide-culinaire")
PUBLIQUES = {"/api/session", "/api/connexion"}


async def _controle_periodique(ctx) -> None:
    """C-9 : importe régulièrement les modifications faites côté Drive, et vérifie les liens une fois par jour."""
    tours = 0
    while True:
        await asyncio.sleep(ctx.config.intervalle_controle)
        tours += 1
        try:
            if ctx.synchro.drive_actif:
                bilan = await asyncio.to_thread(ctx.synchro.importer_externes)
                if bilan["importes"] or bilan["conflits"]:
                    await asyncio.to_thread(ctx.synchro.apres_commit)
            if tours % max(1, int(86400 / ctx.config.intervalle_controle)) == 0:
                await asyncio.to_thread(ctx.references.verifier_liens)
        except Exception:  # noqa: BLE001
            journal.exception("Contrôle périodique en échec")


def creer_application(config: Config | None = None, moteur: Engine | None = None) -> FastAPI:
    config = config or Config()
    ctx = creer_contexte(config, moteur)

    @contextlib.asynccontextmanager
    async def cycle(app: FastAPI):
        ctx.tours.demarrer()
        tache = asyncio.create_task(_controle_periodique(ctx))
        yield
        tache.cancel()
        await ctx.tours.arreter()

    app = FastAPI(
        title="Aide Culinaire", lifespan=cycle, docs_url="/api/docs", openapi_url="/api/openapi.json"
    )
    app.state.ctx = ctx

    @app.middleware("http")
    async def garde(request: Request, suite):
        chemin = request.url.path
        if chemin.startswith("/api/") and chemin not in PUBLIQUES and not divers.est_connecte(request, ctx):
            return JSONResponse({"detail": "Connexion requise."}, status_code=401)
        reponse = await suite(request)
        if chemin in ("/", "/index.html", "/sw.js"):
            reponse.headers["Cache-Control"] = "no-cache"
        return reponse

    for module in (discussions, recettes, references, divers):
        app.include_router(module.routeur)
    if config.front.is_dir():
        app.mount("/", StaticFiles(directory=config.front, html=True), name="pwa")
    return app
