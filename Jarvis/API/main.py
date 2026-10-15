"""Point d'entrée : assemble les services, les agents, Jarvis et les contrôleurs HTTP.

    routes/       reçoivent les requêtes HTTP (HUD, téléphone, Discord) et les passent à Jarvis
    core/         Jarvis, le chef d'orchestre : comprend la demande, choisit le contrôleur, applique les règles
    controllers/  les chefs d'équipe : organisation, ordinateur, savoir, création, routines, maison
    agents/       les spécialistes, chacun sa tâche (messagerie, agenda, musique, web, code, design…)
    services/     les outils techniques des agents (Google, Ollama, voix, météo, web, stockage)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime

import config  # noqa: F401  (premier import local : charge le .env avant les autres modules)
from fastapi import FastAPI

from agents.briefing import Dashboard
from agents.system import keep_awake
from config import HOST, IDLE_MINUTES, KEEP_AWAKE, PORT, env_flag
from controllers.creation import CreationController
from controllers.maison import MaisonController
from controllers.ordinateur import OrdinateurController
from controllers.organisation import OrganisationController
from controllers.routines import RoutinesController
from controllers.savoir import SavoirController
from routes import chat, creations, google, hud, security, voice as voice_routes
from core.agent import Context
from core.jarvis import VERSION, Jarvis
from services import llm, voice
from services.alarm_store import AlarmStore
from services.google_client import GoogleClient
from services.on_demand import Activity, ActivityTracker, launchd_sockets, watch_idle


# ── Services partagés ─────────────────────────────────────────────────────
google_client = GoogleClient.from_env()
alarms = AlarmStore.from_env(google_client.timezone_name)
context = Context(google=google_client, alarms=alarms, dashboard=Dashboard(google_client, alarms))

# ── Jarvis, ses contrôleurs, et leurs agents ──────────────────────────────
savoir = SavoirController(context)
routines = RoutinesController(context)
creation = CreationController(context)
jarvis = Jarvis(
    context,
    controllers=[
        OrganisationController(context),
        OrdinateurController(context),
        savoir,
        creation,
        routines,
        MaisonController(context),
    ],
    conversation=savoir.conversation,
)
# Une routine exécute ses étapes comme si on les disait à Jarvis.
routines.routines.dispatch = jarvis.run_phrase

# Démarrage à la demande (voir services/on_demand.py) : le serveur, et ce qui l'occupe.
activity = Activity()
_server = None
_on_demand = False


def _keeps_awake() -> bool:
    """Une alarme en attente ou un rendez-vous proche à annoncer : Jarvis reste allumé."""
    watcher = getattr(jarvis.routes.get("add_event"), "watcher", None)
    soon = watcher is not None and watcher.soon(datetime.now(context.timezone))
    return bool(context.alarms.list_alarms()) or soon


def _go_to_sleep() -> None:
    print(f"[JARVIS] Aucune demande depuis {IDLE_MINUTES} min : arrêt. macOS me relancera à la prochaine demande.", flush=True)
    if _server is not None:
        _server.should_exit = True


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Démarre les tâches de fond à l'initialisation et nettoie à l'arrêt de l'API."""
    jarvis.start()
    # Les modèles (langage, voix) sont chargés en tâche de fond : l'API répond tout de suite.
    llm.warm_up()
    voice.preload()
    # Un Mac endormi ne répond plus au téléphone.
    awake = keep_awake(KEEP_AWAKE)
    if awake is not None:
        print(f"[JARVIS] Mise en veille du Mac empêchée ({KEEP_AWAKE}) tant que Jarvis tourne", flush=True)
    if _on_demand and IDLE_MINUTES:
        watch_idle(activity, IDLE_MINUTES, _keeps_awake, _go_to_sleep)
        print(f"[JARVIS] Lancé à la demande : arrêt après {IDLE_MINUTES} min sans demande", flush=True)
    for controller in jarvis.controllers:
        print(f"[JARVIS] {controller.name} → {', '.join(agent.name for agent in controller.agents)}", flush=True)
    print(f"[JARVIS] En ligne — interface : http://{'localhost' if HOST in {'127.0.0.1', '0.0.0.0'} else HOST}:{PORT}/", flush=True)

    yield

    if awake is not None:
        awake.terminate()

    if env_flag("GOOGLE_FORGET_TOKEN_ON_EXIT", True):
        try:
            result = context.google.disconnect(revoke=False)
            if result.get("token_deleted"):
                print(f"[GOOGLE] Token local supprimé à l'arrêt: {result.get('token_path')}")
        except Exception as exc:
            print(f"[GOOGLE] Impossible de supprimer le token local à l'arrêt: {exc}")


# ── Routes HTTP ──────────────────────────────────────────────────────
app = FastAPI(title="Jarvis API", version=VERSION, lifespan=lifespan)
security.protect(app, (ActivityTracker, {"activity": activity}))
app.include_router(chat.router(jarvis))
app.include_router(voice_routes.router())
app.include_router(hud.router(jarvis))
app.include_router(google.router(context))
app.include_router(creations.router(creation.workshop))
hud.mount_interface(app)


def serve() -> None:
    """Démarre le serveur sur http://localhost:8001.

    Lancé à la demande par le service macOS, il reprend le port que le système surveillait.
    """
    import uvicorn

    global _server, _on_demand
    sockets = launchd_sockets()
    _on_demand = bool(sockets)
    _server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT))
    _server.run(sockets=sockets or None)


if __name__ == "__main__":
    # Le module « main » (et non « __main__ ») : c'est son application et son état qui sont servis.
    import main

    main.serve()
