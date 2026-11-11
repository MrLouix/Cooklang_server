from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from ..contexte import Contexte
from ..depots import CheminInvalide


def contexte(request: Request) -> Contexte:
    return request.app.state.ctx


def sse(flux: AsyncIterator[tuple[str, dict]]) -> StreamingResponse:
    async def generer():
        async for genre, donnees in flux:
            yield f"event: {genre}\ndata: {json.dumps(donnees, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generer(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def chemin_sur(depot, chemin: str) -> str:
    try:
        depot.resoudre(chemin)
    except CheminInvalide as erreur:
        raise HTTPException(400, str(erreur)) from erreur
    return chemin
