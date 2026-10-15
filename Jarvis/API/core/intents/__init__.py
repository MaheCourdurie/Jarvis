"""Le routeur d'intentions : comprendre une phrase sans le modèle de langage.

Chaque agent a son fichier de phrases (core/intents/<agent>.py) ; ce module les interroge
dans un ordre précis : une phrase revient au premier qui la reconnaît.

    common.py    dates et heures dites, durées, récurrences (partagés)
    commands.py  commandes « slash » et aide
    mail.py, calendar.py, alarms.py, notes.py, travel.py   (organisation)
    system.py, info.py, music.py, files.py                  (ordinateur)
    web.py, memory.py, translate.py, vision.py              (savoir)
    creation.py, routines.py, home.py                       (création, routines, maison)
"""

from __future__ import annotations

import re

from persona import fold, smalltalk_reply, strip_vocative
from core.intents import (
    alarms,
    calendar,
    creation,
    files,
    home,
    info,
    mail,
    memory,
    music,
    notes,
    routines,
    system,
    translate,
    travel,
    vision,
    web,
)
from core.intents.commands import COMMAND_HELP, parse_command
from core.intents.common import extract_relative_delay, parse_datetime_expression
from core.intents.mail import extract_recent_email_from_history

__all__ = [
    "COMMAND_HELP",
    "classify_confirmation",
    "detect_action",
    "extract_recent_email_from_history",
    "extract_relative_delay",
    "parse_datetime_expression",
]

_YES = re.compile(
    r"^(?:oui|ouais|yes|yep|affirmatif|absolument|exactement|tout a fait|bien sur|d'accord|ok|okay|c'est bon|parfait"
    r"|vas[- ]y|allez[- ]y|fais[- ]le|faites[- ]le|envoie(?:[- ]le)?|envoyez(?:[- ]le)?|confirme|je confirme|confirmer"
    r"|supprime(?:[- ]les)?|supprimez(?:[- ]les)?|tu peux|vous pouvez|s'il te plait|s'il vous plait)\b"
)
_NO = re.compile(
    r"^(?:non|nan|no|negatif|surtout pas|pas maintenant|pas du tout|annule|annulez|laisse tomber|laissez tomber"
    r"|oublie|oubliez|stop|attends|attendez|n'envoie|ne l'envoie|ne supprime)\b"
)


def classify_confirmation(text: str) -> str | None:
    """Interprète la réponse à une demande de confirmation : "yes", "no" ou None."""
    folded = fold(strip_vocative(text)).strip(" .!?,")
    if _NO.match(folded):
        return "no"
    if _YES.match(folded):
        return "yes"
    return None


def detect_action(text: str, fallback_email: str | None = None) -> dict | None:
    """Détecte l'action métier à partir d'un texte utilisateur brut."""
    stripped = text.strip()
    if not stripped:
        return None

    if stripped.startswith("/"):
        return parse_command(stripped)

    # Petites phrases du quotidien (« Jarvis ? », « merci », « tu es là ? ») : réponse immédiate.
    smalltalk = smalltalk_reply(stripped)
    if smalltalk is not None:
        return {"action": "smalltalk", "reply": smalltalk}

    # « Jarvis, ouvre Safari » → « ouvre Safari »
    stripped = strip_vocative(stripped) or stripped

    # L'ordre compte : une phrase revient au premier parseur qui la reconnaît.
    parsers = (
        lambda: mail.parse_send_mail(stripped, fallback_email=fallback_email),
        lambda: creation.parse_creation(stripped),
        lambda: mail.parse_mail_more(stripped),
        lambda: alarms.parse_snooze(stripped),
        lambda: system.parse_poste(stripped),
        lambda: alarms.parse_timer(stripped),
        lambda: alarms.parse_reminder(stripped),
        lambda: alarms.parse_alarm(stripped),
        lambda: calendar.parse_move_event(stripped),
        lambda: calendar.parse_calendar(stripped),
        lambda: notes.parse_notes(stripped),
        lambda: mail.parse_mail_reading(stripped),
        lambda: memory.parse_memory(stripped),
        lambda: routines.parse_routines(stripped),
        lambda: info.parse_sky(stripped),
        lambda: info.parse_info(stripped),
        lambda: translate.parse_translate(stripped),
        lambda: travel.parse_travel(stripped),
        lambda: files.parse_files(stripped),
        lambda: vision.parse_vision(stripped),
        lambda: music.parse_music(stripped),
        lambda: home.parse_home(stripped),
        lambda: web.parse_summarize_url(stripped),
        lambda: web.parse_encyclopedia(stripped),
        lambda: web.parse_web_question(stripped),
        lambda: system.parse_system(stripped),
    )
    for parser in parsers:
        action = parser()
        if action is not None:
            return action

    return None
