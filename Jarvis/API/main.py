from __future__ import annotations
import os
import re
import threading
from pathlib import Path
from typing import Optional
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from alarms import AlarmStore
from alarm_actions import (
    ALARM_NOTIFICATION_ENABLED,
    ALARM_SOUND_ENABLED,
    ALARM_SOUND_FILE,
    ALARM_SOUND_REPEAT,
    alarm_scheduler_loop,
    handle_delete_alarm,
    handle_delete_alarms_all,
    handle_delete_alarms_range,
    handle_list_alarms,
    handle_set_alarm,
)
from calendar_actions import (
    handle_add_event,
    handle_availability_week,
    handle_delete_event,
    handle_delete_events_range,
    handle_events_range,
    handle_events_week,
)
from google_client import GoogleApiError, GoogleClient, GoogleConfigError
from intents import COMMAND_HELP, detect_action
from mail_actions import (
    extract_recent_email_from_history,
    format_last_mail,
    format_mail_resume,
    handle_send_mail,
    normalize_generated_french,
)


ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ROOT_ENV)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").strip()
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "jarvis").strip()
SYSTEM_PROMPT_FILE = Path(__file__).resolve().parents[1] / "system_prompt.txt"
STRICT_ACTIONS_ONLY = os.getenv("JARVIS_STRICT_ACTIONS_ONLY", "1").strip().lower() not in {"0", "false", "no"}

OUT_OF_SCOPE_REPLY = (
    "Je ne peux pas répondre à cette demande. "
    "Je suis limité aux actions email, calendrier et alarmes, "
    "et je ne fais pas de recherche générale. "
    "Utilise /help pour voir les commandes disponibles."
)

CAPABILITIES_REPLY = (
    "Je peux t'aider sur 3 domaines: "
    "emails (lire/resumer/envoyer), calendrier (lister/creer/supprimer des evenements) avec Google "
    "et alarmes (creer/lister/supprimer). "
    "Pour la liste complete des commandes, ecris help ou commandes. "
    "Sinon parle moi normalement, je vais essayer de comprendre si tu veux faire une action."
)


def load_system_prompt() -> str:
    """Charge le prompt système partagé depuis le fichier de configuration."""
    if SYSTEM_PROMPT_FILE.exists():
        text = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()
        if text:
            return text
    return "Tu es Jarvis, un assistant personnel professionnel."

SYSTEM_PROMPT = load_system_prompt()


class HistoryMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    history: list[HistoryMessage] = Field(default_factory=list)
    temperature: float = 0.3


class ChatResponse(BaseModel):
    reply: str
    action: Optional[str] = None
    source: str = "api"


app = FastAPI(title="Jarvis API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


mail_client = GoogleClient.from_env()
alarms = AlarmStore.from_env(mail_client.timezone_name)
_alarm_scheduler_started = False


def ollama_status() -> tuple[bool, str]:
    """Vérifie si Ollama répond et si le modèle configuré est disponible."""
    try:
        res = requests.get(f"{OLLAMA_URL}/api/tags", timeout=4)
        res.raise_for_status()
        data = res.json()
        models = [item.get("name", "") for item in data.get("models", [])]
        online = any(OLLAMA_MODEL in name for name in models)
        if not online:
            return False, f'model "{OLLAMA_MODEL}" not found in Ollama'
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


@app.on_event("startup")
def start_alarm_scheduler() -> None:
    """Démarre le scheduler d'alarmes à l'initialisation de l'API."""
    global _alarm_scheduler_started
    if _alarm_scheduler_started:
        return
    print(
        "[ALARM] scheduler started "
        f"(notification={ALARM_NOTIFICATION_ENABLED}, sound={ALARM_SOUND_ENABLED}, "
        f"repeat={ALARM_SOUND_REPEAT}, sound_file={ALARM_SOUND_FILE})"
    , flush=True)
    thread = threading.Thread(target=alarm_scheduler_loop, args=(alarms,), daemon=True)
    thread.start()
    _alarm_scheduler_started = True


@app.on_event("shutdown")
def clear_google_token_on_shutdown() -> None:
    """Supprime le token Google local à l'arrêt du service API."""
    try:
        result = mail_client.disconnect(revoke=False)
        if result.get("token_deleted"):
            print(f"[GOOGLE] Token local supprimé à l'arrêt: {result.get('token_path')}")
    except Exception as exc:
        print(f"[GOOGLE] Impossible de supprimer le token local à l'arrêt: {exc}")


def call_ollama(history: list[HistoryMessage], message: str, temperature: float) -> str:
    """Appelle Ollama en mode chat avec le prompt système et l'historique."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend({"role": item.role, "content": item.content} for item in history)

    if not history or history[-1].role != "user" or history[-1].content != message:
        messages.append({"role": "user", "content": message})

    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "options": {"temperature": temperature, "num_predict": 256},
        "stream": False,
    }
    res = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=90)
    res.raise_for_status()
    data = res.json()
    raw = data.get("message", {}).get("content") or "Je n'ai pas de réponse pour le moment."
    return normalize_generated_french(raw)


def run_action(action_payload: dict) -> str:
    """Exécute une action métier détectée depuis la requête utilisateur."""
    action = action_payload.get("action")
    params = action_payload.get("params", {})

    if action == "help":
        return COMMAND_HELP

    if action == "mail_resume":
        return format_mail_resume(mail_client.get_unread_emails(limit=5))

    if action == "mail_last":
        return format_last_mail(mail_client.get_latest_email())

    if action == "send_mail":
        return handle_send_mail(mail_client, params, ollama_url=OLLAMA_URL, ollama_model=OLLAMA_MODEL)

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
        return handle_delete_alarms_all(alarms)

    if action == "command_error":
        return str(action_payload.get("message", "Commande invalide."))

    return "Action non supportée."


def classify_support_request(text: str) -> str | None:
    """Classe les demandes d'aide entre liste des commandes et capacites generales."""
    lowered = (text or "").lower().replace("’", "'").strip()

    command_patterns = [
        r"\bhelp\b",
        r"\baide\b",
        r"\bcommandes?\b",
        r"\bliste\s+des\s+commandes\b",
    ]
    if any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in command_patterns):
        return "commands"

    capability_patterns = [
        r"\bque\s+peux[-\s]?tu\s+faire\b",
        r"\bqu[' ]?est[-\s]?ce\s+que\s+tu\s+peux\s+faire\b",
        r"\bquelles?\s+sont\s+tes\s+capacites\b",
        r"\btes\s+fonctions\b",
        r"\btu\s+sais\s+faire\s+quoi\b",
    ]
    if any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in capability_patterns):
        return "capabilities"

    return None


@app.get("/api/status")
def api_status() -> dict:
    """Retourne l'état de santé de l'API, du modèle et du provider mail."""
    model_online, model_reason = ollama_status()
    mail_status = mail_client.status()
    return {
        "ok": True,
        "model_online": model_online,
        "model_reason": model_reason,
        "model_name": OLLAMA_MODEL,
        "mail": mail_status,
    }


@app.get("/api/commands")
def api_commands() -> dict:
    """Expose la liste des commandes supportées par l'API."""
    return {"commands_help": COMMAND_HELP}


@app.post("/api/google/connect")
def api_google_connect() -> dict:
    """Lance le flux OAuth Google et enregistre le token local."""
    try:
        token_path = mail_client.setup_oauth_token()
        return {
            "ok": True,
            "message": "Compte Google connecté.",
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
        return {
            "ok": True,
            "message": "Compte Google déconnecté.",
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
    """Point d'entrée principal: route les actions ou interroge Ollama."""
    text = request.message.strip()
    model_online, _ = ollama_status()
    if not model_online:
        return ChatResponse(
            reply=" JARVIS INDISPONIBLE\nLe modèle Ollama est hors ligne ou introuvable.",
            source="api",
        )

    fallback_email = extract_recent_email_from_history(request.history)
    action_payload = detect_action(text, fallback_email=fallback_email)

    if action_payload is not None:
        try:
            reply = run_action(action_payload)
            action_name = action_payload.get("action")
            mail_actions = {
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
            provider_name = mail_client.status().get("provider", "google")
            source = provider_name if action_name in mail_actions else "api"
            return ChatResponse(reply=reply, action=action_payload.get("action"), source=source)
        except GoogleConfigError:
            provider_status = mail_client.status()
            missing = ", ".join(provider_status.get("missing_keys", []))
            provider_label = provider_status.get("provider_label", provider_status.get("provider", "mail"))
            return ChatResponse(
                reply=(
                    f" Compte {provider_label} non configuré pour les actions réelles.\n"
                    f"Variables manquantes: {missing}\n"
                    "Consulte le README pour la configuration du provider mail/calendrier."
                ),
                action=action_payload.get("action"),
                source="api",
            )
        except GoogleApiError as exc:
            provider_status = mail_client.status()
            provider_label = provider_status.get("provider_label", provider_status.get("provider", "mail"))
            return ChatResponse(
                reply=f" Erreur {provider_label}: {exc}",
                action=action_payload.get("action"),
                source=provider_status.get("provider", "google"),
            )

    support_kind = classify_support_request(text)
    if support_kind == "commands":
        return ChatResponse(reply=COMMAND_HELP, action="help", source="api")
    if support_kind == "capabilities":
        return ChatResponse(reply=CAPABILITIES_REPLY, source="api")

    if STRICT_ACTIONS_ONLY:
        return ChatResponse(reply=OUT_OF_SCOPE_REPLY, source="api")

    try:
        answer = call_ollama(request.history, text, request.temperature)
        return ChatResponse(reply=answer, source="ollama")
    except Exception as exc:
        return ChatResponse(reply=f" Erreur Ollama: {exc}", source="api")


if __name__ == "__main__":
    """ Démarre le serveur API avec Uvicorn. Accessible sur http://localhost:8001"""
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=False)