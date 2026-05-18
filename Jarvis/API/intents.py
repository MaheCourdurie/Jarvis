from __future__ import annotations

import re
import shlex
from datetime import datetime, timedelta


COMMAND_HELP = """Commandes disponibles:
/help
/mailresume
/maillast
/sendmail \"destinataire@domaine.com\" \"Objet\" \"Message\"
/eventsweek
/availability
/addevent \"Titre\" \"YYYY-MM-DD HH:MM\" \"YYYY-MM-DD HH:MM\"
/deleteevent \"id\"
/deleteeventsrange \"YYYY-MM-DD\" \"YYYY-MM-DD\"
/setalarm \"YYYY-MM-DD HH:MM\" \"Titre\"
/alarms
/deletealarm \"id\"
/deletealarmsrange \"YYYY-MM-DD\" \"YYYY-MM-DD\"
/deletealarmsall
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


def _extract_email(value: str) -> str | None:
    """Extrait la première adresse email détectée dans le texte."""
    match = EMAIL_PATTERN.search(value)
    if not match:
        return None
    return match.group(0)


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


def _parse_datetime_expression(text: str) -> datetime | None:
    """Interprète une date/heure naturelle en français (demain, lundi, dans 2h...)."""
    now = datetime.now()

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

    # Relatif: "dans 45 minutes", "dans 2 heures"
    m = re.search(r"dans\s+(\d+)\s*(minute|min|minutes)\b", lowered)
    if m:
        return now + timedelta(minutes=int(m.group(1)))

    m = re.search(r"dans\s+(\d+)\s*(heure|heures|h)\b", lowered)
    if m:
        return now + timedelta(hours=int(m.group(1)))

    # Aujourd'hui / demain (mots-clés avec heure placée avant ou après)
    has_today = re.search(r"\b(?:aujourd'hui|aujourdhui|ajd)\b", lowered) is not None
    has_tomorrow = re.search(r"\bdemain\b", lowered) is not None
    if has_today or has_tomorrow:
        extracted = _extract_time_of_day(lowered)
        if extracted is not None:
            hour, minute = extracted
            if has_today:
                # Quand l'utilisateur dit explicitement "aujourd'hui", on respecte le jour demandé.
                base = now
            else:
                base = now + timedelta(days=1)
            return base.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # Heure avec préposition: "a 15h", "pour 16:30", "vers 9h"
    m = re.search(r"\b(?:a|pour|vers)\s*(\d{1,2})(?:(?:[:h])(\d{2}))?\b", lowered)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or "0")
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target < now:
                target += timedelta(days=1)
            return target

    # Heure seule: "16h40", "16:30" -> aujourd'hui ou demain si déjà passé
    extracted = _extract_time_of_day(lowered)
    if extracted is not None:
        hour, minute = extracted
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


def _extract_alarm_title(text: str, lowered: str) -> str:
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

    # On prend le segment après le dernier "pour"
    split_matches = re.split(r"\bpour\b", text, flags=re.IGNORECASE)
    if len(split_matches) >= 2:
        candidate = _clean_fragment(split_matches[-1])
        candidate_lower = candidate.lower()
        # Ignore les fragments temporels et garde les vrais labels
        temporal_tokens = ["dans", "minute", "minutes", "min", "heure", "heures", "demain", "aujourd"]
        if candidate and not any(tok in candidate_lower for tok in temporal_tokens):
            return candidate

    named_match = re.search(r"\b(?:nomm[ée]e?|appel[ée]e?|intitul[ée]e?)\b\s+(.+)$", text, flags=re.IGNORECASE)
    if named_match:
        candidate = _clean_fragment(named_match.group(1))
        if candidate:
            return candidate

    return "Alarme Jarvis"


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
    lowered = text.lower().replace("’", "'")
    has_mail_term = any(token in lowered for token in ["mail", "email", "e-mail", "courrier", "message"])
    references_previous_mail = _references_previous_mail(text)
    has_followup_payload = bool(fallback_email) and _is_mail_followup_payload(text)
    has_send_term = any(
        token in lowered
        for token in [
            "envoie",
            "envoye",
            "envoi",
            "envoyer",
            "send",
            "expedie",
            "expédie",
            "écris",
            "ecris",
            "rédige",
            "redige",
            "écrit",
        ]
    )

    if not has_send_term and not has_followup_payload:
        return None
    explicit_email = _extract_email(text)
    if not has_mail_term and explicit_email is None and not references_previous_mail and not has_followup_payload:
        return None

    to_email = explicit_email
    if not to_email and (references_previous_mail or has_followup_payload):
        to_email = fallback_email

    if not to_email:
        return {
            "action": "command_error",
            "message": "Je n'ai pas trouvé d'adresse email. Exemple: envoie un mail à client@exemple.com sujet Devis message Bonjour.",
        }

    quoted_parts = re.findall(r'"([^\"]+)"', text)
    subject = _extract_mail_subject(text, quoted_parts)
    body, explicit_body = _extract_mail_body(text)

    if not body:
        if subject:
            return {
                "action": "command_error",
                "message": (
                    f"Je peux envoyer le mail à {to_email} avec l'objet '{subject}', "
                    "mais il me manque le message à transmettre. "
                    "Exemple: message Bonjour, je te confirme le rendez-vous de demain."
                ),
            }
        return {
            "action": "command_error",
            "message": (
                f"Je peux envoyer un mail à {to_email}, mais il me manque l'objet et le message. "
                "Dis-moi quoi envoyer, par exemple: "
                "envoie un mail à client@exemple.com sujet Devis message Bonjour, je vous envoie le devis."
            ),
        }

    auto_subject = not bool(subject)
    auto_draft = False
    auto_polish = bool(body) and not explicit_body

    return {
        "action": "send_mail",
        "params": {
            "to_email": to_email,
            "subject": subject,
            "body": body,
            "auto_subject": auto_subject,
            "auto_draft": auto_draft,
            "auto_polish": auto_polish,
            "draft_context": text,
        },
    }


def _parse_natural_alarm(text: str) -> dict | None:
    """Interprète une demande naturelle liée aux alarmes (création/liste/suppression)."""
    lowered = text.lower()

    if ("alarme" in lowered or "reveil" in lowered or "réveil" in lowered) and any(
        token in lowered for token in ["liste", "montre", "affiche", "quelles"]
    ):
        return {"action": "list_alarms"}

    if ("supprime" in lowered or "annule" in lowered) and (
        "alarme" in lowered or "reveil" in lowered or "réveil" in lowered
    ):
        alarm_id_match = re.search(r"\b([a-f0-9]{4,8})\b", lowered)
        if alarm_id_match:
            return {
                "action": "delete_alarm",
                "params": {"alarm_id": alarm_id_match.group(1)},
            }

        day_period = _extract_day_period_bounds(text)
        has_all_token = any(token in lowered for token in ["tout", "tous", "toutes"])
        has_plural_alarm = any(token in lowered for token in ["alarmes", "reveils", "réveils"])

        if has_all_token and has_plural_alarm and day_period is None:
            return {"action": "delete_alarms_all"}

        if day_period is not None:
            start, end = day_period
            return {
                "action": "delete_alarms_range",
                "params": {
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                },
            }

        return {
            "action": "command_error",
            "message": (
                "Précise l'identifiant, la journée ou la période des alarmes à supprimer. "
                "Exemples: supprime l'alarme abcd1234, supprime les alarmes de demain, "
                "supprime toutes mes alarmes."
            ),
        }

    if not any(token in lowered for token in ["alarme", "réveil", "reveil"]):
        return None
    if not any(token in lowered for token in ["mets", "met", "ajoute", "programme", "cree", "crée", "regle", "règle", "réveille", "reveille"]):
        return None

    when = _parse_datetime_expression(text)
    if when is None:
        return {
            "action": "command_error",
            "message": "Je n'ai pas trouvé la date/heure de l'alarme. Exemple: mets une alarme demain à 07:30",
        }

    title = _extract_alarm_title(text, lowered)

    return {
        "action": "set_alarm",
        "params": {
            "when": when.isoformat(),
            "title": title,
        },
    }


def _parse_natural_calendar(text: str) -> dict | None:
    """Interprète une demande naturelle liée au calendrier (création/liste/suppression)."""
    lowered = text.lower()

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

    if any(token in lowered for token in delete_verbs) and any(token in lowered for token in event_terms):
        quoted = re.findall(r'"([^\"]+)"', text)
        event_id = quoted[0].strip() if quoted else ""
        if not event_id:
            id_match = re.search(
                r"\b(?:id|event|evenement|événement)\b\s*[:=]?\s*([A-Za-z0-9_@.\-]{4,})\b",
                text,
                flags=re.IGNORECASE,
            )
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
                },
            }

        return {
            "action": "command_error",
            "message": (
                "Je n'ai pas trouvé l'id, la journée ou la période des événements à supprimer. "
                "Exemples: /deleteevent \"id\", supprime les événements de demain, "
                "supprime les événements du 2026-04-10 au 2026-04-12."
            ),
        }

    create_verbs = ["cree", "crée", "ajoute", "programme", "planifie", "planifier", "bloque", "bloquer"]

    has_create = any(token in lowered for token in create_verbs)
    has_event_term = any(token in lowered for token in event_terms)
    has_block_verb = any(token in lowered for token in ["bloque", "bloquer"])

    if has_create and (has_event_term or has_block_verb):
        start = _parse_datetime_expression(text)
        if start is None:
            return {
                "action": "command_error",
                "message": "Je n'ai pas trouvé la date/heure de l'événement. Exemple: crée un événement lundi prochain à 10h.",
            }

        end = None

        m = re.search(
            r"\bde\s*(\d{1,2})(?:(?:[:h])(\d{2}))?\s*(?:a|à|-|jusqu(?:'|’)a)\s*(\d{1,2})(?:(?:[:h])(\d{2}))?\b",
            lowered,
        )
        if m:
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

        quoted = re.findall(r'"([^\"]+)"', text)
        title = quoted[-1].strip() if quoted else ""

        if not title:
            m = re.search(r"\b(?:pour|concernant)\b\s+(.+)$", text, flags=re.IGNORECASE)
            if m:
                title = m.group(1).strip(" .;,")

        if not title and any(token in lowered for token in ["reunion", "réunion"]):
            title = "Réunion"
        if not title and any(token in lowered for token in ["rdv", "rendez"]):
            title = "Rendez-vous"
        if not title:
            title = "Événement Jarvis"

        return {
            "action": "add_event",
            "params": {
                "title": title,
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        }

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

    return {
        "action": "command_error",
        "message": f"Commande inconnue: {command}\n\n{COMMAND_HELP}",
    }


def detect_action(text: str, fallback_email: str | None = None) -> dict | None:
    """Détecte l'action métier à partir d'un texte utilisateur brut."""
    stripped = text.strip()
    if not stripped:
        return None

    if stripped.startswith("/"):
        return _parse_command(stripped)

    natural_mail = _parse_natural_send_mail(stripped, fallback_email=fallback_email)
    if natural_mail is not None:
        return natural_mail

    natural_alarm = _parse_natural_alarm(stripped)
    if natural_alarm is not None:
        return natural_alarm

    natural_calendar = _parse_natural_calendar(stripped)
    if natural_calendar is not None:
        return natural_calendar

    lowered = stripped.lower()

    if ("mail" in lowered or "email" in lowered) and ("résume" in lowered or "resume" in lowered):
        return {"action": "mail_resume"}

    if ("dernier" in lowered or "latest" in lowered) and ("mail" in lowered or "email" in lowered):
        return {"action": "mail_last"}

    if "disponib" in lowered and "semaine" in lowered:
        return {"action": "availability_week"}

    if ("planning" in lowered or "réunion" in lowered or "reunion" in lowered) and "semaine" in lowered:
        return {"action": "events_week"}

    return None
