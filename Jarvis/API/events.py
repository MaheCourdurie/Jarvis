"""File d'événements proactifs (alarmes, alertes) que le HUD vient relever.

Le HUD interroge /api/events toutes les quelques secondes : c'est ce qui permet
à Jarvis de prendre la parole de lui-même (« Monsieur, il est 7 heures 30. »).
"""

from __future__ import annotations

import threading
import time
from collections import deque


_lock = threading.Lock()
_events: deque = deque(maxlen=100)
_next_id = 1
_last_poll = 0.0


def publish(kind: str, **payload) -> dict:
    """Ajoute un événement à la file et le renvoie avec son identifiant."""
    global _next_id
    with _lock:
        event = {"id": _next_id, "type": kind, "time": time.time(), **payload}
        _next_id += 1
        _events.append(event)
    return event


def last_id() -> int:
    """Identifiant du dernier événement publié (0 si aucun)."""
    with _lock:
        return _next_id - 1


def events_after(after_id: int) -> list[dict]:
    """Retourne les événements plus récents que after_id et note le passage du HUD."""
    global _last_poll
    with _lock:
        _last_poll = time.time()
        return [event for event in _events if event["id"] > after_id]


def hud_is_listening(max_age: float = 8.0) -> bool:
    """Indique si un HUD a relevé les événements récemment (il annoncera donc lui-même)."""
    with _lock:
        return (time.time() - _last_poll) <= max_age
