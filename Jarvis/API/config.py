"""Configuration centralisée de l'API Jarvis.

Ce module charge le fichier .env AVANT toute lecture de variable d'environnement.
Tous les autres modules doivent lire leur configuration ici, jamais via os.getenv
à l'import, sinon les valeurs du .env sont ignorées.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv


API_DIR = Path(__file__).resolve().parent
PROJECT_DIR = API_DIR.parent
ROOT_DIR = PROJECT_DIR.parent
INTERFACE_DIR = PROJECT_DIR / "Interface"
SYSTEM_PROMPT_FILE = PROJECT_DIR / "system_prompt.txt"

load_dotenv(ROOT_DIR / ".env")


def env_str(name: str, default: str = "") -> str:
    """Lit une chaîne de configuration (valeur vide = valeur par défaut)."""
    value = (os.getenv(name) or "").strip()
    return value or default


def env_flag(name: str, default: bool) -> bool:
    """Lit un booléen depuis une variable d'environnement avec valeur par défaut."""
    raw = env_str(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on", "oui"}


def env_int(name: str, default: int, min_value: int, max_value: int) -> int:
    """Lit un entier de configuration et le borne entre min_value et max_value."""
    try:
        parsed = int(env_str(name, str(default)))
    except ValueError:
        parsed = default
    return max(min_value, min(max_value, parsed))


def env_float(name: str, default: float, min_value: float, max_value: float) -> float:
    """Lit un flottant de configuration et le borne entre min_value et max_value."""
    try:
        parsed = float(env_str(name, str(default)))
    except ValueError:
        parsed = default
    return max(min_value, min(max_value, parsed))


def env_list(name: str, default: list[str]) -> list[str]:
    """Lit une liste séparée par des virgules."""
    raw = env_str(name)
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# ── Persona ────────────────────────────────────────────────────────────────
# Formule d'appel utilisée par Jarvis (« Monsieur » comme dans Iron Man).
USER_TITLE = env_str("JARVIS_USER_TITLE", "Monsieur")
# Ville utilisée par défaut pour la météo et le briefing.
CITY = env_str("JARVIS_CITY", "Paris")

# ── Modèle de langage (Ollama) ─────────────────────────────────────────────
OLLAMA_URL = env_str("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = env_str("OLLAMA_MODEL", "jarvis")
OLLAMA_KEEP_ALIVE = env_str("OLLAMA_KEEP_ALIVE", "30m")
LLM_MAX_TOKENS = env_int("JARVIS_MAX_TOKENS", 320, 32, 2048)
LLM_HISTORY_MESSAGES = env_int("JARVIS_HISTORY_MESSAGES", 12, 0, 60)

# 1 = Jarvis refuse tout ce qui n'est pas une action reconnue (ancien comportement).
# 0 (défaut) = Jarvis converse librement, comme dans Iron Man.
STRICT_ACTIONS_ONLY = env_flag("JARVIS_STRICT_ACTIONS_ONLY", False)
# Demande une confirmation avant les actions sensibles (envoi de mail, suppressions en masse).
CONFIRM_ACTIONS = env_flag("JARVIS_CONFIRM_ACTIONS", True)
# 1 (défaut) : Jarvis cherche lui-même sur le web (DuckDuckGo) et lit les pages pour répondre.
# 0 : rien ne sort du poste ; il se contente d'ouvrir la recherche dans le navigateur.
WEB_SEARCH_ENABLED = env_flag("JARVIS_WEB_SEARCH", True)

# ── Serveur ────────────────────────────────────────────────────────────────
HOST = env_str("JARVIS_HOST", "127.0.0.1")
PORT = env_int("JARVIS_PORT", 8001, 1, 65535)
# Origines web autorisées à piloter l'API (en plus de localhost, toujours autorisé).
EXTRA_ALLOWED_ORIGINS = env_list("JARVIS_ALLOWED_ORIGINS", [])
# Clients distants (ex: Discord) autorisés à piloter le poste (applications, volume, veille).
REMOTE_SYSTEM_CONTROL = env_flag("JARVIS_REMOTE_SYSTEM_CONTROL", False)
# Code exigé pour utiliser Jarvis depuis un autre appareil (téléphone). Vide = accès à distance refusé.
ACCESS_TOKEN = env_str("JARVIS_ACCESS_TOKEN", "")

# ── Voix ───────────────────────────────────────────────────────────────────
# auto | piper | say | browser | off
TTS_ENGINE = env_str("JARVIS_TTS_ENGINE", "auto").lower()
TTS_VOICE = env_str("JARVIS_TTS_VOICE", "")
TTS_RATE = env_float("JARVIS_TTS_RATE", 1.0, 0.5, 2.0)
PIPER_VOICE = env_str("JARVIS_PIPER_VOICE", "fr_FR-tom-medium")
VOICES_DIR = Path(env_str("JARVIS_VOICES_DIR", str(API_DIR / "voices"))).expanduser()

# auto | mlx | whisper | browser | off
STT_ENGINE = env_str("JARVIS_STT_ENGINE", "auto").lower()
# Vide = modèle par défaut du moteur : large-v3-turbo sur la puce graphique (mlx), small sur le processeur.
WHISPER_MODEL = env_str("JARVIS_WHISPER_MODEL", "")
STT_LANGUAGE = env_str("JARVIS_STT_LANGUAGE", "fr")
WAKE_WORD = env_str("JARVIS_WAKE_WORD", "jarvis").lower()
# Noms propres que la reconnaissance vocale doit savoir écrire (lieux, enseignes, prénoms…).
# La ville et les contacts du carnet d'adresses y sont ajoutés automatiquement.
STT_VOCABULARY = env_list("JARVIS_STT_VOCABULARY", [])

# ── Alarmes ────────────────────────────────────────────────────────────────
ALARM_NOTIFICATION_ENABLED = env_flag("ALARM_NOTIFICATION_ENABLED", True)
ALARM_SOUND_ENABLED = env_flag("ALARM_SOUND_ENABLED", True)
ALARM_SOUND_REPEAT = env_int("ALARM_SOUND_REPEAT", default=1, min_value=1, max_value=10)
ALARM_SOUND_FILE = env_str("ALARM_SOUND_FILE", "")

# ── Carnet d'adresses (nom → email) pour dicter un destinataire à la voix ──
CONTACTS_FILE = Path(env_str("JARVIS_CONTACTS_FILE", str(API_DIR / "contacts.json"))).expanduser()


def load_contacts() -> dict[str, str]:
    """Charge le carnet d'adresses (nom → email) utilisé pour dicter un destinataire."""
    try:
        data = json.loads(CONTACTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(name).strip(): str(email).strip() for name, email in data.items() if "@" in str(email)}
