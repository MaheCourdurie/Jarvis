from __future__ import annotations

import json
import re
import threading
from contextlib import asynccontextmanager
from typing import Iterator, Optional
from urllib.parse import urlparse

import config  # noqa: F401  (premier import local : charge le .env avant les autres modules)
import events
import llm
import voice
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from alarms import AlarmStore
from alarm_actions import (
    alarm_scheduler_loop,
    handle_delete_alarm,
    handle_delete_alarms_all,
    handle_delete_alarms_range,
    handle_delete_timers,
    handle_list_alarms,
    handle_set_alarm,
)
from briefing import Dashboard, build_briefing, live_context
from calendar_actions import (
    handle_add_event,
    handle_availability_week,
    handle_delete_event,
    handle_delete_events_range,
    handle_events_range,
    handle_events_week,
)
from config import (
    ALARM_NOTIFICATION_ENABLED,
    ALARM_SOUND_ENABLED,
    ALARM_SOUND_FILE,
    ALARM_SOUND_REPEAT,
    CITY,
    CONFIRM_ACTIONS,
    EXTRA_ALLOWED_ORIGINS,
    HOST,
    INTERFACE_DIR,
    OLLAMA_MODEL,
    PORT,
    REMOTE_SYSTEM_CONTROL,
    STRICT_ACTIONS_ONLY,
    WAKE_WORD,
    env_flag,
)
from google_client import GoogleApiError, GoogleClient, GoogleConfigError
from intents import COMMAND_HELP, classify_confirmation, detect_action
from mail_actions import (
    extract_recent_email_from_history,
    format_last_mail,
    format_mail_resume,
    handle_send_mail,
)
from persona import Reply, TITLE, fold
from system_actions import (
    SYSTEM_CONTROL_ACTIONS,
    handle_date,
    handle_open_app,
    handle_open_url,
    handle_quit_app,
    handle_sleep_display,
    handle_system_status,
    handle_time,
    handle_volume,
    handle_web_search,
    read_system_metrics,
    system_alerts,
)
from weather import handle_weather


VERSION = "2.0.0"

# Seules les pages servies depuis ce poste peuvent piloter l'API : Jarvis envoie des
# mails et agit sur l'ordinateur, il ne doit pas obéir à un site web quelconque.
LOCAL_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
LOCAL_CLIENTS = {"web", "hud", "local"}
GOOGLE_ACTIONS = {
    "mail_resume",
    "mail_last",
    "send_mail",
    "events_week",
    "events_range",
    "availability_week",
    "add_event",
    "delete_event",
    "delete_events_range",
}
# Actions qui modifient l'agenda ou la messagerie : le tableau de bord doit être relu ensuite.
GOOGLE_WRITES = {"send_mail", "add_event", "delete_event", "delete_events_range"}
CONFIRMABLE_ACTIONS = {"send_mail", "delete_events_range", "delete_alarms_all"}
MAX_STT_BYTES = 4 * 1024 * 1024

OUT_OF_SCOPE_REPLY = (
    f"Je crains que cette demande ne sorte de mon périmètre actuel, {TITLE} : "
    "en mode strict, je me limite à la messagerie, à l'agenda, aux alarmes et au pilotage du poste. "
    "Dites « aide » pour la liste des commandes."
)

CAPABILITIES_REPLY = (
    f"Je gère votre messagerie, votre agenda, vos alarmes et vos minuteurs, {TITLE}. "
    "Je pilote ce poste — applications, volume, recherches — et je vous renseigne sur l'heure, "
    "la météo et l'état des systèmes. Pour le reste, je suis toujours disposé à converser. "
    "Dites « aide » pour la liste des commandes."
)


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


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


mail_client = GoogleClient.from_env()
alarms = AlarmStore.from_env(mail_client.timezone_name)
dashboard = Dashboard(mail_client, alarms)
_alarm_scheduler_started = False


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Démarre les tâches de fond à l'initialisation et nettoie à l'arrêt de l'API."""
    global _alarm_scheduler_started
    if not _alarm_scheduler_started:
        print(
            "[ALARM] scheduler started "
            f"(notification={ALARM_NOTIFICATION_ENABLED}, sound={ALARM_SOUND_ENABLED}, "
            f"repeat={ALARM_SOUND_REPEAT}, sound_file={ALARM_SOUND_FILE})",
            flush=True,
        )
        threading.Thread(target=alarm_scheduler_loop, args=(alarms,), daemon=True).start()
        _alarm_scheduler_started = True

    # Les modèles (langage, voix) sont chargés en tâche de fond : l'API répond tout de suite.
    llm.warm_up()
    voice.preload()
    print(f"[JARVIS] En ligne — interface : http://{'localhost' if HOST in {'127.0.0.1', '0.0.0.0'} else HOST}:{PORT}/", flush=True)

    yield

    if env_flag("GOOGLE_FORGET_TOKEN_ON_EXIT", True):
        try:
            result = mail_client.disconnect(revoke=False)
            if result.get("token_deleted"):
                print(f"[GOOGLE] Token local supprimé à l'arrêt: {result.get('token_path')}")
        except Exception as exc:
            print(f"[GOOGLE] Impossible de supprimer le token local à l'arrêt: {exc}")


def _allowed_hosts() -> list[str]:
    """Noms d'hôte acceptés : ce poste, plus ceux des origines explicitement autorisées."""
    hosts = {"localhost", "127.0.0.1"}
    for origin in EXTRA_ALLOWED_ORIGINS:
        hostname = urlparse(origin).hostname
        if hostname:
            hosts.add(hostname)
    return sorted(hosts)


app = FastAPI(title="Jarvis API", version=VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=EXTRA_ALLOWED_ORIGINS,
    allow_origin_regex=LOCAL_ORIGIN_REGEX,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
# Refuse les requêtes adressées à un autre nom d'hôte (protection contre le DNS rebinding).
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts())


def run_action(action_payload: dict) -> Reply:
    """Exécute une action métier détectée depuis la requête utilisateur."""
    action = action_payload.get("action")
    params = action_payload.get("params") or {}

    if action == "smalltalk":
        return action_payload["reply"]

    if action == "help":
        return Reply(text=COMMAND_HELP, speech=f"La liste des commandes est à l'écran, {TITLE}.")

    if action == "mail_resume":
        return format_mail_resume(mail_client.get_unread_emails(limit=5))

    if action == "mail_last":
        return format_last_mail(mail_client.get_latest_email())

    if action == "send_mail":
        return handle_send_mail(mail_client, params)

    if action == "events_week":
        return handle_events_week(mail_client)

    if action == "events_range":
        return handle_events_range(mail_client, params)

    if action == "availability_week":
        return handle_availability_week(mail_client)

    if action == "add_event":
        return handle_add_event(mail_client, params)

    if action == "delete_event":
        return handle_delete_event(mail_client, params)

    if action == "delete_events_range":
        return handle_delete_events_range(mail_client, params)

    if action == "set_alarm":
        return handle_set_alarm(alarms, mail_client.timezone, params)

    if action == "list_alarms":
        return handle_list_alarms(alarms, mail_client.timezone)

    if action == "delete_alarm":
        return handle_delete_alarm(alarms, params)

    if action == "delete_alarms_range":
        return handle_delete_alarms_range(alarms, params)

    if action == "delete_alarms_all":
        return handle_delete_alarms_all(alarms, params)

    if action == "delete_timers":
        return handle_delete_timers(alarms)

    if action == "time":
        return handle_time(mail_client.timezone)

    if action == "date":
        return handle_date(mail_client.timezone)

    if action == "weather":
        return handle_weather(params)

    if action == "briefing":
        return build_briefing(dashboard, kind="full")

    if action == "system_status":
        return handle_system_status(params)

    if action == "open_app":
        return handle_open_app(params)

    if action == "quit_app":
        return handle_quit_app(params)

    if action == "open_url":
        return handle_open_url(params)

    if action == "web_search":
        return handle_web_search(params)

    if action == "volume":
        return handle_volume(params)

    if action == "sleep_display":
        return handle_sleep_display(params)

    if action == "command_error":
        return Reply(text=str(action_payload.get("message", "Commande invalide.")))

    return Reply(text=f"Cette action ne fait pas partie de mes attributions, {TITLE}.")


def classify_support_request(text: str) -> str | None:
    """Classe les demandes d'aide entre liste des commandes et capacites generales."""
    folded = fold(text).strip(" .!?")

    if re.fullmatch(
        r"(?:help|aide|a l'aide|commandes?|(?:la )?liste des commandes|quelles sont (?:les|tes|vos) commandes)",
        folded,
    ):
        return "commands"

    capability_patterns = [
        r"\bque\s+(?:peux[-\s]?tu|pouvez[-\s]?vous|sais[-\s]?tu|savez[-\s]?vous)\s+faire\b",
        r"\bqu'est[-\s]?ce\s+que\s+(?:tu\s+(?:peux|sais)|vous\s+(?:pouvez|savez))\s+faire\b",
        r"\bquelles?\s+sont\s+(?:tes|vos)\s+(?:capacites|fonctions|fonctionnalites|competences)\b",
        r"\b(?:tes|vos)\s+fonctions\b",
        r"\btu\s+sais\s+faire\s+quoi\b",
    ]
    if any(re.search(pattern, folded) for pattern in capability_patterns):
        return "capabilities"

    return None


def _response(reply: Reply, action: str | None = None, source: str = "api") -> dict:
    """Convertit la réponse d'un module en réponse d'API."""
    return {
        "reply": reply.text,
        "speech": reply.spoken,
        "action": action,
        "source": source,
        "pending": reply.pending,
        "data": reply.data or None,
    }


def _execute(action_payload: dict) -> dict:
    """Exécute une action et traduit les erreurs Google dans le ton de Jarvis."""
    action_name = action_payload.get("action")
    provider = mail_client.status()
    source = provider.get("provider", "google") if action_name in GOOGLE_ACTIONS else "api"

    try:
        # Inutile de rédiger un mail ou de demander une confirmation si Google n'est pas relié.
        if action_name in GOOGLE_ACTIONS and not mail_client.is_configured():
            raise GoogleConfigError("liaison Google non établie")
        reply = run_action(action_payload)
    except GoogleConfigError:
        missing = ", ".join(mail_client.status().get("missing_keys", []))
        reply = Reply(
            text=(
                f"La liaison Google n'est pas établie, {TITLE}. "
                "Connectez votre compte depuis le panneau « Liaisons » du HUD, puis redemandez-moi."
                + (f"\nÉléments manquants : {missing}" if missing else "")
            ),
            speech=f"La liaison Google n'est pas établie, {TITLE}. Connectez votre compte, puis redemandez-moi.",
            data={"google_required": True},
        )
        return _response(reply, action_name, "api")
    except GoogleApiError as exc:
        reply = Reply(
            text=f"Google a refusé la demande, {TITLE} : {exc}",
            speech=f"Google a refusé la demande, {TITLE}. Le détail est à l'écran.",
        )
        return _response(reply, action_name, source)

    if action_name in GOOGLE_WRITES and reply.pending is None:
        dashboard.invalidate()
    return _response(reply, action_name, source)


def resolve(request: ChatRequest) -> tuple[Optional[dict], str]:
    """Traite tout ce qui ne demande pas le modèle de langage.

    Retourne (réponse, "") si un module a répondu, sinon (None, texte) : le texte
    doit alors être transmis au modèle pour une réponse conversationnelle.
    """
    text = request.message.strip()

    # 1) Réponse à une demande de confirmation (« Dois-je l'envoyer ? » → « oui »).
    pending = request.pending or {}
    if pending.get("action") in CONFIRMABLE_ACTIONS:
        decision = classify_confirmation(text)
        if decision == "yes":
            params = dict(pending.get("params") or {})
            params.pop("confirm", None)
            return _execute({"action": pending["action"], "params": params}), ""
        if decision == "no":
            return _response(Reply(text=f"Très bien, {TITLE}. Je n'en fais rien."), "cancelled"), ""

    # 2) Action reconnue par le routeur d'intentions.
    fallback_email = extract_recent_email_from_history(request.history)
    action_payload = detect_action(text, fallback_email=fallback_email)

    if action_payload is not None:
        action_name = action_payload.get("action")
        is_remote = request.client.lower() not in LOCAL_CLIENTS
        if action_name in SYSTEM_CONTROL_ACTIONS and is_remote and not REMOTE_SYSTEM_CONTROL:
            reply = Reply(text=f"Le pilotage du poste n'est possible que depuis le poste lui-même, {TITLE}.")
            return _response(reply, action_name), ""

        if not CONFIRM_ACTIONS and isinstance(action_payload.get("params"), dict):
            action_payload["params"].pop("confirm", None)
        return _execute(action_payload), ""

    # 3) Demandes d'aide.
    support_kind = classify_support_request(text)
    if support_kind == "commands":
        return _response(run_action({"action": "help"}), "help"), ""
    if support_kind == "capabilities":
        return _response(Reply(text=CAPABILITIES_REPLY)), ""

    # 4) Conversation : réservée au modèle, sauf en mode strict.
    if STRICT_ACTIONS_ONLY:
        return _response(Reply(text=OUT_OF_SCOPE_REPLY)), ""

    model_online, _reason = llm.ollama_status()
    if not model_online:
        reply = Reply(
            text=(
                f"Mes fonctions conversationnelles sont hors ligne, {TITLE} : le modèle « {OLLAMA_MODEL} » "
                "est introuvable dans Ollama. Lancez ./run_jarvis.sh create pour le rétablir. "
                "Mes modules (agenda, messagerie, alarmes, poste) restent opérationnels."
            ),
            speech=(
                f"Mes fonctions conversationnelles sont hors ligne, {TITLE}. "
                "Mes autres modules restent opérationnels."
            ),
        )
        return _response(reply), ""

    return None, text


def _llm_error(exc: Exception) -> dict:
    print(f"[LLM] Erreur: {exc}", flush=True)
    reply = Reply(
        text=f"Je rencontre une difficulté avec mon modèle de langage, {TITLE} : {exc}",
        speech=f"Je rencontre une difficulté avec mon modèle de langage, {TITLE}.",
    )
    return _response(reply)


@app.get("/api/status")
def api_status() -> dict:
    """Retourne l'état de santé de l'API, du modèle, de la voix et du provider mail."""
    model_online, model_reason = llm.ollama_status()
    return {
        "ok": True,
        "version": VERSION,
        "persona": {"title": TITLE, "city": CITY, "wake_word": WAKE_WORD},
        "model_online": model_online,
        "model_reason": model_reason,
        "model_name": OLLAMA_MODEL,
        "strict": STRICT_ACTIONS_ONLY,
        "mail": mail_client.status(),
        "voice": {"tts": voice.tts_status(), "stt": voice.stt_status()},
    }


@app.get("/api/commands")
def api_commands() -> dict:
    """Expose la liste des commandes supportées par l'API."""
    return {"commands_help": COMMAND_HELP}


@app.get("/api/system")
def api_system() -> dict:
    """Relevé en direct du poste (processeur, mémoire, disque, batterie) pour le HUD."""
    metrics = read_system_metrics()
    metrics["alerts"] = system_alerts(metrics)
    return metrics


@app.get("/api/dashboard")
def api_dashboard() -> dict:
    """État du jour affiché par le HUD : météo, agenda, messagerie, alarmes."""
    return dashboard.snapshot()


@app.get("/api/briefing")
def api_briefing(kind: str = "boot") -> dict:
    """Briefing prononcé par Jarvis (kind=boot au démarrage du HUD, kind=full sur demande)."""
    reply = build_briefing(dashboard, kind="full" if kind == "full" else "boot")
    return {"reply": reply.text, "speech": reply.spoken}


@app.get("/api/events")
def api_events(after: Optional[int] = None) -> dict:
    """Événements proactifs (alarmes) publiés depuis le dernier relevé du HUD."""
    if after is None:
        events.events_after(events.last_id())
        return {"events": [], "last_id": events.last_id()}
    return {"events": events.events_after(after), "last_id": events.last_id()}


@app.post("/api/google/connect")
def api_google_connect() -> dict:
    """Lance le flux OAuth Google et enregistre le token local."""
    try:
        token_path = mail_client.setup_oauth_token()
        dashboard.invalidate()
        return {
            "ok": True,
            "message": f"Liaison Google établie, {TITLE}.",
            "token_path": token_path,
            "mail": mail_client.status(),
        }
    except GoogleConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/google/disconnect")
def api_google_disconnect() -> dict:
    """Révoque la connexion Google et supprime le token local."""
    try:
        result = mail_client.disconnect(revoke=True)
        dashboard.invalidate()
        return {
            "ok": True,
            "message": f"Liaison Google coupée, {TITLE}.",
            "result": result,
            "mail": mail_client.status(),
        }
    except GoogleConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GoogleApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/alarms")
def api_alarms() -> dict:
    """Retourne la liste des alarmes encore actives."""
    return {
        "ok": True,
        "items": alarms.list_alarms(),
    }


@app.post("/api/chat", response_model=ChatResponse)
def api_chat(request: ChatRequest) -> ChatResponse:
    """Point d'entrée principal: exécute une action ou converse via le modèle."""
    response, text = resolve(request)
    if response is not None:
        return ChatResponse(**response)

    try:
        answer = llm.chat(request.history, text, request.temperature, live_context(dashboard, text))
        return ChatResponse(reply=answer, speech=answer, source="ollama")
    except Exception as exc:
        return ChatResponse(**_llm_error(exc))


def _chat_events(request: ChatRequest) -> Iterator[str]:
    """Produit la réponse au format NDJSON : les phrases du modèle arrivent une à une."""

    def line(payload: dict) -> str:
        return json.dumps(payload, ensure_ascii=False) + "\n"

    response, text = resolve(request)
    if response is not None:
        yield line({"type": "final", **response})
        return

    yield line({"type": "start", "source": "ollama"})
    sentences: list[str] = []
    try:
        for sentence in llm.chat_stream(request.history, text, request.temperature, live_context(dashboard, text)):
            sentences.append(sentence)
            yield line({"type": "sentence", "text": sentence})
    except Exception as exc:
        if not sentences:
            yield line({"type": "final", **_llm_error(exc)})
            return
        print(f"[LLM] Flux interrompu: {exc}", flush=True)

    answer = " ".join(sentences)
    yield line({"type": "final", "reply": answer, "speech": answer, "source": "ollama", "streamed": True})


@app.post("/api/chat/stream")
def api_chat_stream(request: ChatRequest) -> StreamingResponse:
    """Variante en flux de /api/chat, utilisée par le HUD pour parler sans attendre la fin."""
    return StreamingResponse(
        _chat_events(request),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/tts")
def api_tts(request: SpeakRequest) -> Response:
    """Synthétise la voix de Jarvis (audio WAV)."""
    try:
        audio = voice.synthesize(request.text)
    except voice.VoiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(content=audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@app.post("/api/stt")
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


# Le HUD est servi par l'API elle-même : une seule adresse à ouvrir (http://localhost:8001/).
if INTERFACE_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(INTERFACE_DIR), html=True), name="hud")


if __name__ == "__main__":
    """ Démarre le serveur API avec Uvicorn. Accessible sur http://localhost:8001"""
    import uvicorn

    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
