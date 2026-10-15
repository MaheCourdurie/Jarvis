from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from core.agent import Agent, Handler
from persona import (
    Reply,
    TITLE,
    day_label,
    fold,
    format_date,
    format_time,
    format_when,
    period_label,
    plural,
    spoken_time,
    spoken_when,
)


DELETE_HINT = "\nPour en supprimer un : /deleteevent \"id\""


def _localize(value: datetime, timezone: Any) -> datetime:
    """Place une date sans fuseau dans le fuseau de l'utilisateur."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone)
    return value.astimezone(timezone)


def format_datetime(value: datetime) -> str:
    """Formate une date/heure dans un format lisible pour l'utilisateur."""
    return f"{format_date(value)} {format_time(value)}"


def _event_line(event: dict) -> str:
    """Formate un événement sur une ligne pour l'affichage."""
    start = event["start"]
    end = event["end"]
    if event.get("isAllDay"):
        when = f"{format_date(start)}, toute la journée"
    else:
        when = f"{format_datetime(start)} → {format_time(end)}"
    line = f"- {when} : {event['subject']} [id: {event.get('id') or '?'}]"
    if event.get("location"):
        line += f" ({event['location']})"
    return line


def _spoken_event(event: dict, now: datetime) -> str:
    """Formate un événement pour la voix (« Réunion client, demain à 10 heures »)."""
    if event.get("isAllDay"):
        return f"{event['subject']}, {day_label(event['start'], now)}, toute la journée"
    return f"{event['subject']}, {spoken_when(event['start'], now)}"


def format_week_events(events: list[dict], now: datetime) -> Reply:
    """Construit le rendu des événements de la semaine."""
    if not events:
        return Reply(text=f"Aucun événement cette semaine, {TITLE}. Votre agenda est libre.", data={"events": 0})

    lines = [f"Vos événements de la semaine, {TITLE} :"]
    lines.extend(_event_line(event) for event in events)

    speech = f"Vous avez {plural(len(events), 'rendez-vous', 'rendez-vous')} cette semaine, {TITLE}."
    upcoming = [event for event in events if event["end"] >= now]
    if upcoming:
        speech += f" Le prochain : {_spoken_event(upcoming[0], now)}."
    else:
        speech += " Ils sont tous passés."
    return Reply(text="\n".join(lines) + DELETE_HINT, speech=speech, data={"events": len(events)})


def compute_availability(events: list[dict], timezone: Any) -> Reply:
    """Calcule les créneaux libres de la semaine selon les événements existants."""
    now = datetime.now(timezone)
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

    lines = [f"Vos disponibilités cette semaine (lundi-vendredi, 9 h-18 h), {TITLE} :"]
    first_free: tuple[datetime, datetime] | None = None

    for day_offset in range(5):
        day = monday + timedelta(days=day_offset)
        work_start = day.replace(hour=9, minute=0)
        work_end = day.replace(hour=18, minute=0)

        busy = []
        for event in events:
            start = event["start"]
            end = event["end"]
            if end <= work_start or start >= work_end:
                continue
            busy.append((max(start, work_start), min(end, work_end)))

        busy.sort(key=lambda item: item[0])
        merged = []
        for interval in busy:
            if not merged or interval[0] > merged[-1][1]:
                merged.append([interval[0], interval[1]])
            else:
                merged[-1][1] = max(merged[-1][1], interval[1])

        free = []
        cursor = work_start
        for start, end in merged:
            if start > cursor:
                free.append((cursor, start))
            cursor = max(cursor, end)
        if cursor < work_end:
            free.append((cursor, work_end))

        if not free:
            lines.append(f"- {format_date(day)} : occupé")
            continue

        slots = ", ".join(f"{format_time(s)}-{format_time(e)}" for s, e in free)
        lines.append(f"- {format_date(day)} : {slots}")

        if first_free is None:
            for slot_start, slot_end in free:
                if slot_end > now:
                    first_free = (max(slot_start, now), slot_end)
                    break

    if first_free is None:
        speech = f"Je crains que votre semaine ne soit complète, {TITLE}."
    else:
        slot_start, slot_end = first_free
        if slot_start <= now:
            opening = f"Vous êtes libre dès maintenant, jusqu'à {spoken_time(slot_end)}"
        else:
            opening = (
                f"Votre premier créneau libre est {day_label(slot_start, now)}, "
                f"de {spoken_time(slot_start)} à {spoken_time(slot_end)}"
            )
        speech = f"{opening}, {TITLE}. Le détail de la semaine est à l'écran."

    return Reply(text="\n".join(lines), speech=speech)


def handle_events_week(mail_client: Any) -> Reply:
    """Retourne les événements de la semaine formatés."""
    return format_week_events(mail_client.list_week_events(), datetime.now(mail_client.timezone))


def handle_availability_week(mail_client: Any) -> Reply:
    """Retourne les disponibilités calculées à partir du calendrier."""
    return compute_availability(mail_client.list_week_events(), mail_client.timezone)


def handle_add_event(mail_client: Any, params: dict) -> Reply:
    """Crée un événement calendrier et signale un éventuel chevauchement."""
    title = params["title"]
    timezone = mail_client.timezone
    start = _localize(datetime.fromisoformat(params["start"]), timezone)
    end = _localize(datetime.fromisoformat(params["end"]), timezone)
    now = datetime.now(timezone)

    # Proactivité : on relève les événements déjà prévus sur ce créneau avant de créer.
    conflicts: list[dict] = []
    try:
        conflicts = [event for event in mail_client.list_events_in_range(start, end) if not event.get("isAllDay")]
    except Exception as exc:
        print(f"[CALENDAR] Vérification des conflits impossible: {exc}", flush=True)

    recurrence = params.get("recurrence")
    if recurrence:
        created = mail_client.create_event(title, start, end, recurrence=recurrence)
    else:
        created = mail_client.create_event(title, start, end)
    web_link = created.get("webLink") or created.get("htmlLink")

    text = f"C'est noté, {TITLE} : « {title} », {format_when(start, now)} → {format_time(end)}."
    speech = f"C'est noté, {TITLE}. {title}, {spoken_when(start, now)}."
    if recurrence:
        rhythm = params.get("rhythm") or "de façon récurrente"
        text = f"C'est noté, {TITLE} : « {title} » {rhythm}, de {format_time(start)} à {format_time(end)}. Premier : {format_when(start, now)}."
        speech = f"C'est noté, {TITLE}. {title}, {rhythm} à {spoken_when(start, now).split(' à ')[-1]}."
    if conflicts:
        other = conflicts[0]
        text += (
            f"\nJe me permets de signaler que ce créneau chevauche « {other['subject']} » "
            f"({format_time(other['start'])} → {format_time(other['end'])})."
        )
        speech += f" Je me permets de signaler que ce créneau chevauche {other['subject']}."
    if web_link:
        text += f"\nLien calendrier : {web_link}"
    return Reply(text=text, speech=speech, data={"conflicts": len(conflicts)})


def _matches(event: dict, query: str) -> bool:
    words = [word for word in fold(query).split() if len(word) > 2]
    subject = fold(event.get("subject") or "")
    return bool(words) and all(word in subject for word in words)


def handle_move_event(mail_client: Any, params: dict) -> Reply:
    """Déplace un événement trouvé par son titre (« décale le dentiste à 16h »)."""
    timezone = mail_client.timezone
    now = datetime.now(timezone)
    query = str(params.get("query") or "").strip()
    search_start = _localize(datetime.fromisoformat(params["from"]), timezone) if params.get("from") else now
    search_end = _localize(datetime.fromisoformat(params["to"]), timezone) if params.get("to") else now + timedelta(days=60)
    candidates = [event for event in mail_client.list_events_in_range(search_start, search_end) if not event.get("isAllDay")]
    found = [event for event in candidates if _matches(event, query)]
    if not found:
        return Reply(text=f"Je ne trouve pas « {query} » dans votre agenda, {TITLE}.")
    event = found[0]
    start, end = event["start"], event["end"]
    target = _localize(datetime.fromisoformat(params["target"]), timezone)
    if params.get("time_only"):
        target = start.replace(hour=target.hour, minute=target.minute)
    new_end = target + (end - start)
    mail_client.move_event(event["id"], target, new_end)
    return Reply(
        text=f"C'est fait, {TITLE} : « {event['subject']} » passe {format_when(target, now)} → {format_time(new_end)}.",
        speech=f"C'est fait, {TITLE}. {event['subject']} est déplacé {spoken_when(target, now)}.",
    )


def handle_delete_event(mail_client: Any, params: dict) -> Reply:
    """Supprime un événement par identifiant."""
    event_id = str(params.get("event_id") or "").strip()
    if not event_id:
        return Reply(text=f"Il me manque l'identifiant de l'événement, {TITLE}.")
    if mail_client.delete_event(event_id):
        return Reply(text=f"Événement supprimé, {TITLE} ({event_id}).", speech=f"Événement supprimé, {TITLE}.")
    return Reply(
        text=f"Je ne trouve aucun événement portant l'identifiant {event_id}, {TITLE}.",
        speech=f"Je ne trouve aucun événement portant cet identifiant, {TITLE}.",
    )


def handle_delete_events_range(mail_client: Any, params: dict) -> Reply:
    """Supprime les événements sur une plage de dates.

    Si params["confirm"] est vrai, rien n'est supprimé : Jarvis énumère les
    événements concernés et attend un « oui ».
    """
    timezone = mail_client.timezone
    start = _localize(datetime.fromisoformat(params["start"]), timezone)
    end = _localize(datetime.fromisoformat(params["end"]), timezone)
    period = period_label(start, end, datetime.now(timezone))

    if params.get("confirm"):
        events = mail_client.list_events_in_range(start, end)
        if not events:
            return Reply(text=f"Aucun événement à supprimer {period}, {TITLE}.")
        names = ", ".join(f"« {event['subject']} »" for event in events[:5])
        if len(events) > 5:
            names += "…"
        count = plural(len(events), "événement", "événements")
        return Reply(
            text=f"Vous avez {count} {period}, {TITLE} : {names}.\nDois-je tout supprimer ?",
            speech=f"Vous avez {count} {period}, {TITLE}. Dois-je tout supprimer ?",
            pending={
                "action": "delete_events_range",
                "params": {"start": params["start"], "end": params["end"]},
            },
        )

    count = len(mail_client.delete_events_in_range(start, end))
    if count == 0:
        return Reply(text=f"Aucun événement à supprimer {period}, {TITLE}.")
    if count == 1:
        return Reply(text=f"C'est fait, {TITLE} : l'événement prévu {period} est supprimé.")
    return Reply(text=f"C'est fait, {TITLE} : {count} événements supprimés {period}.")


def handle_events_range(mail_client: Any, params: dict) -> Reply:
    """Retourne les événements d'un jour précis ou d'une période."""
    timezone = mail_client.timezone
    start = _localize(datetime.fromisoformat(params["start"]), timezone)
    end = _localize(datetime.fromisoformat(params["end"]), timezone)
    now = datetime.now(timezone)
    period = period_label(start, end, now)
    events = mail_client.list_events_in_range(start, end)

    if not events:
        return Reply(text=f"Rien de prévu {period}, {TITLE}.", data={"events": 0})

    lines = [f"Vos événements {period}, {TITLE} :"]
    lines.extend(_event_line(event) for event in events)

    single_day = start.date() == (end - timedelta(seconds=1)).date()
    count = plural(len(events), "rendez-vous", "rendez-vous")
    speech = f"Vous avez {count} {period}, {TITLE}."
    if single_day:
        spoken = [
            f"{event['subject']}, toute la journée" if event.get("isAllDay")
            else f"{event['subject']} à {spoken_time(event['start'])}"
            for event in events[:3]
        ]
        speech += " " + " ; ".join(spoken) + "."
    else:
        speech += f" Le premier : {_spoken_event(events[0], now)}."
    return Reply(text="\n".join(lines) + DELETE_HINT, speech=speech, data={"events": len(events)})


class CalendarAgent(Agent):
    """Agenda Google : consultation, disponibilités, ajout et suppression d'événements."""

    name = "agenda"
    needs_google = True
    writes = frozenset({"add_event", "delete_event", "delete_events_range", "move_event"})
    confirmable = frozenset({"delete_events_range"})

    def handlers(self) -> dict[str, Handler]:
        google = lambda: self.context.google  # noqa: E731  (lu à chaque appel, jamais copié)
        return {
            "events_week": lambda params: handle_events_week(google()),
            "events_range": lambda params: handle_events_range(google(), params),
            "availability_week": lambda params: handle_availability_week(google()),
            "add_event": lambda params: handle_add_event(google(), params),
            "move_event": lambda params: handle_move_event(google(), params),
            "delete_event": lambda params: handle_delete_event(google(), params),
            "delete_events_range": lambda params: handle_delete_events_range(google(), params),
        }
