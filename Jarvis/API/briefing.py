"""Tableau de bord du HUD, briefing du jour et contexte en direct pour la conversation."""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timedelta
from typing import Any

from config import CITY
from persona import (
    Reply,
    TITLE,
    format_date,
    format_time,
    greeting,
    plural,
    spoken_time,
    strip_accents,
)
from system_actions import read_system_metrics, system_alerts
from weather import WeatherError, get_weather, spoken_degrees, summarize_now


GOOGLE_CACHE_SECONDS = 90

_AGENDA_HINTS = re.compile(
    r"rendez|rdv|reunion|agenda|planning|emploi du temps|prochain|libre|dispo|sieste|journee|programme|prevu|occupe"
)
_WEATHER_HINTS = re.compile(
    r"meteo|temps qu'il|temps fait|pleuv|pluie|parapluie|froid|chaud|soleil|dehors|sortir|veste|manteau|temperature|neige"
)
_SYSTEM_HINTS = re.compile(r"batterie|memoire|\bram\b|processeur|\bcpu\b|disque|ordinateur|\bmac\b|machine|systeme|\blent|rame")
_MAIL_HINTS = re.compile(r"mail|courrier|messagerie|boite de reception|non lus?")


class Dashboard:
    """Rassemble l'état du jour (météo, agenda, messagerie, alarmes) avec un cache court."""

    def __init__(self, google_client: Any, alarm_store: Any) -> None:
        self.google = google_client
        self.alarms = alarm_store
        self._lock = threading.Lock()
        self._google_cache: tuple[float, dict] | None = None

    def invalidate(self) -> None:
        """Oublie les données Google en cache (après une action qui les modifie)."""
        with self._lock:
            self._google_cache = None

    def _google_snapshot(self) -> dict:
        """Lit l'agenda du jour et les messages non lus (None si Google n'est pas connecté)."""
        empty = {"events": None, "unread": None, "unread_items": []}
        if not self.google.is_configured():
            return empty

        with self._lock:
            cached = self._google_cache
        if cached and time.time() - cached[0] < GOOGLE_CACHE_SECONDS:
            return cached[1]

        snapshot = dict(empty)
        now = datetime.now(self.google.timezone)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            events = self.google.list_events_in_range(day_start, day_start + timedelta(days=1))
            snapshot["events"] = [
                {
                    "id": event.get("id") or "",
                    "title": event["subject"],
                    "start": event["start"].isoformat(),
                    "end": event["end"].isoformat(),
                    "all_day": bool(event.get("isAllDay")),
                    "location": event.get("location") or "",
                }
                for event in events
            ]
        except Exception as exc:
            print(f"[DASHBOARD] Agenda indisponible: {exc}", flush=True)

        try:
            unread = self.google.get_unread_emails(limit=5)
            snapshot["unread"] = len(unread)
            snapshot["unread_items"] = [
                {
                    "from": item.get("from", {}).get("emailAddress", {}).get("name") or "Expéditeur inconnu",
                    "subject": item.get("subject") or "(sans objet)",
                }
                for item in unread[:3]
            ]
        except Exception as exc:
            print(f"[DASHBOARD] Messagerie indisponible: {exc}", flush=True)

        with self._lock:
            self._google_cache = (time.time(), snapshot)
        return snapshot

    def snapshot(self) -> dict:
        """Retourne l'état complet affiché par les panneaux du HUD."""
        now = datetime.now(self.google.timezone)
        try:
            weather = get_weather()
        except WeatherError as exc:
            print(f"[DASHBOARD] Météo indisponible: {exc}", flush=True)
            weather = None

        data = {
            "time": now.isoformat(),
            "city": CITY,
            "weather": weather,
            "google": self.google.is_configured(),
            "alarms": [
                {"id": item.get("id"), "label": item.get("label"), "when": item.get("when")}
                for item in self.alarms.list_alarms()
            ],
        }
        data.update(self._google_snapshot())
        return data


def _upcoming_events(snapshot: dict, now: datetime) -> list[dict]:
    """Garde les événements du jour qui ne sont pas encore terminés."""
    upcoming = []
    for event in snapshot.get("events") or []:
        try:
            end = datetime.fromisoformat(event["end"])
        except (KeyError, ValueError):
            continue
        if end >= now:
            upcoming.append(event)
    return upcoming


def _event_time(event: dict) -> datetime:
    return datetime.fromisoformat(event["start"])


def _agenda_sentences(snapshot: dict, now: datetime) -> tuple[str, str]:
    """Résume l'agenda restant du jour : (texte affiché, texte oral)."""
    upcoming = _upcoming_events(snapshot, now)
    if not upcoming:
        sentence = "Votre agenda est libre pour le reste de la journée."
        return sentence, sentence

    first = upcoming[0]
    count = plural(len(upcoming), "rendez-vous", "rendez-vous")
    if first.get("all_day"):
        text = speech = f"Vous avez {count} aujourd'hui, dont « {first['title']} » toute la journée."
        return text, speech

    start = _event_time(first)
    lead = "Il vous reste" if len(upcoming) > 1 else "Vous avez"
    if len(upcoming) == 1:
        text = f"{lead} un rendez-vous aujourd'hui : « {first['title']} » à {format_time(start)}."
        speech = f"{lead} un rendez-vous aujourd'hui : {first['title']}, à {spoken_time(start)}."
    else:
        text = f"{lead} {count} aujourd'hui ; le prochain, « {first['title']} », est à {format_time(start)}."
        speech = f"{lead} {count} aujourd'hui. Le prochain, {first['title']}, est à {spoken_time(start)}."
    return text, speech


def _mail_sentence(snapshot: dict) -> str | None:
    unread = snapshot.get("unread")
    if unread is None:
        return None
    if unread == 0:
        return "Aucun message non lu."
    if unread == 1:
        return "Un message non lu vous attend."
    more = "Au moins " if unread >= 5 else ""
    return f"{more}{unread} messages non lus vous attendent."


def build_briefing(dashboard: Dashboard, kind: str = "full") -> Reply:
    """Compose le briefing façon Jarvis : heure, météo, agenda, messagerie, points d'attention.

    kind="boot" : version courte prononcée au démarrage du HUD.
    kind="full" : version complète, sur demande (« fais-moi le point »).
    """
    snapshot = dashboard.snapshot()
    now = datetime.fromisoformat(snapshot["time"])
    hello = f"{greeting(now)}, {TITLE}."

    text_parts = [hello, f"Il est {format_time(now)}."]
    speech_parts = [hello, f"Il est {spoken_time(now)}."]

    weather = snapshot.get("weather")
    if weather:
        if kind == "boot":
            text_parts.append(f"À {weather['city']}, {weather['temperature']} °C, {weather['description']}.")
            speech_parts.append(
                f"À {weather['city']}, il fait {spoken_degrees(weather['temperature'])}, {weather['description']}."
            )
        else:
            weather_text, weather_speech = summarize_now(weather)
            text_parts.append(weather_text)
            speech_parts.append(weather_speech)

    if snapshot.get("events") is not None:
        agenda_text, agenda_speech = _agenda_sentences(snapshot, now)
        text_parts.append(agenda_text)
        speech_parts.append(agenda_speech)
    elif kind == "full":
        note = "La liaison Google n'est pas établie : agenda et messagerie sont hors de ma portée."
        text_parts.append(note)
        speech_parts.append(note)

    mail = _mail_sentence(snapshot)
    if mail and (kind == "full" or (snapshot.get("unread") or 0) > 0):
        text_parts.append(mail)
        speech_parts.append(mail)

    alarms = snapshot.get("alarms") or []
    if alarms and kind == "full":
        note = f"{plural(len(alarms), 'alarme active', 'alarmes actives')}."
        text_parts.append(note)
        speech_parts.append(note)

    alerts = system_alerts(read_system_metrics())
    text_parts.extend(alerts)
    speech_parts.extend(alerts)
    if not alerts and kind == "full":
        text_parts.append("Tous les systèmes sont opérationnels.")
        speech_parts.append("Tous les systèmes sont opérationnels.")

    return Reply(text=" ".join(text_parts), speech=" ".join(speech_parts), data=snapshot)


def live_context(dashboard: Dashboard, message: str) -> str:
    """Construit le contexte en direct transmis au modèle pour la conversation.

    Seules les données en rapport avec la question sont fournies : un petit modèle
    a tendance à réciter tout ce qu'on lui donne.
    """
    now = datetime.now(dashboard.google.timezone)
    lines = [
        f"Contexte en direct : nous sommes le {format_date(now)} {now.year}, il est {format_time(now)}. "
        f"Ville de l'utilisateur : {CITY}."
    ]

    folded = strip_accents((message or "").lower())
    wants_agenda = bool(_AGENDA_HINTS.search(folded))
    wants_weather = bool(_WEATHER_HINTS.search(folded))
    wants_system = bool(_SYSTEM_HINTS.search(folded))
    wants_mail = bool(_MAIL_HINTS.search(folded))
    if not (wants_agenda or wants_weather or wants_system or wants_mail):
        return lines[0]

    try:
        snapshot = dashboard.snapshot()
    except Exception as exc:
        print(f"[DASHBOARD] Contexte indisponible: {exc}", flush=True)
        return lines[0]

    if wants_agenda:
        if snapshot.get("events") is None:
            lines.append("Agenda : non connecté (la liaison Google n'est pas établie).")
        else:
            upcoming = _upcoming_events(snapshot, now)
            if upcoming:
                items = "; ".join(
                    "{} {}".format(
                        "toute la journée" if event.get("all_day") else format_time(_event_time(event)),
                        event["title"],
                    )
                    for event in upcoming
                )
                lines.append(f"Agenda restant aujourd'hui : {items}.")
            else:
                lines.append("Agenda restant aujourd'hui : aucun événement.")

    if wants_weather and snapshot.get("weather"):
        lines.append("Météo : " + summarize_now(snapshot["weather"])[0])

    if wants_mail:
        mail = _mail_sentence(snapshot)
        lines.append(f"Messagerie : {mail}" if mail else "Messagerie : non connectée.")

    if wants_system:
        metrics = read_system_metrics()
        if metrics.get("cpu_percent") is not None:
            parts = [f"processeur {metrics['cpu_percent']} %", f"mémoire {metrics['memory']['percent']} %"]
            battery = metrics.get("battery")
            if battery:
                source = "sur secteur" if battery["plugged"] else "sur batterie"
                parts.append(f"batterie {battery['percent']} % {source}")
            lines.append("État du poste : " + ", ".join(parts) + ".")

    return "\n".join(lines)
