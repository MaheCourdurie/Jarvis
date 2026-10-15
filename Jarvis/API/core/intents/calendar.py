"""Agent agenda : créer, lister, supprimer et déplacer des événements."""

from __future__ import annotations

import re
from datetime import timedelta

from config import local_now
from persona import TITLE, fold
from core.intents.common import (
    DAY,
    capitalize,
    clean_fragment,
    clean_name,
    extract_day_period_bounds,
    extract_duration_minutes,
    extract_repeat,
    first_occurrence,
    normalize_spoken_time,
    parse_datetime_expression,
    strip_time_expressions,
)


EVENT_LABELS = {
    "reunion": "Réunion",
    "rdv": "Rendez-vous",
    "rendez-vous": "Rendez-vous",
    "meeting": "Meeting",
    "dejeuner": "Déjeuner",
    "diner": "Dîner",
    "appel": "Appel",
    "call": "Call",
    "visio": "Visio",
    "entretien": "Entretien",
    "seance": "Séance",
    "cours": "Cours",
}
_EVENT_NOUN = re.compile(r"\b(" + "|".join(re.escape(key) for key in EVENT_LABELS) + r")\b")


def _event_title(text: str, folded: str) -> str:
    """Déduit le titre d'un événement : guillemets, « pour … », puis « <type> avec <personne> »."""
    quoted = re.findall(r'"([^\"]+)"', text)
    if quoted and quoted[-1].strip():
        return quoted[-1].strip()

    noun = _EVENT_NOUN.search(folded)
    base = EVENT_LABELS[noun.group(1)] if noun else ""

    subject_match = re.search(r"\b(?:pour|concernant|au sujet de)\b\s+(.+)$", text, flags=re.IGNORECASE)
    if subject_match:
        subject = clean_fragment(strip_time_expressions(subject_match.group(1)))
        if len(subject) >= 2:
            return capitalize(subject)

    # « Note dans mon agenda : match de foot samedi à 14h »
    colon_match = re.search(r":\s*(.+)$", text)
    if colon_match:
        subject = clean_fragment(strip_time_expressions(colon_match.group(1)))
        if len(subject) >= 2:
            return capitalize(subject)

    with_match = re.search(r"\bavec\s+(.+)$", text, flags=re.IGNORECASE)
    if with_match:
        person = clean_fragment(strip_time_expressions(with_match.group(1)))
        person = re.split(r"\s+(?:de|du|pour|pendant|durant)\s+\d", person)[0].strip()
        if len(person) >= 2:
            return f"{base or 'Rendez-vous'} avec {person}"

    # « rendez-vous chez le dentiste demain à 15h »
    at_match = re.search(r"\bchez\s+(.+)$", text, flags=re.IGNORECASE)
    if at_match:
        place = clean_fragment(strip_time_expressions(at_match.group(1)))
        if len(place) >= 2:
            return f"{base or 'Rendez-vous'} chez {place}"

    return base or "Événement"


def parse_calendar(text: str) -> dict | None:
    """Interprète une demande naturelle liée au calendrier (création/liste/suppression)."""
    text = normalize_spoken_time(text)
    lowered = text.lower()
    folded = fold(text)

    delete_verbs = ["supprime", "annule", "efface", "retire"]
    event_terms = [
        "evenement",
        "événement",
        "rdv",
        "rendez",
        "reunion",
        "réunion",
        "meeting",
        "agenda",
        "creneau",
        "créneau",
        "bloc",
    ]
    has_event_noun = _EVENT_NOUN.search(folded) is not None

    if any(token in lowered for token in delete_verbs) and (any(token in lowered for token in event_terms) or has_event_noun):
        quoted = re.findall(r'"([^\"]+)"', text)
        event_id = quoted[0].strip() if quoted else ""
        if not event_id:
            id_match = re.search(r"\bid\b\s*[:=]?\s*([A-Za-z0-9_@.\-]{4,})\b", text, flags=re.IGNORECASE)
            if id_match:
                event_id = id_match.group(1).strip()

        if event_id:
            return {
                "action": "delete_event",
                "params": {"event_id": event_id},
            }

        day_period = extract_day_period_bounds(text)
        if day_period is not None:
            start, end = day_period
            return {
                "action": "delete_events_range",
                "params": {
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    # Suppression en masse demandée en langage naturel : Jarvis demande confirmation.
                    "confirm": True,
                },
            }

        return {
            "action": "command_error",
            "message": (
                f"Lequel, {TITLE} ? Précisez l'identifiant, la journée ou la période. "
                "Par exemple : supprime les événements de demain, "
                "ou supprime les événements du 2026-04-10 au 2026-04-12."
            ),
        }

    create_verbs = [
        "cree", "crée", "ajoute", "rajoute", "programme", "planifie", "planifier", "bloque", "bloquer", "organise", "cale",
        "mets", "met", "note", "noter", "inscris", "inscrire", "prevois", "prévois", "fixe", "reserve", "réserve",
    ]

    has_create = any(re.search(rf"\b{verb}\b", lowered) for verb in create_verbs)
    has_event_term = any(token in lowered for token in event_terms) or has_event_noun
    has_block_verb = any(token in lowered for token in ["bloque", "bloquer"])

    if has_create and (has_event_term or has_block_verb):

        repeat = extract_repeat(folded)
        start = parse_datetime_expression(text)
        if repeat is not None and repeat["alarm"] != "weekly":
            start = first_occurrence(text, repeat) or start
        if start is None:
            return {
                "action": "command_error",
                "message": f"Pour quand, {TITLE} ? Par exemple : crée un événement lundi prochain à 10 h.",
            }

        end = None

        m = re.search(
            r"\bde\s*(\d{1,2})\s*(?:h|:)?\s*(\d{2})?\s*(?:a|à|-|jusqu(?:'|’)a)\s*(\d{1,2})\s*(?:h|:)?\s*(\d{2})?\b",
            lowered,
        )
        if m:
            start = start.replace(hour=int(m.group(1)), minute=int(m.group(2) or "0"), second=0, microsecond=0)
            end_hour = int(m.group(3))
            end_min = int(m.group(4) or "0")
            end = start.replace(hour=end_hour, minute=end_min, second=0, microsecond=0)
            if end <= start:
                end += timedelta(days=1)

        if end is None:
            duration_minutes = extract_duration_minutes(text)
            if duration_minutes is not None:
                end = start + timedelta(minutes=duration_minutes)

        if end is None:
            end = start + timedelta(hours=1)

        params = {"title": _event_title(text, folded), "start": start.isoformat(), "end": end.isoformat()}
        if repeat is not None:
            params["recurrence"] = repeat["rrule"]
            params["rhythm"] = repeat["label"]
        return {"action": "add_event", "params": params}

    time_tokens = ["semaine", "aujourd", "demain", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

    if any(token in lowered for token in ["disponib", "libre"]) and any(token in lowered for token in time_tokens):
        return {"action": "availability_week"}

    list_terms = [
        "planning",
        "agenda",
        "reunion",
        "réunion",
        "rdv",
        "rendez",
        "meeting",
        "evenement",
        "événement",
        "evenements",
        "événements",
    ]

    if any(token in lowered for token in list_terms):
        day_period = extract_day_period_bounds(text)
        if day_period is not None and "semaine" not in lowered:
            start, end = day_period
            return {
                "action": "events_range",
                "params": {
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                },
            }

        if any(token in lowered for token in time_tokens):
            return {"action": "events_week"}

        if any(token in lowered for token in ["quel", "quels", "quoi", "liste", "montre", "affiche"]):
            return {"action": "events_week"}

    # « Qu'est-ce que j'ai de prévu demain ? », « j'ai quoi aujourd'hui ? », « mon programme demain »
    if re.search(
        r"\bde prevu\b|\bau programme\b|\bj'ai quoi\b|\bqu'est-ce que j'ai\b|\bqu'ai-je\b|\bmon programme\b"
        r"|\bemploi du temps\b|\bj'ai (?:quelque chose|un truc|des trucs)\b|\b(?:suis[- ]je|je suis) (?:pris|occupe|dispo)\b",
        folded,
    ):
        if "semaine" in folded:
            return {"action": "events_week"}
        day_period = extract_day_period_bounds(text)
        if day_period is None:
            today = local_now().replace(hour=0, minute=0, second=0, microsecond=0)
            day_period = (today, today + timedelta(days=1))
        start, end = day_period
        return {"action": "events_range", "params": {"start": start.isoformat(), "end": end.isoformat()}}

    return None


def parse_move_event(text: str) -> dict | None:
    """« Décale le dentiste à 16h », « déplace la réunion de demain à jeudi 10h »."""
    clean = normalize_spoken_time(text.strip().replace("’", "'").rstrip(" .!?"))
    match = re.match(
        r"^(?:d[ée]cale|d[ée]place|repousse|avance|reporte|change l'heure d[ue])\s+(?:le |la |l'|mon |ma |mes |les )?"
        r"(?P<what>.+?)\s+(?:à|a|au|pour|vers|jusqu'à)\s+(?P<target>[^,]+)$",
        clean, flags=re.IGNORECASE,
    )
    if not match:
        return None
    what = match["what"]
    if re.search(r"\b(?:alarme|r[ée]veil|minuteur|rappel)\b", fold(what)):
        return None
    day = extract_day_period_bounds(what)
    query = re.sub(rf"\s+(?:de|du|d')\s*(?:demain|aujourd'hui|ce (?:matin|soir)|{DAY}(?: prochain)?)\b.*$", "", what, flags=re.IGNORECASE)
    target_text = match["target"]
    target = parse_datetime_expression(target_text)
    if target is None:
        return {"action": "command_error", "message": f"À quel moment dois-je le déplacer, {TITLE} ? Par exemple : décale le dentiste à 16 h."}
    time_only = not re.search(rf"\b(?:demain|apr[eè]s-demain|{DAY}|\d{{1,2}}/\d{{1,2}}|\d{{4}}-\d{{2}})", fold(target_text))
    params = {"query": clean_name(query), "target": target.isoformat(), "time_only": time_only}
    if day is not None:
        params["from"], params["to"] = day[0].isoformat(), day[1].isoformat()
    return {"action": "move_event", "params": params}
