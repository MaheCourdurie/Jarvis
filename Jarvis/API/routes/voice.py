"""La voix de Jarvis (synthèse) et son oreille (transcription du micro)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field

from services import voice

MAX_STT_BYTES = 4 * 1024 * 1024


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def router() -> APIRouter:
    routes = APIRouter(prefix="/api")

    @routes.post("/tts")
    def api_tts(request: SpeakRequest) -> Response:
        """Synthétise la voix de Jarvis (audio WAV)."""
        try:
            audio = voice.synthesize(request.text)
        except voice.VoiceError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return Response(content=audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    @routes.post("/stt")
    async def api_stt(request: Request) -> dict:
        """Transcrit un enregistrement du micro (WAV PCM 16 bits) et repère le mot d'activation."""
        data = await request.body()
        if not data:
            raise HTTPException(status_code=400, detail="audio manquant")
        if len(data) > MAX_STT_BYTES:
            raise HTTPException(status_code=413, detail="enregistrement trop long")
        try:
            return await run_in_threadpool(voice.transcribe, data)
        except voice.VoiceError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return routes
