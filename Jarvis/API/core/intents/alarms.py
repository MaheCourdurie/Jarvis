"""Agent alarmes : alarmes, réveils, minuteurs, rappels, répétition."""

from __future__ import annotations

import re

from config import local_now
from persona import TITLE, fold
from core.intents.common import (
    capitalize,
    clean_fragment,
    extract_day_period_bounds,
    extract_relative_delay,
    extract_repeat,
    first_occurrence,
    parse_datetime_expression,
    strip_time_expressions,
)


def _extract_alarm_title(text: str, default: str = "Alarme") -> str:
    """Extrait un titre d'alarme depuis une phrase naturelle.

    Exemples pris en charge:
    - mets une alarme "PAUSE"
    - mets une alarme dans 1 min pour PAUSE
    - programme un reveil appele PAUSE
    """
    quoted = re.findall(r'"([^\"]+)"', text)
    if quoted:
        title = clean_fragment(quoted[-1])
        if title:
            return title

    # On prend le segment après le dernier "pour", débarrassé des indications d'heure.
    split_matches = re.split(r"\bpour\b", text, flags=re.IGNORECASE)
    if len(split_matches) >= 2:
        candidate = clean_fragment(strip_time_expressions(split_matches[-1]))
        if len(candidate) >= 2:
            return capitalize(candidate)

    named_match = re.search(r"\b(?:nomm[ée]e?|appel[ée]e?|intitul[ée]e?)\b\s+(.+)$", text, flags=re.IGNORECASE)
    if named_match:
        candidate = clean_fragment(named_match.group(1))
        if candidate:
            return candidate

    return default


def parse_timer(text: str) -> dict | None:
    """Interprète une demande de minuteur (« minuteur de 10 minutes »)."""
    folded = fold(text)
    if not re.search(r"\b(?:minuteurs?|compte a rebours|chronometre|chrono|timer)\b", folded):
        return None

    if re.search(r"\b(?:supprime|annule|arrete|stoppe|coupe)\b", folded):
        return {"action": "delete_timers"}
    if re.search(r"\bcombien de temps\b|\breste[- ]t[- ]il\b|\b(?:temps )?restant\b|\bou en est\b|\bquels? (?:sont )?(?:mes |les )?minuteurs\b", folded):
        return {"action": "list_alarms"}

    delay = extract_relative_delay(text)
    if delay is None:
        return {
            "action": "command_error",
            "message": f"Pour quelle durée, {TITLE} ? Par exemple : minuteur de 10 minutes.",
        }

    label = ""
    label_match = re.search(r"\bpour\s+(.+)$", text, flags=re.IGNORECASE)
    if label_match:
        label = clean_fragment(strip_time_expressions(label_match.group(1)))
        label = re.sub(r"^\d+\s*(?:minutes?|min|mn|heures?|h|secondes?|sec)\b\s*", "", label, flags=re.IGNORECASE)
    title = f"Minuteur : {label}" if len(label) >= 2 else "Minuteur"

    return {
        "action": "set_alarm",
        "params": {"when": (local_now() + delay).isoformat(), "title": title, "kind": "timer"},
    }


def parse_reminder(text: str) -> dict | None:
    """Interprète un rappel (« rappelle-moi dans 20 minutes de sortir le gâteau »)."""
    lead = re.search(
        r"\b(?:rappelle|rappelez)[- ]moi\b|\bfai(?:s|tes)[- ]moi penser\b|\bpense à me rappeler\b"
        r"|\b(?:pr[ée]viens|pr[ée]venez|avertis|avertissez|alerte|alertez)[- ]moi\b",
        text,
        flags=re.IGNORECASE,
    )
    if not lead:
        return None

    when = parse_datetime_expression(text)
    if when is None:
        return {
            "action": "command_error",
            "message": (
                f"Quand dois-je vous le rappeler, {TITLE} ? "
                "Par exemple : rappelle-moi dans 20 minutes de sortir le gâteau."
            ),
        }

    subject = strip_time_expressions(text[: lead.start()] + " " + text[lead.end():])
    subject = re.sub(r"^(?:de|d'|que|qu'|à|a)\s*", "", subject.replace("’", "'"), flags=re.IGNORECASE)
    subject = clean_fragment(subject)

    return {
        "action": "set_alarm",
        "params": {
            "when": when.isoformat(),
            "title": capitalize(subject) if len(subject) >= 2 else "Rappel",
            "kind": "reminder",
        },
    }


def parse_alarm(text: str) -> dict | None:
    """Interprète une demande naturelle liée aux alarmes (création/liste/suppression)."""
    folded = fold(text)
    has_alarm_term = re.search(r"\b(?:alarmes?|reveils?)\b", folded) is not None
    wake_me = re.search(r"\breveille[sz]?[- ]moi\b", folded) is not None
    if not has_alarm_term and not wake_me:
        return None

    is_delete = re.search(r"\b(?:supprime|annule|efface|retire|enleve)\b", folded) is not None
    is_create = wake_me or re.search(r"\b(?:mets|met|ajoute|programme|cree|regle|lance)\b", folded) is not None

    if not is_delete and not is_create and re.search(r"\b(?:liste|montre|affiche|quelles?|mes|ai-je|combien)\b", folded):
        return {"action": "list_alarms"}

    if is_delete:
        day_period = extract_day_period_bounds(text)
        has_all_token = re.search(r"\b(?:tout|tous|toutes)\b", folded) is not None
        has_plural_alarm = re.search(r"\b(?:alarmes|reveils)\b", folded) is not None

        if has_all_token and has_plural_alarm and day_period is None:
            # Suppression en masse demandée en langage naturel : Jarvis demande confirmation.
            return {"action": "delete_alarms_all", "params": {"confirm": True}}

        if day_period is not None:
            start, end = day_period
            return {
                "action": "delete_alarms_range",
                "params": {
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                },
            }

        # Identifiant hexadécimal court (au moins un chiffre, pour ne pas le confondre avec un mot).
        alarm_id_match = re.search(r"\b(?=[a-f0-9]*\d)[a-f0-9]{4,8}\b", folded)
        if alarm_id_match:
            return {
                "action": "delete_alarm",
                "params": {"alarm_id": alarm_id_match.group(0)},
            }

        return {
            "action": "command_error",
            "message": (
                f"Laquelle, {TITLE} ? Précisez l'identifiant, la journée ou la période. "
                "Par exemple : supprime l'alarme abcd1234, supprime les alarmes de demain, "
                "supprime toutes mes alarmes."
            ),
        }

    if not is_create:
        return None

    default_title = "Réveil" if wake_me or re.search(r"\breveils?\b", folded) else "Alarme"

    recurring = recurring_alarm(text, _extract_alarm_title(text, default=default_title))
    if recurring is not None:
        return recurring

    when = parse_datetime_expression(text)
    if when is None:
        return {
            "action": "command_error",
            "message": f"Pour quelle heure, {TITLE} ? Par exemple : mets une alarme demain à 7 h 30.",
        }

    return {
        "action": "set_alarm",
        "params": {
            "when": when.isoformat(),
            "title": _extract_alarm_title(text, default=default_title),
            "kind": "alarm",
        },
    }


def parse_snooze(text: str) -> dict | None:
    """« Encore 5 minutes », « snooze », « laisse-moi dormir ».»"""
    folded = fold(text).strip(" .!?")
    if not re.match(r"^(?:encore|snooze|repete|repousse|laisse[- ]moi (?:encore )?dormir)\b", folded):
        return None
    if not (re.search(r"minute|alarme|reveil|dormir|snooze", folded) or folded in {"encore", "repete"}):
        return None
    delay = extract_relative_delay(text)
    minutes = max(1, round(delay.total_seconds() / 60)) if delay else 5
    return {"action": "snooze_alarm", "params": {"minutes": minutes}}


def recurring_alarm(text: str, title: str) -> dict | None:
    """Une alarme qui revient : « réveille-moi tous les jours de semaine à 7h »."""
    repeat = extract_repeat(fold(text))
    if repeat is None:
        return None
    if repeat["alarm"] == "weekly":
        when = parse_datetime_expression(text)
        if when is None:
            return None
        repeat = {**repeat, "alarm": f"weekly:{when.weekday()}"}
    else:
        when = first_occurrence(text, repeat)
    if when is None:
        return {"action": "command_error", "message": f"À quelle heure, {TITLE} ? Par exemple : réveille-moi tous les jours à 7 h."}
    return {"action": "set_alarm", "params": {"when": when.isoformat(), "title": title, "kind": "alarm", "repeat": repeat["alarm"]}}
