"""Agent routines : créer, lister, lancer une routine."""

from __future__ import annotations

import re

from persona import fold
from core.intents.common import apply_day_period, clean_name, extract_repeat, extract_time_of_day, normalize_spoken_time


def parse_routines(text: str) -> dict | None:
    clean = text.strip().rstrip(" .!?")
    folded = fold(clean)
    create = re.match(r"^(?:cr[ée]e|ajoute|enregistre|nouvelle)\s+(?:une |la |ma )?routine\s+(?P<name>[^:]+?)\s*:\s*(?P<steps>.+)$", clean, flags=re.IGNORECASE)
    if create:
        return {"action": "create_routine", "params": {"name": clean_name(create["name"]), "steps": create["steps"]}}
    scheduled = parse_scheduled_routine(clean, folded)
    if scheduled is not None:
        return scheduled
    if re.search(r"\b(?:quelles sont|liste|montre(?:-moi)?) (?:mes |les )routines\b", folded):
        return {"action": "list_routines"}
    run = re.match(r"^(?:lance|active|demarre|execute|passe en|on passe en)?\s*(?:la routine|ma routine|le mode|mode)\s+(?P<name>[\w' -]+)$", folded)
    if run:
        return {"action": "run_routine", "params": {"name": run["name"].strip()}}
    return None


def parse_scheduled_routine(clean: str, folded: str) -> dict | None:
    """« Lance la routine bonne nuit tous les soirs à 22h », « n'exécute plus le mode travail automatiquement »."""
    named = re.search(r"\b(?:la routine|ma routine|le mode|mode)\s+(?P<name>[\w' -]+?)(?=\s+(?:tous|toutes|chaque|en semaine|du lundi|a \d|a midi|automatiquement)\b|$)", folded)
    if not named:
        return None
    if re.search(r"\b(?:ne (?:lance|declenche|execute)|n'execute|arrete de lancer|annule|supprime|desactive)\b.*\b(?:plus|programm|automatique|tous les|chaque)", folded) or re.search(r"\bplus automatiquement\b", folded):
        return {"action": "unschedule_routine", "params": {"name": named["name"].strip()}}
    repeat = extract_repeat(folded)
    if repeat is None:
        return None
    normalized = normalize_spoken_time(clean)
    clock = extract_time_of_day(normalized.lower())
    if clock is None:
        return {"action": "schedule_routine", "params": {"name": named["name"].strip(), "repeat": repeat["alarm"], "time": ""}}
    hour = apply_day_period(clock[0], fold(normalized))
    if re.search(r"\btous les soirs\b|\bchaque soir\b", folded) and hour < 12:
        hour += 12
    return {
        "action": "schedule_routine",
        "params": {"name": named["name"].strip(), "repeat": repeat["alarm"], "time": f"{hour:02d}:{clock[1]:02d}"},
    }
