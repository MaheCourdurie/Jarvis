from __future__ import annotations

import re
import shlex
from datetime import datetime, timedelta
from typing import Any

from config import load_contacts
from persona import TITLE, fold as _fold, smalltalk_reply, strip_vocative


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

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
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


def _find_contact(text: str) -> tuple[str, str] | None:
    """Retrouve un contact cité dans la phrase (« envoie un mail à Paul »)."""
    folded = _fold(text)
    best: tuple[str, str] | None = None
    for name, email in load_contacts().items():
        key = re.escape(_fold(name))
        if re.search(rf"\b(?:a|au|pour|avec)\s+{key}\b", folded):
            # Le nom le plus long l'emporte (« Paul Martin » avant « Paul »).
            if best is None or len(name) > len(best[0]):
                best = (name, email)
    return best


def _normalize_spoken_email(text: str) -> str:
    """Recolle une adresse dictée (« paul arobase exemple point com »)."""
    if "arobase" not in text.lower():
        return text
    normalized = re.sub(r"\s*\barobase\b\s*", "@", text, flags=re.IGNORECASE)
    return re.sub(r"(@[\w-]+(?:\.[\w-]+)*)\s+point\s+([a-z]{2,6})\b", r"\1.\2", normalized, flags=re.IGNORECASE)


def _normalize_spoken_time(text: str) -> str:
    """Ramène les heures dictées à la forme 7h30 (« 7 heures et demie », « midi », « 20 heures »)."""
    normalized = text.replace("’", "'")

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


def _extract_relative_delay(text: str) -> timedelta | None:
    """Extrait une durée (« 10 minutes », « une demi-heure », « 1h30 », « 45 secondes »)."""
    folded = _fold(text)
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


def _extract_email(value: str) -> str | None:
    """Extrait la première adresse email détectée dans le texte."""
    match = EMAIL_PATTERN.search(value)
    if not match:
        return None
    return match.group(0)


def extract_recent_email_from_history(history: list[Any], max_messages: int = 8) -> str | None:
    """Récupère la dernière adresse email visible dans l'historique récent."""
    for item in reversed(history[-max_messages:]):
        content = getattr(item, "content", None)
        if content is None and isinstance(item, dict):
            content = item.get("content", "")
        email = _extract_email(str(content or ""))
        if email:
            return email
    return None


def _parse_datetime(value: str) -> datetime:
    """Convertit une date saisie en objet datetime ISO."""
    normalized = value.strip().replace("/", "-")
    if "T" not in normalized and " " in normalized:
        normalized = normalized.replace(" ", "T")
    return datetime.fromisoformat(normalized)


def _extract_time_of_day(text: str) -> tuple[int, int] | None:
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


def _apply_day_period(hour: int, lowered: str) -> int:
    """Passe en heure de l'après-midi/du soir quand la phrase le précise (« 8h ce soir » → 20h)."""
    if 1 <= hour <= 11 and re.search(r"\bsoir\b", lowered):
        return hour + 12
    if 1 <= hour <= 6 and re.search(r"\bapr[eè]s-midi\b", lowered):
        return hour + 12
    return hour


def _parse_datetime_expression(text: str) -> datetime | None:
    """Interprète une date/heure naturelle en français (demain, lundi, dans 2h...)."""
    now = datetime.now()
    text = _normalize_spoken_time(text)

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
        delay = _extract_relative_delay(m.group(1))
        if delay is not None:
            return now + delay

    # Aujourd'hui / demain (mots-clés avec heure placée avant ou après)
    has_today = re.search(r"\b(?:aujourd'hui|aujourdhui|ajd|ce soir|ce matin|cet apr[eè]s-midi)\b", lowered) is not None
    has_tomorrow = re.search(r"\bdemain\b", lowered) is not None
    if has_today or has_tomorrow:
        extracted = _extract_time_of_day(lowered)
        if extracted is None:
            # "demain matin", "ce soir" : pas d'heure précise, on prend celle du moment de la journée.
            if re.search(r"\bmatin\b", lowered):
                extracted = (9, 0)
            elif re.search(r"\bapr[eè]s-midi\b", lowered):
                extracted = (14, 0)
            elif re.search(r"\bsoir\b", lowered):
                extracted = (19, 0)
        if extracted is not None:
            hour, minute = _apply_day_period(extracted[0], lowered), extracted[1]
            if has_today:
                # Quand l'utilisateur dit explicitement "aujourd'hui", on respecte le jour demandé.
                base = now
            else:
                base = now + timedelta(days=1)
            return base.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # Heure avec préposition: "a 15h", "pour 16:30", "vers 9h"
    m = re.search(r"\b(?:a|pour|vers)\s*(\d{1,2})(?:(?:[:h])(\d{2}))?\b", lowered)
    if m:
        hour = _apply_day_period(int(m.group(1)), lowered)
        minute = int(m.group(2) or "0")
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target < now:
                target += timedelta(days=1)
            return target

    # Heure seule: "16h40", "16:30" -> aujourd'hui ou demain si déjà passé
    extracted = _extract_time_of_day(lowered)
    if extracted is not None:
        hour, minute = _apply_day_period(extracted[0], lowered), extracted[1]
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target < now:
            target += timedelta(days=1)
        return target

    return None


def _parse_day_value(value: str, now: datetime | None = None) -> datetime | None:
    """Transforme un jour (ISO/FR/relatif) en datetime au début de journée."""
    base_now = now or datetime.now()
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


def _extract_day_period_bounds(text: str) -> tuple[datetime, datetime] | None:
    """Déduit les bornes (début, fin) d'une journée ou d'une période mentionnée."""
    lowered = text.lower().replace("’", "'")
    now = datetime.now()

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
        parsed = _parse_day_value(token, now=now)
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


def _extract_duration_minutes(text: str) -> int | None:
    """Extrait une durée exprimée en heures/minutes et la convertit en minutes."""
    lowered = text.lower().replace("à", "a")

    m = re.search(r"\b(?:bloque|bloquer|pendant|durant|pour)\s+(\d+)\s*(heure|heures|h)\b", lowered)
    if m:
        return int(m.group(1)) * 60

    m = re.search(r"\b(?:bloque|bloquer|pendant|durant|pour)\s+(\d+)\s*(minute|min|minutes)\b", lowered)
    if m:
        return int(m.group(1))

    return None


def _clean_fragment(value: str) -> str:
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


def _strip_time_expressions(text: str) -> str:
    """Retire les indications de date et d'heure d'une phrase pour n'en garder que le sujet."""
    cleaned = _normalize_spoken_time(text)
    for pattern in _TIME_FRAGMENTS:
        cleaned = pattern.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" ,.;:!?-")


def _capitalize(value: str) -> str:
    return value[:1].upper() + value[1:] if value else value


def _extract_alarm_title(text: str, default: str = "Alarme") -> str:
    """Extrait un titre d'alarme depuis une phrase naturelle.

    Exemples pris en charge:
    - mets une alarme "PAUSE"
    - mets une alarme dans 1 min pour PAUSE
    - programme un reveil appele PAUSE
    """
    quoted = re.findall(r'"([^\"]+)"', text)
    if quoted:
        title = _clean_fragment(quoted[-1])
        if title:
            return title

    # On prend le segment après le dernier "pour", débarrassé des indications d'heure.
    split_matches = re.split(r"\bpour\b", text, flags=re.IGNORECASE)
    if len(split_matches) >= 2:
        candidate = _clean_fragment(_strip_time_expressions(split_matches[-1]))
        if len(candidate) >= 2:
            return _capitalize(candidate)

    named_match = re.search(r"\b(?:nomm[ée]e?|appel[ée]e?|intitul[ée]e?)\b\s+(.+)$", text, flags=re.IGNORECASE)
    if named_match:
        candidate = _clean_fragment(named_match.group(1))
        if candidate:
            return candidate

    return default


def _extract_mail_subject(text: str, quoted_parts: list[str]) -> str:
    """Extrait l'objet d'email à partir de la phrase utilisateur."""
    subject = ""

    subject_quoted = re.search(r'(?:sujet|objet)\s*[:=]?\s*"([^\"]+)"', text, flags=re.IGNORECASE)
    if subject_quoted:
        subject = _clean_fragment(subject_quoted.group(1))

    if not subject:
        subject_plain = re.search(
            r"(?:sujet|objet)\s*[:=]?\s*(.+?)(?=(?:\b(?:message|contenu|corps|et\s+dis(?:-|\s)?lui|"
            r"en\s+lui\s+disant|pour\s+lui\s+dire|dis(?:-|\s)?lui)\b|$))",
            text,
            flags=re.IGNORECASE,
        )
        if subject_plain:
            subject = _clean_fragment(subject_plain.group(1))

    if not subject and quoted_parts:
        subject = _clean_fragment(quoted_parts[0])

    return subject


def _extract_mail_body(text: str) -> tuple[str, bool]:
    """Extrait le corps d'email et indique s'il était explicitement fourni."""
    body = ""
    explicit_body = False
    normalized = text.replace("’", "'")

    body_quoted = re.search(r'(?:message|contenu|corps)\s*[:=]?\s*"([^\"]+)"', text, flags=re.IGNORECASE)
    if body_quoted:
        body = _clean_fragment(body_quoted.group(1))
        explicit_body = True

    if not body:
        body_plain = re.search(r"(?:message|contenu|corps)\s*[:=]?\s*(.+)$", text, flags=re.IGNORECASE)
        if body_plain:
            body = _clean_fragment(body_plain.group(1))
            explicit_body = True

    if not body:
        natural_patterns = [
            r"(?:et\s+)?dis(?:-|\s)?lui\s+(?:que|qu['’])\s*(.+)$",
            r"(?:et\s+)?dis(?:-|\s)?lui\s+(.+)$",
            r"(?:et\s+)?dit(?:-|\s)?lui\s+(?:que|qu['’])\s*(.+)$",
            r"en\s+lui\s+disant\s+(?:que|qu['’])\s*(.+)$",
            r"pour\s+lui\s+dire\s+(?:que|qu['’])\s*(.+)$",
            r"(?:et|puis)\s+lui\s+dire\s+(?:que|qu['’])\s*(.+)$",
            r"(?:et|puis)\s+lui\s+dire\s+(.+)$",
            r"pour\s+(?:lui\s+)?(?:dire|annoncer|pr[ée]venir|signaler|confirmer)\s+(?:que|qu['’])\s*(.+)$",
            r"pour\s+lui\s+(?:dire|demander|proposer|rappeler)\s+(.+)$",
            # « écris à paul@exemple.com : la réunion est annulée »
            r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+\s*:\s*(.+)$",
            r"\b(?:a|à)\s+[^:@]{2,40}?\s*:\s*(.+)$",
        ]
        for pattern in natural_patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if match:
                body = _clean_fragment(match.group(1))
                break

    if not body:
        after_subject = re.search(
            r"(?:sujet|objet)\s*[:=]?\s*(?:\"[^\"]+\"|[^,;]+)\s*(?:,|;|\bet\b)\s*(.+)$",
            text,
            flags=re.IGNORECASE,
        )
        if after_subject:
            candidate = _clean_fragment(after_subject.group(1))
            candidate = re.sub(
                r"^(?:et\s+)?(?:dis(?:-|\s)?lui(?:\s+que)?|dit(?:-|\s)?lui(?:\s+que)?|"
                r"en\s+lui\s+disant\s+que|pour\s+lui\s+dire\s+que)\s+",
                "",
                candidate,
                flags=re.IGNORECASE,
            )
            body = _clean_fragment(candidate)

    return body, explicit_body


def _references_previous_mail(text: str) -> bool:
    """Détecte si la phrase fait référence à un email déjà évoqué."""
    lowered = text.lower().replace("’", "'")
    patterns = [
        r"\b(?:ce|cet|cette)\s+(?:mail|email|e-mail|message|destinataire|adresse)\b",
        r"\b(?:envoie|envoye|envoi|envoyer|send)\s*(?:-|\s)?(?:le|la|lui)\b",
        r"\b(?:l[' ]?envoyer|lui\s+envoyer|renvoie(?:-|\s)?le)\b",
        r"\b(?:au|a\s+la)\s+m[eé]me\s+(?:mail|email|destinataire|adresse)\b",
    ]
    return any(re.search(pattern, lowered) for pattern in patterns)


def _is_mail_followup_payload(text: str) -> bool:
    """Détecte une réponse de suivi contenant objet/message sans verbe d'envoi."""
    lowered = text.lower().replace("’", "'").strip()
    return bool(
        re.search(
            r"^(?:sujet|objet|message|contenu|corps)\b"
            r"|^(?:et\s+)?dis(?:-|\s)?lui\b"
            r"|^(?:et\s+)?dit(?:-|\s)?lui\b"
            r"|^en\s+lui\s+disant\b"
            r"|^pour\s+lui\s+dire\b",
            lowered,
            flags=re.IGNORECASE,
        )
    )


def _parse_natural_send_mail(text: str, fallback_email: str | None = None) -> dict | None:
    """Interprète une demande naturelle d'envoi d'email et renvoie l'action associée."""
    text = _normalize_spoken_email(text)
    lowered = text.lower().replace("’", "'")
    has_mail_term = re.search(r"\b(?:mails?|emails?|e-mails?|courriers?|courriels?|messages?)\b", lowered) is not None
    references_previous_mail = _references_previous_mail(text)
    has_followup_payload = bool(fallback_email) and _is_mail_followup_payload(text)
    # Verbes d'envoi explicites, par opposition aux verbes de rédaction (« écris-moi un poème »).
    has_dispatch_verb = re.search(r"\b(?:envoie|envoye|envoi|envoyer|envoyez|send|exp[ée]die)\b", lowered) is not None
    has_writing_verb = re.search(r"\b(?:[ée]cris|[ée]crit|[ée]crire|r[ée]dige|r[ée]diger)\b", lowered) is not None

    if not (has_dispatch_verb or has_writing_verb) and not has_followup_payload:
        return None

    explicit_email = _extract_email(text)
    contact = None if explicit_email else _find_contact(text)
    has_recipient = explicit_email is not None or contact is not None
    if not has_mail_term and not has_recipient and not references_previous_mail and not has_followup_payload:
        return None

    to_email = explicit_email or (contact[1] if contact else None)
    to_name = contact[0] if contact else None
    if not to_email and (references_previous_mail or has_followup_payload):
        to_email = fallback_email

    if not to_email:
        # « Rédige un message d'anniversaire » : pas un envoi, le modèle s'en charge.
        if not has_dispatch_verb:
            return None
        return {
            "action": "command_error",
            "message": (
                f"Il me faut l'adresse du destinataire, {TITLE}. Dites par exemple : "
                "envoie un mail à client@exemple.com pour lui dire que le devis est prêt."
            ),
        }

    recipient = to_name or to_email
    quoted_parts = re.findall(r'"([^\"]+)"', text)
    subject = _extract_mail_subject(text, quoted_parts)
    body, explicit_body = _extract_mail_body(text)

    if not body:
        if subject:
            return {
                "action": "command_error",
                "message": (
                    f"Je peux écrire à {recipient} avec l'objet « {subject} », {TITLE}, "
                    "mais il me manque le message. Que dois-je lui dire ?"
                ),
            }
        return {
            "action": "command_error",
            "message": f"Je peux écrire à {recipient}, {TITLE}. Que dois-je lui dire ?",
        }

    auto_subject = not bool(subject)
    auto_draft = False
    auto_polish = bool(body) and not explicit_body

    return {
        "action": "send_mail",
        "params": {
            "to_email": to_email,
            "to_name": to_name,
            "subject": subject,
            "body": body,
            "auto_subject": auto_subject,
            "auto_draft": auto_draft,
            "auto_polish": auto_polish,
            "draft_context": text,
            # Demande formulée en langage naturel : Jarvis montre le message avant de l'envoyer.
            "confirm": True,
        },
    }


def _parse_natural_timer(text: str) -> dict | None:
    """Interprète une demande de minuteur (« minuteur de 10 minutes »)."""
    folded = _fold(text)
    if not re.search(r"\b(?:minuteurs?|compte a rebours|chronometre|chrono|timer)\b", folded):
        return None

    if re.search(r"\b(?:supprime|annule|arrete|stoppe|coupe)\b", folded):
        return {"action": "delete_timers"}
    if re.search(r"\bcombien de temps\b|\breste[- ]t[- ]il\b|\b(?:temps )?restant\b|\bou en est\b|\bquels? (?:sont )?(?:mes |les )?minuteurs\b", folded):
        return {"action": "list_alarms"}

    delay = _extract_relative_delay(text)
    if delay is None:
        return {
            "action": "command_error",
            "message": f"Pour quelle durée, {TITLE} ? Par exemple : minuteur de 10 minutes.",
        }

    label = ""
    label_match = re.search(r"\bpour\s+(.+)$", text, flags=re.IGNORECASE)
    if label_match:
        label = _clean_fragment(_strip_time_expressions(label_match.group(1)))
        label = re.sub(r"^\d+\s*(?:minutes?|min|mn|heures?|h|secondes?|sec)\b\s*", "", label, flags=re.IGNORECASE)
    title = f"Minuteur : {label}" if len(label) >= 2 else "Minuteur"

    return {
        "action": "set_alarm",
        "params": {"when": (datetime.now() + delay).isoformat(), "title": title, "kind": "timer"},
    }


def _parse_natural_reminder(text: str) -> dict | None:
    """Interprète un rappel (« rappelle-moi dans 20 minutes de sortir le gâteau »)."""
    lead = re.search(
        r"\b(?:rappelle|rappelez)[- ]moi\b|\bfai(?:s|tes)[- ]moi penser\b|\bpense à me rappeler\b"
        r"|\b(?:pr[ée]viens|pr[ée]venez|avertis|avertissez|alerte|alertez)[- ]moi\b",
        text,
        flags=re.IGNORECASE,
    )
    if not lead:
        return None

    when = _parse_datetime_expression(text)
    if when is None:
        return {
            "action": "command_error",
            "message": (
                f"Quand dois-je vous le rappeler, {TITLE} ? "
                "Par exemple : rappelle-moi dans 20 minutes de sortir le gâteau."
            ),
        }

    subject = _strip_time_expressions(text[: lead.start()] + " " + text[lead.end():])
    subject = re.sub(r"^(?:de|d'|que|qu'|à|a)\s*", "", subject.replace("’", "'"), flags=re.IGNORECASE)
    subject = _clean_fragment(subject)

    return {
        "action": "set_alarm",
        "params": {
            "when": when.isoformat(),
            "title": _capitalize(subject) if len(subject) >= 2 else "Rappel",
            "kind": "reminder",
        },
    }


def _parse_natural_alarm(text: str) -> dict | None:
    """Interprète une demande naturelle liée aux alarmes (création/liste/suppression)."""
    folded = _fold(text)
    has_alarm_term = re.search(r"\b(?:alarmes?|reveils?)\b", folded) is not None
    wake_me = re.search(r"\breveille[sz]?[- ]moi\b", folded) is not None
    if not has_alarm_term and not wake_me:
        return None

    is_delete = re.search(r"\b(?:supprime|annule|efface|retire|enleve)\b", folded) is not None
    is_create = wake_me or re.search(r"\b(?:mets|met|ajoute|programme|cree|regle|lance)\b", folded) is not None

    if not is_delete and not is_create and re.search(r"\b(?:liste|montre|affiche|quelles?|mes|ai-je|combien)\b", folded):
        return {"action": "list_alarms"}

    if is_delete:
        day_period = _extract_day_period_bounds(text)
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
    from core import phrases

    recurring = phrases.recurring_alarm(text, _extract_alarm_title(text, default=default_title))
    if recurring is not None:
        return recurring

    when = _parse_datetime_expression(text)
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
        subject = _clean_fragment(_strip_time_expressions(subject_match.group(1)))
        if len(subject) >= 2:
            return _capitalize(subject)

    # « Note dans mon agenda : match de foot samedi à 14h »
    colon_match = re.search(r":\s*(.+)$", text)
    if colon_match:
        subject = _clean_fragment(_strip_time_expressions(colon_match.group(1)))
        if len(subject) >= 2:
            return _capitalize(subject)

    with_match = re.search(r"\bavec\s+(.+)$", text, flags=re.IGNORECASE)
    if with_match:
        person = _clean_fragment(_strip_time_expressions(with_match.group(1)))
        person = re.split(r"\s+(?:de|du|pour|pendant|durant)\s+\d", person)[0].strip()
        if len(person) >= 2:
            return f"{base or 'Rendez-vous'} avec {person}"

    # « rendez-vous chez le dentiste demain à 15h »
    at_match = re.search(r"\bchez\s+(.+)$", text, flags=re.IGNORECASE)
    if at_match:
        place = _clean_fragment(_strip_time_expressions(at_match.group(1)))
        if len(place) >= 2:
            return f"{base or 'Rendez-vous'} chez {place}"

    return base or "Événement"


def _parse_natural_calendar(text: str) -> dict | None:
    """Interprète une demande naturelle liée au calendrier (création/liste/suppression)."""
    text = _normalize_spoken_time(text)
    lowered = text.lower()
    folded = _fold(text)

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

        day_period = _extract_day_period_bounds(text)
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
        from core import phrases

        repeat = phrases.extract_repeat(folded)
        start = _parse_datetime_expression(text)
        if repeat is not None and repeat["alarm"] != "weekly":
            start = phrases.first_occurrence(text, repeat) or start
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
            duration_minutes = _extract_duration_minutes(text)
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
        day_period = _extract_day_period_bounds(text)
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
        day_period = _extract_day_period_bounds(text)
        if day_period is None:
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            day_period = (today, today + timedelta(days=1))
        start, end = day_period
        return {"action": "events_range", "params": {"start": start.isoformat(), "end": end.isoformat()}}

    return None


def _parse_command(text: str) -> dict:
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
            start = _parse_datetime(parts[2])
            end = _parse_datetime(parts[3])
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

        start_day = _parse_day_value(parts[1])
        end_day = _parse_day_value(parts[2]) if len(parts) >= 3 else start_day

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
            when = _parse_datetime(parts[1])
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

        start_day = _parse_day_value(parts[1])
        end_day = _parse_day_value(parts[2]) if len(parts) >= 3 else start_day

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


_NOT_A_CITY = {"demain", "aujourd'hui", "maintenant", "moment", "semaine", "matin", "soir", "midi", "jarvis"}


_TIME_WORDS = re.compile(
    r"\b(?:semaine|week-?end|jours?|matin|soir|apres-midi|nuit|demain|apres-demain|aujourd'hui|maintenant"
    r"|lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|prochains?)\b"
)


def _extract_city(text: str) -> str | None:
    """Repère une ville dans une demande météo (« à Lyon », « sur New York », « météo Bordeaux »)."""
    city = _extract_city_candidate(text)
    if city and _TIME_WORDS.search(_fold(city)):
        return None
    return city


def _extract_city_candidate(text: str) -> str | None:
    match = re.search(
        r"(?:\b(?:a|sur|pour|de)|à)\s+((?:[A-ZÀ-Ý][\wà-ÿ'’-]+)(?:[ -][A-ZÀ-Ý][\wà-ÿ'’-]+)*)",
        text,
    )
    if match and _fold(match.group(1)) not in _NOT_A_CITY:
        return match.group(1)

    match = re.search(r"\bm[ée]t[ée]o\s+(?:(?:a|à|de|sur|pour)\s+)?([a-zà-ÿ][\wà-ÿ' -]{1,30})$", text.strip(" ?!."), flags=re.IGNORECASE)
    if match:
        candidate = re.sub(r"\b(?:de\s+)?(?:demain|aujourd'hui|maintenant)\b", "", match.group(1), flags=re.IGNORECASE).strip(" '-")
        if len(candidate) >= 2 and _fold(candidate) not in _NOT_A_CITY and not _fold(candidate).startswith(("du ", "de ", "pour ")):
            return candidate.title()
    return None


def _parse_info(text: str) -> dict | None:
    """Interprète les demandes d'information : heure, date, météo, briefing."""
    folded = _fold(text)

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
        from core import phrases

        return {"action": "weather", "params": {"city": _extract_city(text), "day": phrases.weather_day(folded)}}

    if re.search(
        r"\bbriefing\b|\bfai(?:s|tes)[- ](?:moi )?(?:le|un) point\b|\bpoint sur (?:la|ma) journee\b"
        r"|\brapport du (?:jour|matin)\b|\bprogramme (?:du jour|de la journee)\b|\bresume de (?:la|ma) journee\b",
        folded,
    ):
        return {"action": "briefing"}

    return None


def _parse_mail_reading(text: str) -> dict | None:
    """Interprète les demandes de lecture de la messagerie."""
    folded = _fold(text)
    has_mail = re.search(
        r"\b(?:mails?|emails?|e-mails?|courriers?|courriels?|messagerie|boite (?:mail|de reception|aux lettres))\b"
        r"|\bnouveaux messages\b|\bmessages non lus\b|\bqui m'a ecrit\b",
        folded,
    )
    if not has_mail:
        return None
    # Supprimer, archiver ou répondre n'est pas lire : ces demandes ne sont pas prises en charge.
    if re.search(r"\b(?:supprime|efface|archive|reponds|repondre|transfere|marque)\b", folded):
        return None

    if re.search(r"\b(?:dernier|derniere|latest|plus recent)\b", folded):
        return {"action": "mail_last"}
    if re.search(
        r"\b(?:resume|lis|lire|consulte|consulter|verifie|verifier|regarde|regarder|check|checker|montre|montrer"
        r"|affiche|afficher|non lus?|nouveaux?|recu|releve)\b"
        r"|\bai[- ]je\b|\best[- ]ce que j'ai\b|\bj'ai des\b|\bquoi de neuf\b|\bqui m'a ecrit\b",
        folded,
    ):
        return {"action": "mail_resume"}
    return None


_SEARCH_VERB = re.compile(
    r"^(?:(?:peux|pourrais|pouvez|pourriez)[- ](?:tu|vous)\s+)?(?:me\s+)?"
    r"(?:(?:fais|lance)(?:[- ]moi)?\s+une\s+recherche(?:\s+(?:web|internet))?\s+(?:sur|pour|de)\s+"
    r"|(?:cherche|recherche|chercher|rechercher|trouve|trouver|renseigne[- ]toi sur)(?:[- ]moi)?\s+"
    r"|regarde(?:[- ]moi)?\s+(?=.*\bsur (?:internet|le web|le net|google)\b))(.+)$",
    flags=re.IGNORECASE,
)
# Questions dont la réponse se trouve sur le web : informations locales, récentes ou chiffrées.
_WEB_TOPICS = re.compile(
    r"\bhoraires?\b|\bheures? d'ouverture\b|\ba quelle heure (?:ouvre|ferme)\b|\b(?:ouvre|ferme) a quelle heure\b"
    r"|\b(?:est|sont)[- ](?:il|elle|ils|elles|ce que) (?:encore |toujours )?ouverte?s?\b|\bencore ouverte?s?\b"
    r"|\bpharmacies? de garde\b|\bprogramme (?:tv|tele|cine|du cinema)\b|\bseances? (?:de|du) cinema\b"
    r"|\bau cinema\b|\bfilms? (?:a l'affiche|en ce moment|qui passent?)\b"
    r"|\bactualites?\b|\bactus?\b|\bnews\b|\bdernieres nouvelles\b"
    r"|\bresultats? (?:du|de la|des|d'un|d'une)\b|\bscore (?:du|de|des)\b|\bqui a gagne\b|\bclassement (?:de|du|des)\b"
    r"|\bprix (?:de|du|d'un|d'une|des)\b|\bcombien (?:ca )?coute\b|\btarifs?\b"
    r"|\bcours (?:de l'action|du bitcoin|de l'euro|du dollar|de bourse|de l'or)\b|\btaux de change\b"
    r"|\bnumero de telephone\b|\badresse (?:de|du|des|d'un|d'une)\b"
    r"|\bdate de sortie\b|\bquand (?:sort|sortira|sortent)\b|\bprochaine sortie\b|\btrafic\b|\bbouchons\b|\bgreves?\b"
    r"|\b(?:restaurant|resto|boulangerie|pharmacie|medecin|dentiste|garage|supermarche|magasin|coiffeur)s? "
    r"(?:ouverte?s?|pres|proche|a proximite|dans le coin|autour|a cote)\b"
    r"|\bmeilleure?s? (?:restaurant|resto|bar|pizzeria|boulangerie|coiffeur|garage|medecin|dentiste)s?\b"
)
_PERSONAL_DATA = re.compile(r"\b(?:mes|mon|ma|nos|notre) (?:mails?|emails?|agenda|calendrier|evenements?|alarmes?|contacts?|horaires?|rendez)")


def _parse_web_question(text: str) -> dict | None:
    """Repère les demandes que Jarvis doit aller chercher lui-même sur le web."""
    cleaned = text.strip().strip(".!?").strip()
    folded = _fold(cleaned)
    if _PERSONAL_DATA.search(folded) or re.search(r"\bdans (?:mes|mon|ma) \w+", folded):
        return None

    explicit = _SEARCH_VERB.match(cleaned)
    if explicit:
        query = explicit.group(1).strip()
        # « sur YouTube » : on ouvre la recherche dans le navigateur, c'est pour regarder.
        video = re.search(r"\s+(?:sur|dans)\s+youtube$", query, flags=re.IGNORECASE)
        if video:
            return {"action": "web_search", "params": {"query": query[: video.start()].strip(), "engine": "youtube"}}
        video = re.match(r"(?:sur|dans)\s+youtube\s+(.+)$", query, flags=re.IGNORECASE)
        if video:
            return {"action": "web_search", "params": {"query": video.group(1).strip(), "engine": "youtube"}}
        query = re.sub(r"\s+(?:sur|dans)\s+(?:google|internet|le web|le net|wikip[ée]dia)$", "", query, flags=re.IGNORECASE).strip()
        if query:
            return {"action": "web_answer", "params": {"query": query}}

    if _WEB_TOPICS.search(folded):
        # La requête sera formulée par le modèle à partir de la question et de la ville.
        return {"action": "web_answer", "params": {"query": None}}

    return None


def _parse_system(text: str) -> dict | None:
    """Interprète les demandes de pilotage du poste : diagnostic, volume, applications, web, veille."""
    folded = _fold(text).strip(" .!?")
    cleaned = text.strip().strip(".!?").strip()

    # Diagnostic
    if re.search(r"\bbatterie\b|\bautonomie\b", folded):
        return {"action": "system_status", "params": {"focus": "battery"}}
    if re.search(
        r"\bdiagnostic\b|\b(?:etat|statut|status|rapport|bilan) (?:du|des|de tes|de vos|de mon|systeme)\s*(?:systemes?|mac|poste|pc|ordinateur|machine)?"
        r"|\brapport d'etat\b|\btous les systemes\b|\b(?:utilisation|charge|usage) (?:du |de la )?(?:processeur|cpu|memoire|ram)\b"
        r"|\bespace disque\b|\bmemoire (?:vive|utilisee|disponible)\b",
        folded,
    ):
        return {"action": "system_status"}

    # Volume
    sound = r"(?:son|volume)"
    level = re.search(rf"\b{sound}\s+(?:a|au|sur)\s+(\d{{1,3}})\b", folded)
    if level:
        return {"action": "volume", "params": {"mode": "set", "level": min(100, int(level.group(1)))}}
    if re.search(rf"\b{sound}\s+(?:au maximum|au max|a fond)\b", folded):
        return {"action": "volume", "params": {"mode": "set", "level": 100}}
    if re.search(rf"\b(?:coupe|mute|desactive|eteins)\s+le\s+{sound}\b|\ben sourdine\b|\bmode muet\b", folded):
        return {"action": "volume", "params": {"mode": "mute"}}
    if re.search(rf"\b(?:remets|reactive|retablis|rallume|active)\s+le\s+{sound}\b", folded):
        return {"action": "volume", "params": {"mode": "unmute"}}
    if re.search(rf"\b(?:monte|augmente|hausse)\b.*\b{sound}\b|\bplus fort\b", folded):
        return {"action": "volume", "params": {"mode": "up"}}
    if re.search(rf"\b(?:baisse|diminue|reduis)\b.*\b{sound}\b|\bmoins fort\b", folded):
        return {"action": "volume", "params": {"mode": "down"}}
    if re.search(rf"\b(?:quel est le|a combien est le|niveau du|montre le)\s+{sound}\b", folded):
        return {"action": "volume", "params": {"mode": "get"}}

    # Veille de l'écran
    if re.search(
        r"\bverrouille[rz]?\s+(?:l'ecran|la session|le mac|l'ordinateur|le poste)\b"
        r"|\b(?:mets|mettre|passe)\s+(?:l'ecran|le mac|l'ordinateur|le poste)\s+en veille\b|\beteins l'ecran\b",
        folded,
    ):
        return {"action": "sleep_display"}

    # Recherche à ouvrir dans le navigateur (les recherches « parlées » sont dans _parse_web_question)
    browser_search = re.match(
        r"^(?:ouvre|affiche|montre)(?:[- ]moi)?\s+(?:une\s+|la\s+)?recherche\s+(?:web\s+|internet\s+|google\s+)?(?:sur|pour|de)\s+(.+)$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if browser_search:
        return {"action": "web_search", "params": {"query": browser_search.group(1).strip(), "engine": "web"}}

    # Ouverture d'un site ou d'une application
    opening = re.match(r"^(?:ouvre|ouvrir|ouvrez|lance|lancer|lancez|d[ée]marre|d[ée]marrer)(?:[- ]moi)?\s+(.+)$", cleaned, flags=re.IGNORECASE)
    if opening:
        target = opening.group(1).strip()
        site = re.sub(r"^(?:le\s+site\s+(?:de\s+|d')?|la\s+page\s+(?:de\s+|d')?)", "", target, flags=re.IGNORECASE)
        if re.fullmatch(r"(?:https?://)?[\w-]+(?:\.[\w-]+)+(?:/\S*)?", site):
            return {"action": "open_url", "params": {"url": site}}
        return {"action": "open_app", "params": {"name": target}}

    closing = re.match(r"^(?:ferme|fermer|fermez|quitte|quitter|quittez)\s+(.+)$", cleaned, flags=re.IGNORECASE)
    if closing:
        return {"action": "quit_app", "params": {"name": closing.group(1).strip()}}

    return None


_YES = re.compile(
    r"^(?:oui|ouais|yes|yep|affirmatif|absolument|exactement|tout a fait|bien sur|d'accord|ok|okay|c'est bon|parfait"
    r"|vas[- ]y|allez[- ]y|fais[- ]le|faites[- ]le|envoie(?:[- ]le)?|envoyez(?:[- ]le)?|confirme|je confirme|confirmer"
    r"|supprime(?:[- ]les)?|supprimez(?:[- ]les)?|tu peux|vous pouvez|s'il te plait|s'il vous plait)\b"
)
_NO = re.compile(
    r"^(?:non|nan|no|negatif|surtout pas|pas maintenant|pas du tout|annule|annulez|laisse tomber|laissez tomber"
    r"|oublie|oubliez|stop|attends|attendez|n'envoie|ne l'envoie|ne supprime)\b"
)


# ── Création : code et design ──────────────────────────────────────────────

_CREATE_VERB = (
    r"(?:cree|creer|crees|fais|fait|faire|fabrique|fabriquer|ecris|ecrire|code|coder|codes|genere|generer"
    r"|developpe|developper|dessine|dessiner|concois|concevoir|imagine|imaginer|propose|proposer|realise|realiser"
    r"|prepare|preparer|construis|construire|compose|composer|monte|monter|programme|programmer|redige|rediger)"
)
_CODE_NOUN = r"(?:script|programme|code|fonction|bot|algorithme|appli|application|app|jeu|outil|extension|calculatrice)"
_PAGE_NOUN = r"(?:site(?: web| internet| vitrine)?|page(?: web| d'accueil| html| internet)?|landing(?: page)?|maquette|portfolio|template|mockup)"
_LOGO_NOUN = r"(?:logo|logotype|icone|embleme)"
_PALETTE_NOUN = r"(?:palette|nuancier|gamme de couleurs|couleurs (?:pour|qui))"
_DOCUMENT_NOUN = (
    r"(?:lettre|cv|curriculum(?: vitae)?|compte[- ]rendu|attestation|courrier|discours|dissertation|expose|rapport"
    r"|devis|facture|contrat|proces[- ]verbal|note de synthese)"
)
_CODE_LANGUAGE = re.compile(
    r"\ben (python|javascript|js|typescript|bash|shell|zsh|swift|rust|go|golang|java|kotlin|php|ruby|sql|lua|applescript|c\+\+|c#|c)\b"
    r"|\b(python|javascript|typescript|bash|swift|rust|kotlin|php|ruby|applescript)\b"
)
# « programme » au sens d'emploi du temps ou d'entraînement : ce n'est pas du code.
_NOT_CODE = re.compile(r"\bprogramme (?:d'entrainement|de (?:revision|musculation|la journee|la semaine|course)|du jour|sportif|tele|tv)\b")
_CREATION_TARGET = r"(?:script|programme|code|page|site|logo|palette|maquette|creation|design|jeu|appli|application)"
_REVISE_VERB = (
    r"(?:modifie|modifier|change|changer|ameliore|ameliorer|corrige|corriger|ajoute|ajouter|rajoute|retire|enleve"
    r"|supprime|mets|met|rends|agrandis|reduis|remplace|refais|refaire|retouche|peaufine|traduis|simplifie|optimise)"
)


def _creation_request(verb: str, noun: str, folded: str) -> bool:
    return re.search(rf"\b{verb}\b(?:[- ]moi| moi)?(?:\s+\S+){{0,5}}?\s+{noun}s?\b", folded) is not None


def _parse_creation(text: str) -> dict | None:
    """Commandes à l'atelier : programmes, pages, logos, palettes, et retouches de la dernière création."""
    folded = _fold(text).strip(" .!?")
    request = text.strip().strip(".!?").strip()

    # Rouvrir, lister, suivre les créations.
    if re.search(rf"\b(?:ouvre|montre|affiche|rouvre)(?:[- ]moi)? (?:ma|la|mon|le) dernier(?:e)? {_CREATION_TARGET}\b", folded):
        return {"action": "open_creation"}
    if re.search(r"\b(?:mes|les) creations\b|\bmon atelier\b|\bou en est (?:la creation|le script|la page|le logo|la palette|le programme)\b", folded):
        return {"action": "list_creations"}

    # Retouches : « ajoute un bouton de contact à la page », « corrige-le », « change les couleurs du logo ».
    target = rf"(?:le|la|ce|cette|mon|ma|du|de la|au|a la|sur la|sur le|dans le|dans la|a ce|a cette)\s+{_CREATION_TARGET}\b"
    if re.search(rf"\b{_REVISE_VERB}\b.*\b{target}", folded) or re.match(
        r"^(?:modifie|ameliore|corrige|refais|retouche|peaufine|simplifie|optimise)[- ](?:le|la)\b", folded
    ):
        if not re.search(rf"\b{_CREATE_VERB}(?:[- ]moi)? (?:un|une|des)\b", folded):
            return {"action": "revise_creation", "params": {"request": request}}

    if re.search(r"\b(?:reviens|retourne|remets|revenir|reprends)\b.*\bversion (?:precedente|d'avant|anterieure)\b|\bannule (?:la |les )?(?:derniere )?(?:modification|retouche)s?\b", folded):
        return {"action": "previous_version"}

    if _creation_request(_CREATE_VERB, _DOCUMENT_NOUN, folded):
        return {"action": "write_document", "params": {"request": request}}

    if _creation_request(_CREATE_VERB, _LOGO_NOUN, folded):
        return {"action": "design_logo", "params": {"request": request}}
    if _creation_request(_CREATE_VERB, _PALETTE_NOUN, folded):
        return {"action": "design_palette", "params": {"request": request}}

    language = _CODE_LANGUAGE.search(folded)
    wants_code = _creation_request(_CREATE_VERB, _CODE_NOUN, folded) and not _NOT_CODE.search(folded)
    if _creation_request(_CREATE_VERB, _PAGE_NOUN, folded) and not wants_code:
        return {"action": "design_page", "params": {"request": request}}
    if wants_code or (language and re.search(rf"\b{_CREATE_VERB}\b", folded)):
        params = {"request": request}
        if language:
            params["language"] = language.group(1) or language.group(2)
        return {"action": "write_code", "params": params}
    return None


def classify_confirmation(text: str) -> str | None:
    """Interprète la réponse à une demande de confirmation : "yes", "no" ou None."""
    folded = _fold(strip_vocative(text)).strip(" .!?,")
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
        return _parse_command(stripped)

    # Petites phrases du quotidien (« Jarvis ? », « merci », « tu es là ? ») : réponse immédiate.
    smalltalk = smalltalk_reply(stripped)
    if smalltalk is not None:
        return {"action": "smalltalk", "reply": smalltalk}

    # « Jarvis, ouvre Safari » → « ouvre Safari »
    stripped = strip_vocative(stripped) or stripped

    from core import phrases

    # L'ordre compte : une phrase revient au premier parseur qui la reconnaît.
    parsers = (
        lambda: _parse_natural_send_mail(stripped, fallback_email=fallback_email),
        lambda: _parse_creation(stripped),
        lambda: phrases.parse_mail_more(stripped),
        lambda: phrases.parse_snooze(stripped),
        lambda: phrases.parse_poste(stripped),
        lambda: _parse_natural_timer(stripped),
        lambda: _parse_natural_reminder(stripped),
        lambda: _parse_natural_alarm(stripped),
        lambda: phrases.parse_move_event(stripped),
        lambda: _parse_natural_calendar(stripped),
        lambda: phrases.parse_notes(stripped),
        lambda: _parse_mail_reading(stripped),
        lambda: phrases.parse_memory(stripped),
        lambda: phrases.parse_routines(stripped),
        lambda: phrases.parse_sky(stripped),
        lambda: _parse_info(stripped),
        lambda: phrases.parse_translate(stripped),
        lambda: phrases.parse_travel(stripped),
        lambda: phrases.parse_files(stripped),
        lambda: phrases.parse_vision(stripped),
        lambda: phrases.parse_music(stripped),
        lambda: phrases.parse_home(stripped),
        lambda: phrases.parse_summarize_url(stripped),
        lambda: phrases.parse_encyclopedia(stripped),
        lambda: _parse_web_question(stripped),
        lambda: _parse_system(stripped),
    )
    for parser in parsers:
        action = parser()
        if action is not None:
            return action

    return None
