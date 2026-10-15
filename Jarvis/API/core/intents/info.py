"""Agent informations : heure, date, météo, soleil, qualité de l'air, briefing."""

from __future__ import annotations

import re

from config import local_now
from persona import fold
from core.intents.common import WEEKDAY_INDEX


_NOT_A_CITY = {"demain", "aujourd'hui", "maintenant", "moment", "semaine", "matin", "soir", "midi", "jarvis"}


_TIME_WORDS = re.compile(
    r"\b(?:semaine|week-?end|jours?|matin|soir|apres-midi|nuit|demain|apres-demain|aujourd'hui|maintenant"
    r"|lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|prochains?)\b"
)


def _extract_city(text: str) -> str | None:
    """Repère une ville dans une demande météo (« à Lyon », « sur New York », « météo Bordeaux »)."""
    city = _extract_city_candidate(text)
    if city and _TIME_WORDS.search(fold(city)):
        return None
    return city


def _extract_city_candidate(text: str) -> str | None:
    match = re.search(
        r"(?:\b(?:a|sur|pour|de)|à)\s+((?:[A-ZÀ-Ý][\wà-ÿ'’-]+)(?:[ -][A-ZÀ-Ý][\wà-ÿ'’-]+)*)",
        text,
    )
    if match and fold(match.group(1)) not in _NOT_A_CITY:
        return match.group(1)

    match = re.search(r"\bm[ée]t[ée]o\s+(?:(?:a|à|de|sur|pour)\s+)?([a-zà-ÿ][\wà-ÿ' -]{1,30})$", text.strip(" ?!."), flags=re.IGNORECASE)
    if match:
        candidate = re.sub(r"\b(?:de\s+)?(?:demain|aujourd'hui|maintenant)\b", "", match.group(1), flags=re.IGNORECASE).strip(" '-")
        if len(candidate) >= 2 and fold(candidate) not in _NOT_A_CITY and not fold(candidate).startswith(("du ", "de ", "pour ")):
            return candidate.title()
    return None


def parse_info(text: str) -> dict | None:
    """Interprète les demandes d'information : heure, date, météo, briefing."""
    folded = fold(text)

    if re.search(
        r"(?<!a )quelle heure (?:est[- ]il|il est|on a)\b|\bil est quelle heure\b|\b(?:donne|dis)[- ]moi l'heure\b"
        r"|\b(?:tu as|t'as|vous avez|as[- ]tu|avez[- ]vous) l'heure\b|^l'heure\b",
        folded,
    ):
        return {"action": "time"}

    if re.search(
        r"\bquel jour (?:sommes|est[- ]on|on est|est[- ]ce)|\bon est quel jour\b|\bquelle est la date\b"
        r"|\bla date d'aujourd'hui\b|\bon est le combien\b|\bnous sommes le combien\b|\bquelle date\b",
        folded,
    ):
        return {"action": "date"}

    if re.search(
        r"\bmeteo\b|\bquel temps\b|\btemps qu'il (?:fait|fera)\b"
        r"|\bil fait (?:combien|quelle temperature|beau|froid|chaud)\b|\btemperature (?:exterieure|dehors|qu'il fait)\b"
        r"|\bva[- ]t[- ]il pleuvoir\b|\best[- ]ce qu'il (?:va pleuvoir|pleut|pleuvra)\b|\bil pleut\b"
        r"|\bbesoin d'un parapluie\b|\bprevisions\b|\bparapluie\b|\bquelle temperature\b"
        r"|\b(?:il )?va[- ](?:t[- ]il[- ])?(?:pleuvoir|neiger|faire (?:beau|froid|chaud))\b|\bpleuvoir\b|\bneiger?\b"
        r"|\bfera[- ]t[- ]il (?:beau|froid|chaud)\b|\bil fera (?:beau|froid|chaud|mauvais|combien)\b",
        folded,
    ):

        return {"action": "weather", "params": {"city": _extract_city(text), "day": weather_day(folded)}}

    if re.search(
        r"\bbriefing\b|\bfai(?:s|tes)[- ](?:moi )?(?:le|un) point\b|\bpoint sur (?:la|ma) journee\b"
        r"|\brapport du (?:jour|matin)\b|\bprogramme (?:du jour|de la journee)\b|\bresume de (?:la|ma) journee\b",
        folded,
    ):
        return {"action": "briefing"}

    return None


def weather_day(folded: str):
    """Le jour demandé pour la météo : today, tomorrow, weekend, week, ou un décalage en jours."""
    if re.search(r"\bweek-?end\b", folded):
        return "weekend"
    if re.search(r"\b(?:cette|la|de la|sur la) semaine\b|\bprochains jours\b|\b7 jours\b|\bjours qui viennent\b|\bsemaine prochaine\b", folded):
        return "week"
    if re.search(r"\bapres-demain\b", folded):
        return 2
    later = re.search(r"\bdans (\d) jours\b", folded)
    if later:
        return int(later.group(1))
    if re.search(r"\bdemain\b", folded):
        return "tomorrow"
    for name, index in WEEKDAY_INDEX.items():
        if re.search(rf"\b{name}\b", folded):
            offset = (index - local_now().weekday()) % 7
            return {0: "today", 1: "tomorrow"}.get(offset, offset)
    return "today"


def parse_sky(text: str) -> dict | None:
    folded = fold(text)
    if re.search(r"\b(?:lever|coucher) du soleil\b|\bsoleil se (?:leve|couche)\b|\bse (?:leve|couche) le soleil\b|\bfait nuit\b", folded):
        return {"action": "sun", "params": {"day": "tomorrow" if "demain" in folded else "today"}}
    if re.search(r"\bqualite de l'air\b|\bpollution\b|\bl'air est (?:pollue|bon)\b", folded):
        return {"action": "air_quality", "params": {}}
    return None
