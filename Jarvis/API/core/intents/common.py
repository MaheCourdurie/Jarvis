"""Outils partagés par tous les fichiers de phrases : dates et heures dites, durées, récurrences, nettoyage."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from config import local_now
from persona import fold


WEEKDAY_INDEX = {
    "lundi": 0,
    "mardi": 1,
    "mercredi": 2,
    "jeudi": 3,
    "vendredi": 4,
    "samedi": 5,
    "dimanche": 6,
}
NUMBER_WORDS = {
    "un": 1,
    "une": 1,
    "deux": 2,
    "trois": 3,
    "quatre": 4,
    "cinq": 5,
    "six": 6,
    "sept": 7,
    "huit": 8,
    "neuf": 9,
    "dix": 10,
    "quinze": 15,
    "vingt": 20,
    "trente": 30,
    "quarante-cinq": 45,
}


def _number_spellings() -> dict[str, int]:
    """Les nombres de 0 à 100 tels qu'on les écrit en lettres (« vingt et un », « quatre-vingt-dix »)."""
    units = [
        "zero", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix",
        "onze", "douze", "treize", "quatorze", "quinze", "seize",
    ]
    names = {word: value for value, word in enumerate(units)}
    names.update({"une": 1, "zéro": 0, "dix-sept": 17, "dix-huit": 18, "dix-neuf": 19, "cent": 100})
    tens = {20: "vingt", 30: "trente", 40: "quarante", 50: "cinquante", 60: "soixante"}
    for base, word in tens.items():
        names[word] = base
        for unit in range(1, 10):
            names[f"{word}-et-un" if unit == 1 else f"{word}-{units[unit]}"] = base + unit
    for unit in range(10, 20):  # soixante-dix à soixante-dix-neuf, quatre-vingt-dix…
        spelled = units[unit] if unit <= 16 else f"dix-{units[unit - 10]}"
        names["soixante-et-onze" if unit == 11 else f"soixante-{spelled}"] = 60 + unit
        names[f"quatre-vingt-{spelled}"] = 80 + unit
    names["quatre-vingts"] = names["quatre-vingt"] = 80
    for unit in range(1, 10):
        names[f"quatre-vingt-{units[unit]}"] = 80 + unit
    names.update({word + "e": value for word, value in list(names.items()) if word.endswith("-et-un")})  # « vingt et une heures »
    spellings = {}
    for word, value in names.items():
        for variant in {word, word.replace("-", " "), word.replace("-et-", " et ")}:
            spellings[variant] = value
    return spellings


NUMBER_SPELLINGS = _number_spellings()
_NUMBER = r"(?:" + "|".join(re.escape(word) for word in sorted(NUMBER_SPELLINGS, key=len, reverse=True)) + r")"
_UNIT_AFTER = r"(?=\s*(?:heures?|h\b|minutes?\b|mn\b|min\b|secondes?\b|sec\b|jours?\b|pour ?cent\b|%))"


def spoken_numbers(text: str) -> str:
    """Les nombres dits en lettres devant une unité passent en chiffres (« sept heures trente » → « 7 heures 30 »).

    Seuls les nombres qui comptent (heures, minutes, durées, pourcentages, réglages) sont convertis :
    « la réunion des deux équipes » reste telle quelle.
    """
    def digits(match: re.Match) -> str:
        return str(NUMBER_SPELLINGS[match.group(0).lower()])

    converted = re.sub(rf"(?<![\w-]){_NUMBER}(?![\w-]){_UNIT_AFTER}", digits, text, flags=re.IGNORECASE)
    # Les minutes après l'heure : « 7 heures trente », « 7h quinze ».
    converted = re.sub(
        rf"(\d\s*(?:heures?|h))\s+({_NUMBER})(?![\w-])",
        lambda m: f"{m.group(1)} {NUMBER_SPELLINGS[m.group(2).lower()]}",
        converted, flags=re.IGNORECASE,
    )
    # Un réglage : « le son à cinquante », « luminosité à trente ».
    converted = re.sub(
        rf"(\b(?:son|volume|luminosit[ée])\s+(?:a|à|au|sur)\s+)({_NUMBER})(?![\w-])",
        lambda m: f"{m.group(1)}{NUMBER_SPELLINGS[m.group(2).lower()]}",
        converted, flags=re.IGNORECASE,
    )
    return converted


def normalize_spoken_time(text: str) -> str:
    """Ramène les heures dictées à la forme 7h30 (« 7 heures et demie », « midi », « sept heures »)."""
    normalized = spoken_numbers(text.replace("’", "'"))

    def quarter_to(match: re.Match) -> str:
        return f"{(int(match.group(1)) - 1) % 24}h45"

    normalized = re.sub(r"\b(\d{1,2})\s*(?:h|heures?)\s+moins\s+le\s+quart\b", quarter_to, normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\b(\d{1,2})\s*(?:h|heures?)\s+et\s+demie?\b", r"\1h30", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\b(\d{1,2})\s*(?:h|heures?)\s+et\s+quart\b", r"\1h15", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\b(\d{1,2})\s*heures?\s*(\d{1,2})\b", lambda m: f"{m.group(1)}h{int(m.group(2)):02d}", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\b(\d{1,2})\s*heures?\b", r"\1h", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(?<![\w-])midi\b", "12h", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bminuit\b", "0h", normalized, flags=re.IGNORECASE)
    return normalized


def extract_relative_delay(text: str) -> timedelta | None:
    """Extrait une durée (« 10 minutes », « une demi-heure », « 1h30 », « 45 secondes »)."""
    folded = fold(spoken_numbers(text))
    for word, value in NUMBER_WORDS.items():
        folded = re.sub(rf"\b{word}\s+(?=minutes?\b|heures?\b|secondes?\b)", f"{value} ", folded)

    if re.search(r"\bdemi[- ]heure\b", folded):
        return timedelta(minutes=30)
    if re.search(r"\bquart d'heure\b", folded):
        match = re.search(r"\b(\d+)\s+quarts? d'heure", folded)
        return timedelta(minutes=15 * (int(match.group(1)) if match else 1))

    match = re.search(r"\b(\d+)\s*(?:h|heures?)\s*(\d{1,2})?\b(?!\s*\d)", folded)
    if match:
        return timedelta(hours=int(match.group(1)), minutes=int(match.group(2) or 0))
    match = re.search(r"\b(\d+)\s*(?:minutes?|min|mn)\b", folded)
    if match:
        delay = timedelta(minutes=int(match.group(1)))
        seconds = re.search(r"\b(\d+)\s*(?:secondes?|sec)\b", folded)
        return delay + timedelta(seconds=int(seconds.group(1))) if seconds else delay
    match = re.search(r"\b(\d+)\s*(?:secondes?|sec)\b", folded)
    if match:
        return timedelta(seconds=int(match.group(1)))
    return None


def parse_datetime(value: str) -> datetime:
    """Convertit une date saisie en objet datetime ISO."""
    normalized = value.strip().replace("/", "-")
    if "T" not in normalized and " " in normalized:
        normalized = normalized.replace(" ", "T")
    return datetime.fromisoformat(normalized)


def extract_time_of_day(text: str) -> tuple[int, int] | None:
    """Extrait une heure/minute depuis une expression libre (10h, 10:30...)."""
    m = re.search(r"\b(\d{1,2})\s*(?::|h)\s*(\d{2})\b", text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute

    m = re.search(r"\b(\d{1,2})\s*h\b", text)
    if m:
        hour = int(m.group(1))
        if 0 <= hour <= 23:
            return hour, 0

    return None


def apply_day_period(hour: int, lowered: str) -> int:
    """Passe en heure de l'après-midi/du soir quand la phrase le précise (« 8h ce soir » → 20h)."""
    if 1 <= hour <= 11 and re.search(r"\bsoir\b", lowered):
        return hour + 12
    if 1 <= hour <= 6 and re.search(r"\bapr[eè]s-midi\b", lowered):
        return hour + 12
    return hour


def parse_datetime_expression(text: str) -> datetime | None:
    """Interprète une date/heure naturelle en français (demain, lundi, dans 2h...)."""
    now = local_now()
    text = normalize_spoken_time(text)

    # Formats absolus ISO: YYYY-MM-DD HH:MM
    m = re.search(r"(\d{4}-\d{2}-\d{2})[ T](\d{1,2})(?::(\d{2}))?", text)
    if m:
        try:
            minute = int(m.group(3) or "0")
            return datetime.fromisoformat(f"{m.group(1)}T{int(m.group(2)):02d}:{minute:02d}")
        except ValueError:
            return None

    # Formats absolus FR: DD/MM/YYYY HH:MM
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})[ T](\d{1,2})(?::(\d{2}))?", text)
    if m:
        day, month, year, hour, minute = m.groups()
        try:
            return datetime.fromisoformat(
                f"{int(year):04d}-{int(month):02d}-{int(day):02d}T{int(hour):02d}:{int(minute or '0'):02d}"
            )
        except ValueError:
            return None

    lowered = text.lower().replace("à", "a").replace("’", "'")

    # Jour de la semaine: "lundi prochain a 10h", "mardi apres-midi"
    m = re.search(
        r"\b(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\b"
        r"(?:\s+(prochain|prochaine))?"
        r"(?:\s+(matin|apres-midi|après-midi|soir))?"
        r"(?:\s*(?:a)?\s*(\d{1,2})(?:(?:[:h])(\d{2}))?)?",
        lowered,
    )
    if m:
        weekday_name, _, period, hour_raw, minute_raw = m.groups()
        target_weekday = WEEKDAY_INDEX[weekday_name]
        delta = (target_weekday - now.weekday()) % 7
        if delta == 0:
            delta = 7

        if hour_raw is not None:
            hour = int(hour_raw)
            minute = int(minute_raw or "0")
        elif period in {"apres-midi", "après-midi"}:
            hour, minute = 14, 0
        elif period == "soir":
            hour, minute = 18, 0
        else:
            hour, minute = 9, 0

        base = now + timedelta(days=delta)
        return base.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # Relatif: "dans 45 minutes", "dans 2 heures", "dans une demi-heure"
    m = re.search(r"\bdans\s+(.{1,40})", lowered)
    if m:
        delay = extract_relative_delay(m.group(1))
        if delay is not None:
            return now + delay

    # Aujourd'hui / demain (mots-clés avec heure placée avant ou après)
    has_today = re.search(r"\b(?:aujourd'hui|aujourdhui|ajd|ce soir|ce matin|cet apr[eè]s-midi)\b", lowered) is not None
    has_tomorrow = re.search(r"\bdemain\b", lowered) is not None
    if has_today or has_tomorrow:
        extracted = extract_time_of_day(lowered)
        if extracted is None:
            # "demain matin", "ce soir" : pas d'heure précise, on prend celle du moment de la journée.
            if re.search(r"\bmatin\b", lowered):
                extracted = (9, 0)
            elif re.search(r"\bapr[eè]s-midi\b", lowered):
                extracted = (14, 0)
            elif re.search(r"\bsoir\b", lowered):
                extracted = (19, 0)
        if extracted is not None:
            hour, minute = apply_day_period(extracted[0], lowered), extracted[1]
            if has_today:
                # Quand l'utilisateur dit explicitement "aujourd'hui", on respecte le jour demandé.
                base = now
            else:
                base = now + timedelta(days=1)
            return base.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # Heure avec préposition: "a 15h", "pour 16:30", "vers 9h"
    m = re.search(r"\b(?:a|pour|vers)\s*(\d{1,2})(?:(?:[:h])(\d{2}))?\b", lowered)
    if m:
        hour = apply_day_period(int(m.group(1)), lowered)
        minute = int(m.group(2) or "0")
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target < now:
                target += timedelta(days=1)
            return target

    # Heure seule: "16h40", "16:30" -> aujourd'hui ou demain si déjà passé
    extracted = extract_time_of_day(lowered)
    if extracted is not None:
        hour, minute = apply_day_period(extracted[0], lowered), extracted[1]
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target < now:
            target += timedelta(days=1)
        return target

    return None


def parse_day_value(value: str, now: datetime | None = None) -> datetime | None:
    """Transforme un jour (ISO/FR/relatif) en datetime au début de journée."""
    base_now = now or local_now()
    lowered = value.strip().lower().replace("’", "'").replace("à", "a")

    iso_match = re.fullmatch(r"\d{4}-\d{2}-\d{2}", lowered)
    if iso_match:
        try:
            parsed = datetime.fromisoformat(lowered)
            return parsed.replace(hour=0, minute=0, second=0, microsecond=0)
        except ValueError:
            return None

    fr_match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", lowered)
    if fr_match:
        day, month, year = fr_match.groups()
        try:
            parsed = datetime.fromisoformat(f"{int(year):04d}-{int(month):02d}-{int(day):02d}")
            return parsed.replace(hour=0, minute=0, second=0, microsecond=0)
        except ValueError:
            return None

    if re.search(r"\b(?:aujourd'hui|aujourdhui|ajd)\b", lowered):
        return base_now.replace(hour=0, minute=0, second=0, microsecond=0)

    if re.search(r"\bdemain\b", lowered):
        return (base_now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    weekday_match = re.fullmatch(r"(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)(?:\s+(prochain|prochaine))?", lowered)
    if weekday_match:
        weekday_name, qualifier = weekday_match.groups()
        target_weekday = WEEKDAY_INDEX[weekday_name]
        delta = (target_weekday - base_now.weekday()) % 7
        if delta == 0 and qualifier:
            delta = 7
        target = base_now + timedelta(days=delta)
        return target.replace(hour=0, minute=0, second=0, microsecond=0)

    return None


def extract_day_period_bounds(text: str) -> tuple[datetime, datetime] | None:
    """Déduit les bornes (début, fin) d'une journée ou d'une période mentionnée."""
    lowered = text.lower().replace("’", "'")
    now = local_now()

    if "cette semaine" in lowered:
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=7)

    date_tokens: list[str] = []
    date_tokens.extend(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", lowered))
    date_tokens.extend(re.findall(r"\b\d{1,2}/\d{1,2}/\d{4}\b", lowered))

    if re.search(r"\b(?:aujourd'hui|aujourdhui|ajd)\b", lowered):
        date_tokens.append("aujourd'hui")
    if re.search(r"\bdemain\b", lowered):
        date_tokens.append("demain")

    weekday_matches = re.findall(
        r"\b(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)(?:\s+(prochain|prochaine))?\b",
        lowered,
    )
    for weekday_name, qualifier in weekday_matches:
        token = f"{weekday_name} {qualifier}".strip()
        date_tokens.append(token)

    parsed_days: list[datetime] = []
    for token in date_tokens:
        parsed = parse_day_value(token, now=now)
        if parsed is not None:
            parsed_days.append(parsed)

    if not parsed_days:
        return None

    has_range_hint = any(marker in lowered for marker in [" du ", " entre ", " au ", " et ", "jusqu"])

    start_day = parsed_days[0]
    end_day = parsed_days[0]

    if has_range_hint and len(parsed_days) >= 2:
        end_day = parsed_days[1]
        if end_day < start_day:
            start_day, end_day = end_day, start_day

    start = start_day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = end_day.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return start, end


def extract_duration_minutes(text: str) -> int | None:
    """Extrait une durée exprimée en heures/minutes et la convertit en minutes."""
    lowered = text.lower().replace("à", "a")

    m = re.search(r"\b(?:bloque|bloquer|pendant|durant|pour)\s+(\d+)\s*(heure|heures|h)\b", lowered)
    if m:
        return int(m.group(1)) * 60

    m = re.search(r"\b(?:bloque|bloquer|pendant|durant|pour)\s+(\d+)\s*(minute|min|minutes)\b", lowered)
    if m:
        return int(m.group(1))

    return None


def clean_fragment(value: str) -> str:
    """Nettoie un fragment texte en retirant guillemets et ponctuation superflue."""
    return value.strip().strip("\"'` ").strip(" .,;:!?\t\n\r")


_TIME_FRAGMENTS = [
    re.compile(
        r"\bdans\s+(?:\d+|une?|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|quinze|vingt|trente)\s*"
        r"(?:minutes?|min|mn|heures?|h|secondes?|sec)\b(?:\s*\d{1,2}\b)?",
        flags=re.IGNORECASE,
    ),
    re.compile(r"\bdans\s+(?:une?\s+)?(?:demi[- ]heure|quart d'heure)\b", flags=re.IGNORECASE),
    re.compile(r"(?:\b(?:a|vers|pour)|à)\s*\d{1,2}\s*(?:h|:)\s*\d{0,2}\b", flags=re.IGNORECASE),
    re.compile(r"\b\d{1,2}\s*h\s*\d{0,2}\b", flags=re.IGNORECASE),
    re.compile(
        r"\b(?:demain|aujourd'hui|aujourdhui|ce soir|ce matin|cet apr[eè]s-midi)\b(?:\s+(?:matin|soir|apr[eè]s-midi))?",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\b(?:\s+prochaine?)?(?:\s+(?:matin|soir|apr[eè]s-midi))?",
        flags=re.IGNORECASE,
    ),
]


def strip_time_expressions(text: str) -> str:
    """Retire les indications de date et d'heure d'une phrase pour n'en garder que le sujet."""
    cleaned = normalize_spoken_time(text)
    for pattern in _TIME_FRAGMENTS:
        cleaned = pattern.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" ,.;:!?-")


def capitalize(value: str) -> str:
    return value[:1].upper() + value[1:] if value else value


WEEKDAY_CODES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
DAY = r"(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)"


ARTICLES = re.compile(r"^(?:du|de la|de l'|des|un|une|le|la|les|l'|d')\s*", re.IGNORECASE)


def clean_name(value: str) -> str:
    return value.strip().strip(" .!?,;:«»\"'")


# ── Récurrence (alarmes et agenda) ─────────────────────────────────────────

def extract_repeat(folded: str) -> dict | None:
    """« tous les jours », « en semaine », « tous les mardis et jeudis » → codes alarme et agenda."""
    # « tous les jours de semaine » avant « tous les jours ».
    if re.search(r"\ben semaine\b|\bdu lundi au vendredi\b|\bjours? (?:de (?:la )?semaine|ouvres?)\b", folded):
        return {"alarm": "weekdays", "rrule": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", "label": "du lundi au vendredi"}
    if re.search(r"\btous les (?:jours|soirs|matins)\b|\bchaque (?:jour|soir|matin)\b|\bquotidien", folded):
        return {"alarm": "daily", "rrule": "FREQ=DAILY", "label": "tous les jours"}
    days_match = re.search(rf"\b(?:tous les|chaque)\s+({DAY}s?(?:\s*(?:,|et)\s*{DAY}s?)*)", folded)
    if days_match:
        days = sorted({WEEKDAY_INDEX[name] for name in re.findall(DAY, days_match.group(1))})
        names = [list(WEEKDAY_INDEX)[day] + "s" for day in days]
        label = "tous les " + (names[0] if len(names) == 1 else ", ".join(names[:-1]) + " et " + names[-1])
        return {
            "alarm": "weekly:" + ",".join(map(str, days)),
            "rrule": "FREQ=WEEKLY;BYDAY=" + ",".join(WEEKDAY_CODES[day] for day in days),
            "label": label,
            "days": days,
        }
    if re.search(r"\btoutes les semaines\b|\bchaque semaine\b|\bhebdomadaire", folded):
        return {"alarm": "weekly", "rrule": "FREQ=WEEKLY", "label": "toutes les semaines"}
    return None


def first_occurrence(text: str, repeat: dict) -> datetime | None:
    """Première échéance d'une répétition : l'heure dite, le premier jour concerné à venir."""
    normalized = normalize_spoken_time(text)
    clock = extract_time_of_day(normalized)
    if clock is None:
        return None
    hour = apply_day_period(clock[0], normalized.lower())
    now = local_now()
    candidate = now.replace(hour=hour, minute=clock[1], second=0, microsecond=0)
    days = set(repeat.get("days") or (range(5) if repeat["alarm"] == "weekdays" else range(7)))
    for _ in range(8):
        if candidate > now and candidate.weekday() in days:
            return candidate
        candidate += timedelta(days=1)
    return None
