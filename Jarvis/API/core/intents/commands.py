"""Les commandes « slash » (/mailresume, /setalarm…) et l'aide qui les liste."""

from __future__ import annotations

import re
import shlex
from datetime import timedelta

from core.intents.common import parse_datetime, parse_day_value


COMMAND_HELP = """Commandes disponibles :

Messagerie
/mailresume
/maillast
/sendmail \"destinataire@domaine.com\" \"Objet\" \"Message\"

Agenda
/eventsweek
/availability
/addevent \"Titre\" \"YYYY-MM-DD HH:MM\" \"YYYY-MM-DD HH:MM\"
/deleteevent \"id\"
/deleteeventsrange \"YYYY-MM-DD\" \"YYYY-MM-DD\"

Alarmes
/setalarm \"YYYY-MM-DD HH:MM\" \"Titre\"
/alarms
/deletealarm \"id\"
/deletealarmsrange \"YYYY-MM-DD\" \"YYYY-MM-DD\"
/deletealarmsall

Poste et informations
/briefing
/status
/weather \"Ville\"
/time
/open \"Application\"
/close \"Application\"
/volume 40 (ou up, down, mute, unmute)
/search \"requête\"
/sleep

Création
/code "ce que doit faire le programme"
/design "sujet de la page web"
/logo "pour qui ou pour quoi"
/palette "ambiance ou sujet"
/creations
/incompris  (phrases que Jarvis n'a pas reconnues)
/help
"""


def parse_command(text: str) -> dict:
    """Parse les commandes slash et retourne l'action structurée à exécuter."""
    try:
        parts = shlex.split(text)
    except ValueError:
        return {
            "action": "command_error",
            "message": "Commande invalide. Vérifie les guillemets.\n\n" + COMMAND_HELP,
        }

    if not parts:
        return {"action": "command_error", "message": COMMAND_HELP}

    command = parts[0].lower()

    if command in {"/help", "/commands"}:
        return {"action": "help"}

    if command == "/mailresume":
        return {"action": "mail_resume"}

    if command == "/maillast":
        return {"action": "mail_last"}

    if command == "/sendmail":
        if len(parts) < 4:
            return {
                "action": "command_error",
                "message": "Format attendu:\n/sendmail \"destinataire@domaine.com\" \"Objet\" \"Message\"",
            }

        to_email = parts[1].strip()
        subject = parts[2].strip()
        body = " ".join(parts[3:]).strip()

        if "@" not in to_email:
            return {
                "action": "command_error",
                "message": "Adresse email invalide.",
            }

        return {
            "action": "send_mail",
            "params": {
                "to_email": to_email,
                "subject": subject,
                "body": body,
                "auto_subject": False,
                "auto_draft": False,
                "auto_polish": False,
                "draft_context": body,
            },
        }

    if command == "/eventsweek":
        return {"action": "events_week"}

    if command == "/availability":
        return {"action": "availability_week"}

    if command == "/addevent":
        if len(parts) < 4:
            return {
                "action": "command_error",
                "message": "Format attendu:\n/addevent \"Titre\" \"YYYY-MM-DD HH:MM\" \"YYYY-MM-DD HH:MM\"",
            }

        title = parts[1]
        try:
            start = parse_datetime(parts[2])
            end = parse_datetime(parts[3])
        except ValueError:
            return {
                "action": "command_error",
                "message": "Dates invalides. Utilise le format YYYY-MM-DD HH:MM.",
            }

        if end <= start:
            return {
                "action": "command_error",
                "message": "La date de fin doit être après la date de début.",
            }

        return {
            "action": "add_event",
            "params": {
                "title": title,
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        }

    if command in {"/deleteevent", "/delevent"}:
        if len(parts) < 2:
            return {
                "action": "command_error",
                "message": "Format attendu:\n/deleteevent \"id\"",
            }
        return {
            "action": "delete_event",
            "params": {
                "event_id": parts[1].strip(),
            },
        }

    if command in {"/deleteeventsrange", "/deleteeventrange", "/deleverange"}:
        if len(parts) < 2:
            return {
                "action": "command_error",
                "message": "Format attendu:\n/deleteeventsrange \"YYYY-MM-DD\" \"YYYY-MM-DD\"",
            }

        start_day = parse_day_value(parts[1])
        end_day = parse_day_value(parts[2]) if len(parts) >= 3 else start_day

        if start_day is None or end_day is None:
            return {
                "action": "command_error",
                "message": "Dates invalides. Utilise le format YYYY-MM-DD.",
            }

        if end_day < start_day:
            start_day, end_day = end_day, start_day

        return {
            "action": "delete_events_range",
            "params": {
                "start": start_day.isoformat(),
                "end": (end_day + timedelta(days=1)).isoformat(),
            },
        }

    if command in {"/setalarm", "/addalarm"}:
        if len(parts) < 3:
            return {
                "action": "command_error",
                "message": "Format attendu:\n/setalarm \"YYYY-MM-DD HH:MM\" \"Titre\"",
            }

        try:
            when = parse_datetime(parts[1])
        except ValueError:
            return {
                "action": "command_error",
                "message": "Date invalide. Utilise le format YYYY-MM-DD HH:MM.",
            }

        title = " ".join(parts[2:]).strip()
        if not title:
            return {
                "action": "command_error",
                "message": "Le titre de l'alarme ne peut pas être vide.",
            }

        return {
            "action": "set_alarm",
            "params": {
                "when": when.isoformat(),
                "title": title,
            },
        }

    if command == "/alarms":
        return {"action": "list_alarms"}

    if command in {"/deletealarm", "/delalarm"}:
        if len(parts) < 2:
            return {
                "action": "command_error",
                "message": "Format attendu:\n/deletealarm \"id\"",
            }
        return {
            "action": "delete_alarm",
            "params": {
                "alarm_id": parts[1].strip(),
            },
        }

    if command in {"/deletealarmsrange", "/deletealarmrange"}:
        if len(parts) < 2:
            return {
                "action": "command_error",
                "message": "Format attendu:\n/deletealarmsrange \"YYYY-MM-DD\" \"YYYY-MM-DD\"",
            }

        start_day = parse_day_value(parts[1])
        end_day = parse_day_value(parts[2]) if len(parts) >= 3 else start_day

        if start_day is None or end_day is None:
            return {
                "action": "command_error",
                "message": "Dates invalides. Utilise le format YYYY-MM-DD.",
            }

        if end_day < start_day:
            start_day, end_day = end_day, start_day

        return {
            "action": "delete_alarms_range",
            "params": {
                "start": start_day.isoformat(),
                "end": (end_day + timedelta(days=1)).isoformat(),
            },
        }

    if command in {"/deletealarmsall", "/deleteallalarms"}:
        return {"action": "delete_alarms_all"}

    if command in {"/briefing", "/brief"}:
        return {"action": "briefing"}

    if command in {"/status", "/diagnostic", "/system"}:
        return {"action": "system_status"}

    if command == "/battery":
        return {"action": "system_status", "params": {"focus": "battery"}}

    if command in {"/weather", "/meteo"}:
        return {"action": "weather", "params": {"city": " ".join(parts[1:]).strip() or None}}

    if command == "/time":
        return {"action": "time"}

    if command == "/date":
        return {"action": "date"}

    if command in {"/open", "/close"}:
        if len(parts) < 2:
            return {"action": "command_error", "message": f"Format attendu:\n{command} \"Application\""}
        target = " ".join(parts[1:]).strip()
        if command == "/close":
            return {"action": "quit_app", "params": {"name": target}}
        if re.fullmatch(r"(?:https?://)?[\w-]+(?:\.[\w-]+)+(?:/\S*)?", target):
            return {"action": "open_url", "params": {"url": target}}
        return {"action": "open_app", "params": {"name": target}}

    if command == "/volume":
        if len(parts) < 2:
            return {"action": "volume", "params": {"mode": "get"}}
        value = parts[1].lower().rstrip("%")
        if value.isdigit():
            return {"action": "volume", "params": {"mode": "set", "level": int(value)}}
        if value in {"up", "down", "mute", "unmute"}:
            return {"action": "volume", "params": {"mode": value}}
        return {"action": "command_error", "message": "Format attendu:\n/volume 40 (ou up, down, mute, unmute)"}

    if command == "/search":
        if len(parts) < 2:
            return {"action": "command_error", "message": "Format attendu:\n/search \"requête\""}
        return {"action": "web_search", "params": {"query": " ".join(parts[1:]).strip(), "engine": "web"}}

    if command == "/sleep":
        return {"action": "sleep_display"}

    creations = {"/code": "write_code", "/design": "design_page", "/logo": "design_logo", "/palette": "design_palette"}
    if command in creations:
        request = " ".join(parts[1:]).strip()
        if not request and command != "/palette":
            return {"action": "command_error", "message": f'Format attendu:\n{command} "description"'}
        return {"action": creations[command], "params": {"request": request}}

    if command == "/creations":
        return {"action": "list_creations"}

    if command == "/incompris":
        return {"action": "misses"}

    return {
        "action": "command_error",
        "message": f"Commande inconnue: {command}\n\n{COMMAND_HELP}",
    }
