"""Configuration commune des tests : isole l'API de la machine réelle.

Les variables sont posées avant tout import des modules de l'API, car config.py
lit l'environnement une seule fois, à l'import.
"""

import os
import sys
import tempfile
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1] / "Jarvis" / "API"
sys.path.insert(0, str(API_DIR))

_TMP = Path(tempfile.mkdtemp(prefix="jarvis-tests-"))

os.environ.update(
    {
        "JARVIS_USER_TITLE": "Monsieur",
        "JARVIS_CITY": "Paris",
        "JARVIS_STRICT_ACTIONS_ONLY": "0",
        "JARVIS_CONFIRM_ACTIONS": "1",
        "JARVIS_WEB_SEARCH": "1",
        "JARVIS_REMOTE_SYSTEM_CONTROL": "0",
        # Les tests n'empêchent pas le Mac de se mettre en veille.
        "JARVIS_KEEP_AWAKE": "0",
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_ALLOWED_USERS": "",
        # Aucun modèle n'est chargé pendant les tests.
        "JARVIS_TTS_ENGINE": "off",
        "JARVIS_STT_ENGINE": "off",
        "OLLAMA_URL": "http://127.0.0.1:9",
        "OLLAMA_MODEL": "jarvis-test",
        # Aucun fichier réel de l'utilisateur n'est touché.
        "ALARMS_FILE": str(_TMP / "alarms.json"),
        "GOOGLE_TOKEN_FILE": str(_TMP / "google-token.json"),
        "GOOGLE_CLIENT_SECRET_FILE": "",
        "GOOGLE_TIMEZONE": "Europe/Paris",
        "GOOGLE_FORGET_TOKEN_ON_EXIT": "0",
        "JARVIS_CONTACTS_FILE": str(_TMP / "contacts.json"),
        # Les réglages personnels du .env ne doivent pas influencer les tests.
        "JARVIS_STT_VOCABULARY": "",
        "JARVIS_WAKE_WORD": "jarvis",
        "JARVIS_ALLOWED_ORIGINS": "",
        "ALARM_NOTIFICATION_ENABLED": "0",
        "ALARM_SOUND_ENABLED": "0",
        # Les créations des agents code et design restent dans le dossier temporaire.
        "JARVIS_CREATIONS_DIR": str(_TMP / "creations"),
        # Mémoire, journal des incompris et routines : jamais les fichiers réels.
        "JARVIS_MEMORY_FILE": str(_TMP / "memory.json"),
        "JARVIS_MISSES_FILE": str(_TMP / "incompris.jsonl"),
        "JARVIS_ROUTINES_FILE": str(_TMP / "routines.json"),
        # La relecture visuelle demande Quick Look et le modèle : testée à part.
        "JARVIS_DESIGN_SELF_REVIEW": "0",
        "JARVIS_HOME_ADDRESS": "",
    }
)

(_TMP / "contacts.json").write_text('{"Paul": "paul@exemple.com", "Sophie Martin": "sophie@exemple.com"}', encoding="utf-8")
