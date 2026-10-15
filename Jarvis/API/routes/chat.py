"""Parler à Jarvis : une réponse d'un bloc, ou phrase par phrase pour le HUD."""

from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from core.jarvis import Jarvis
from core.messages import ChatRequest, ChatResponse


def router(jarvis: Jarvis) -> APIRouter:
    routes = APIRouter(prefix="/api")

    @routes.post("/chat", response_model=ChatResponse)
    def api_chat(request: ChatRequest) -> ChatResponse:
        """Point d'entrée principal: exécute une action ou converse via le modèle."""
        return ChatResponse(**jarvis.answer(request))

    @routes.post("/chat/stream")
    def api_chat_stream(request: ChatRequest) -> StreamingResponse:
        """Variante en flux (NDJSON) : le HUD parle sans attendre la fin de la réponse."""
        lines = (json.dumps(event, ensure_ascii=False) + "\n" for event in jarvis.stream(request))
        return StreamingResponse(
            lines,
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return routes
