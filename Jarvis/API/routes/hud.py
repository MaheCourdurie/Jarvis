"""Ce que le HUD affiche : état des systèmes, tableau de bord, briefing, alarmes, événements."""

from __future__ import annotations

import mimetypes
import threading
from typing import Optional

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles

from agents.briefing import build_briefing
from agents.system import read_system_metrics, system_alerts
from config import CITY, INTERFACE_DIR, OLLAMA_MODEL, STRICT_ACTIONS_ONLY, WAKE_WORD, WEB_SEARCH_ENABLED
from core.intents import COMMAND_HELP
from core.jarvis import VERSION, Jarvis
from persona import TITLE
from services import events, llm, voice


def router(jarvis: Jarvis) -> APIRouter:
    context = jarvis.context
    routes = APIRouter(prefix="/api")

    @routes.get("/status")
    def api_status() -> dict:
        """Retourne l'état de santé de l'API, du modèle, de la voix, du provider mail, des contrôleurs et de leurs agents."""
        model_online, model_reason = llm.ollama_status()
        return {
            "ok": True,
            "version": VERSION,
            "persona": {"title": TITLE, "city": CITY, "wake_word": WAKE_WORD},
            "model_online": model_online,
            "model_reason": model_reason,
            "model_name": OLLAMA_MODEL,
            "strict": STRICT_ACTIONS_ONLY,
            "web_search": WEB_SEARCH_ENABLED,
            "mail": context.google.status(),
            "voice": {"tts": voice.tts_status(), "stt": voice.stt_status()},
            "controllers": {
                controller.name: {agent.name: sorted(agent.actions) for agent in controller.agents}
                for controller in jarvis.controllers
            },
        }

    @routes.get("/commands")
    def api_commands() -> dict:
        """Expose la liste des commandes supportées par l'API."""
        return {"commands_help": COMMAND_HELP}

    @routes.post("/warmup")
    def api_warmup() -> dict:
        """Garde le modèle en mémoire tant que le HUD est ouvert (appelé toutes les 10 minutes)."""
        threading.Thread(target=llm.keep_warm, daemon=True, name="jarvis-keep-warm").start()
        return {"ok": True}

    @routes.get("/system")
    def api_system() -> dict:
        """Relevé en direct du poste (processeur, mémoire, disque, batterie) pour le HUD."""
        metrics = read_system_metrics()
        metrics["alerts"] = system_alerts(metrics)
        return metrics

    @routes.get("/dashboard")
    def api_dashboard() -> dict:
        """État du jour affiché par le HUD : météo, agenda, messagerie, alarmes."""
        return context.dashboard.snapshot()

    @routes.get("/briefing")
    def api_briefing(kind: str = "boot") -> dict:
        """Briefing prononcé par Jarvis (kind=boot au démarrage du HUD, kind=full sur demande)."""
        reply = build_briefing(context.dashboard, kind="full" if kind == "full" else "boot")
        return {"reply": reply.text, "speech": reply.spoken}

    @routes.get("/events")
    def api_events(after: Optional[int] = None) -> dict:
        """Événements proactifs (alarmes) publiés depuis le dernier relevé du HUD."""
        if after is None:
            events.events_after(events.last_id())
            return {"events": [], "last_id": events.last_id()}
        return {"events": events.events_after(after), "last_id": events.last_id()}

    @routes.get("/alarms")
    def api_alarms() -> dict:
        """Retourne la liste des alarmes encore actives."""
        return {"ok": True, "items": context.alarms.list_alarms()}

    return routes


class HudFiles(StaticFiles):
    """Fichiers du HUD, toujours revalidés : une mise à jour est visible au premier rechargement."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def mount_interface(app: FastAPI) -> None:
    """Le HUD est servi par l'API elle-même : une seule adresse à ouvrir (http://localhost:8001/).

    Il s'installe aussi comme une app (manifeste, icônes, service worker sw.js).
    À monter en dernier : il répond à toutes les adresses que l'API ne connaît pas.
    """
    mimetypes.add_type("application/manifest+json", ".webmanifest")
    if INTERFACE_DIR.is_dir():
        app.mount("/", HudFiles(directory=str(INTERFACE_DIR), html=True), name="hud")
