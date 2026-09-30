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
        "JARVIS_REMOTE_SYSTEM_CONTROL": "0",
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
        "ALARM_NOTIFICATION_ENABLED": "0",
        "ALARM_SOUND_ENABLED": "0",
    }
)

(_TMP / "contacts.json").write_text('{"Paul": "paul@exemple.com", "Sophie Martin": "sophie@exemple.com"}', encoding="utf-8")
