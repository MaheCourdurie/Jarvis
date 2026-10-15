"""Prévenir avant un rendez-vous : « Monsieur, le dentiste est à 15 h ; comptez 22 minutes de trajet. »

Le veilleur relit l'agenda des prochaines heures toutes les quelques minutes. Pour un
rendez-vous qui a un lieu, il calcule le trajet depuis la maison (agent trajets) : Jarvis
prévient au moment de partir, avec une marge. Sans lieu, il prévient quelques minutes avant.
L'annonce passe par le HUD s'il est ouvert, sinon par les haut-parleurs du Mac.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from config import CITY, HOME_ADDRESS, MEETING_REMINDER_MINUTES
from persona import TITLE, fold, spoken_time
from services import events, voice

# Fenêtre d'agenda relue, et fréquence de relecture (Google n'est pas interrogé à chaque tour).
LOOKAHEAD = timedelta(hours=3)
REFRESH_SECONDS = 300
TICK_SECONDS = 30
# Un lieu « en visio » ou un lien ne demande pas de trajet.
_NO_TRIP = ("visio", "zoom", "teams", "meet", "skype", "telephone", "en ligne", "http", "discord", "domicile", "maison")


def needs_trip(location: str) -> bool:
    folded = fold(location or "").strip()
    return bool(folded) and not any(word in folded for word in _NO_TRIP)


def notice_time(start: datetime, travel_seconds: Optional[float], lead_minutes: int) -> datetime:
    """Le moment de prévenir : départ (trajet + marge) ou quelques minutes avant le début."""
    return start - timedelta(seconds=travel_seconds or 0) - timedelta(minutes=lead_minutes)


def notice_phrase(event: dict, start: datetime, travel_seconds: Optional[float], now: datetime) -> tuple[str, str]:
    """(texte affiché, phrase dite) pour un rendez-vous qui approche."""
    from agents.travel import spoken_duration

    title = event.get("subject") or "Votre rendez-vous"
    place = (event.get("location") or "").split(",")[0].strip()
    minutes_left = max(0, round((start - now).total_seconds() / 60))
    at = spoken_time(start)
    where = f" ({place})" if place else ""
    if travel_seconds:
        trip = spoken_duration(travel_seconds)
        text = f"{title}{where} à {start:%H:%M} : comptez {trip} de trajet. Il est temps de partir, {TITLE}."
        speech = f"{TITLE}, {title} est à {at}. Comptez {trip} de trajet : il serait temps de partir."
    else:
        soon = "maintenant" if minutes_left <= 1 else f"dans {minutes_left} minutes"
        text = f"{title}{where} commence {soon} ({start:%H:%M}), {TITLE}."
        speech = f"{TITLE}, {title} commence {soon}."
    return text, speech


class MeetingWatcher:
    """Relit l'agenda et prévient une fois par rendez-vous."""

    def __init__(
        self,
        google: Callable[[], Any],
        travel_seconds: Optional[Callable[[str], Optional[float]]] = None,
        lead_minutes: int = MEETING_REMINDER_MINUTES,
    ) -> None:
        self.google = google
        self.travel_seconds = travel_seconds or trip_from_home
        self.lead_minutes = lead_minutes
        self.notified: set[str] = set()
        self._events: list[dict] = []
        self._read_at = 0.0
        self._trips: dict[str, Optional[float]] = {}

    def upcoming(self, now: datetime) -> list[dict]:
        """Les rendez-vous des prochaines heures (agenda relu toutes les 5 minutes)."""
        client = self.google()
        if client is None or not client.is_configured():
            return []
        if time.monotonic() - self._read_at > REFRESH_SECONDS or not self._read_at:
            try:
                self._events = client.list_events_in_range(now, now + LOOKAHEAD)
            except Exception as exc:
                print(f"[RDV] Agenda illisible: {exc}", flush=True)
                self._events = []
            self._read_at = time.monotonic()
        return [event for event in self._events if not event.get("isAllDay")]

    def trip(self, location: str) -> Optional[float]:
        if not needs_trip(location):
            return None
        if location not in self._trips:
            try:
                self._trips[location] = self.travel_seconds(location)
            except Exception as exc:
                print(f"[RDV] Trajet incalculable vers « {location} »: {exc}", flush=True)
                self._trips[location] = None
        return self._trips[location]

    def due(self, now: datetime) -> list[tuple[str, str]]:
        """Les annonces à faire maintenant (chaque rendez-vous n'est annoncé qu'une fois)."""
        if self.lead_minutes <= 0:
            return []
        notices = []
        for event in self.upcoming(now):
            key = f"{event.get('id')}@{event['start'].isoformat()}"
            start = event["start"].astimezone(now.tzinfo) if now.tzinfo else event["start"]
            if key in self.notified or start <= now:
                continue
            travel = self.trip(event.get("location") or "")
            if now >= notice_time(start, travel, self.lead_minutes):
                self.notified.add(key)
                notices.append(notice_phrase(event, start, travel, now))
        return notices

    def soon(self, now: datetime, within: timedelta = timedelta(hours=1)) -> bool:
        """Un rendez-vous approche : Jarvis (lancé à la demande) reste allumé pour prévenir."""
        if self.lead_minutes <= 0:
            return False
        return any(now < event["start"] <= now + within for event in self._events if not event.get("isAllDay"))

    def loop(self, timezone: Any) -> None:
        while True:
            try:
                for text, speech in self.due(datetime.now(timezone)):
                    print(f"[RDV] {text}", flush=True)
                    events.publish("notice", label="Rendez-vous", text=text, speech=speech)
                    if not events.hud_is_listening():
                        voice.speak_local(speech)
            except Exception as exc:
                print(f"[RDV] Veilleur en erreur: {exc}", flush=True)
            time.sleep(TICK_SECONDS)

    def start(self, timezone: Any) -> None:
        if self.lead_minutes <= 0:
            return
        threading.Thread(target=self.loop, args=(timezone,), daemon=True, name="jarvis-rendez-vous").start()
        print(f"[RDV] Veilleur lancé : prévient {self.lead_minutes} min avant le départ", flush=True)


def trip_from_home(location: str) -> Optional[float]:
    """Durée du trajet en voiture depuis la maison (secondes)."""
    from agents.travel import locate, route

    origin = locate(HOME_ADDRESS or CITY)
    seconds, _meters = route(origin, locate(location, near=origin), "voiture")
    return seconds
