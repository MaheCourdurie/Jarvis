from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class HistoryMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    history: list[HistoryMessage] = Field(default_factory=list)
    temperature: float = 0.6
    # Action proposée au tour précédent et en attente d'un « oui » ou d'un « non ».
    pending: Optional[dict] = None
    # Origine de la demande : "hud"/"web" (poste local) ou "discord" (distant).
    client: str = "web"


class ChatResponse(BaseModel):
    reply: str
    speech: Optional[str] = None
    action: Optional[str] = None
    source: str = "api"
    pending: Optional[dict] = None
    data: Optional[dict] = None
