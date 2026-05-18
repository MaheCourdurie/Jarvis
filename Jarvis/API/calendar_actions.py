from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def format_datetime(value: datetime) -> str:
    """Formate une date/heure dans un format lisible pour l'utilisateur."""
    return value.strftime("%A %d/%m %H:%M")


def format_week_events(events: list[dict]) -> str:
    """Construit le rendu texte des événements de la semaine."""
    if not events:
        return " Aucun événement cette semaine."

    lines = [" Événements de la semaine :"]
    for event in events:
        start = event["start"]
        end = event["end"]
        subject = event["subject"]
        event_id = event.get("id") or "?"
        location = event.get("location")
        line = f"- {format_datetime(start)} -> {end.strftime('%H:%M')} : {subject} [id: {event_id}]"
        if location:
            line += f" ({location})"
        lines.append(line)
    lines.append("\nUtilise /deleteevent \"id\" pour supprimer un événement.")
    return "\n".join(lines)


def compute_availability(events: list[dict], timezone: Any) -> str:
    """Calcule les créneaux libres de la semaine selon les événements existants."""
    now = datetime.now(timezone)
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

    lines = [" Tes disponibilités (lun-ven, 09:00-18:00) :"]
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

        day_name = day.strftime("%A")
        if not free:
            lines.append(f"- {day_name}: occupé")
            continue

        slots = ", ".join(f"{s.strftime('%H:%M')}-{e.strftime('%H:%M')}" for s, e in free)
        lines.append(f"- {day_name}: {slots}")

    return "\n".join(lines)


def handle_events_week(mail_client: Any) -> str:
    """Retourne les événements de la semaine formatés."""
    return format_week_events(mail_client.list_week_events())


def handle_availability_week(mail_client: Any) -> str:
    """Retourne les disponibilités calculées à partir du calendrier."""
    return compute_availability(mail_client.list_week_events(), mail_client.timezone)


def handle_add_event(mail_client: Any, params: dict) -> str:
    """Crée un événement calendrier."""
    title = params["title"]
    start = datetime.fromisoformat(params["start"])
    end = datetime.fromisoformat(params["end"])
    created = mail_client.create_event(title, start, end)
    web_link = created.get("webLink") or created.get("htmlLink")
    reply = f" Événement créé: {title} ({start.strftime('%d/%m %H:%M')} -> {end.strftime('%H:%M')})"
    if web_link:
        reply += f"\nLien calendrier: {web_link}"
    return reply


def handle_delete_event(mail_client: Any, params: dict) -> str:
    """Supprime un événement par identifiant."""
    event_id = str(params.get("event_id") or "").strip()
    if not event_id:
        return "Identifiant d'événement manquant."
    deleted = mail_client.delete_event(event_id)
    if deleted:
        return f"Événement supprimé: {event_id}"
    return f"Aucun événement trouvé pour: {event_id}"


def handle_delete_events_range(mail_client: Any, params: dict) -> str:
    """Supprime les événements sur une plage de dates."""
    start = datetime.fromisoformat(params["start"])
    end = datetime.fromisoformat(params["end"])
    deleted_events = mail_client.delete_events_in_range(start, end)
    count = len(deleted_events)

    period_start = start.strftime("%d/%m/%Y")
    period_end = (end - timedelta(seconds=1)).strftime("%d/%m/%Y")

    if count == 0:
        if period_start == period_end:
            return f"Aucun événement trouvé à supprimer le {period_start}."
        return f"Aucun événement trouvé à supprimer entre le {period_start} et le {period_end}."

    if period_start == period_end:
        return f"{count} événement(s) supprimé(s) le {period_start}."
    return f"{count} événement(s) supprimé(s) entre le {period_start} et le {period_end}."


def handle_events_range(mail_client: Any, params: dict) -> str:
    """Retourne les événements d'un jour précis ou d'une période."""
    start = datetime.fromisoformat(params["start"])
    end = datetime.fromisoformat(params["end"])
    events = mail_client.list_events_in_range(start, end)

    period_start = start.strftime("%d/%m/%Y")
    period_end = (end - timedelta(seconds=1)).strftime("%d/%m/%Y")

    if not events:
        if period_start == period_end:
            return f"Aucun événement trouvé le {period_start}."
        return f"Aucun événement trouvé entre le {period_start} et le {period_end}."

    lines = []
    if period_start == period_end:
        lines.append(f"Événements du {period_start} :")
    else:
        lines.append(f"Événements entre le {period_start} et le {period_end} :")

    for event in events:
        start_dt = event["start"]
        end_dt = event["end"]
        subject = event["subject"]
        event_id = event.get("id") or "?"
        location = event.get("location")
        line = f"- {start_dt.strftime('%A %d/%m %H:%M')} -> {end_dt.strftime('%H:%M')} : {subject} [id: {event_id}]"
        if location:
            line += f" ({location})"
        lines.append(line)

    lines.append("\nUtilise /deleteevent \"id\" pour supprimer un événement.")
    return "\n".join(lines)
