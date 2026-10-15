"""Jarvis à la demande : il ne tourne que lorsqu'on s'en sert.

macOS (launchd) surveille le port de Jarvis et ne le lance qu'à la première connexion : ouverture
de l'app, du site, ou « Lancer » dans Telegram. Jarvis s'arrête ensuite de lui-même après un moment
sans aucune demande ; le port reste surveillé, et la demande suivante le relance.
"""

from __future__ import annotations

import ctypes
import socket
import sys
import threading
import time
from typing import Callable


def launchd_sockets(name: str = "Listeners") -> list[socket.socket]:
    """Sockets ouverts par launchd pour un démarrage à la demande ; [] si Jarvis a été lancé à la main."""
    if sys.platform != "darwin":
        return []
    try:
        libc = ctypes.CDLL(None)
        fds = ctypes.POINTER(ctypes.c_int)()
        count = ctypes.c_size_t(0)
        if libc.launch_activate_socket(name.encode(), ctypes.byref(fds), ctypes.byref(count)) != 0:
            return []
        sockets = [socket.socket(fileno=fds[index]) for index in range(count.value)]
        libc.free(fds)
        return sockets
    except (OSError, AttributeError, ValueError):
        return []


class Activity:
    """Dernière demande reçue, et demandes en cours (une réponse en flux compte jusqu'à sa fin)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.last = clock()
        self.in_flight = 0
        self._lock = threading.Lock()

    def begin(self) -> None:
        with self._lock:
            self.in_flight += 1
            self.last = self.clock()

    def end(self) -> None:
        with self._lock:
            self.in_flight = max(0, self.in_flight - 1)
            self.last = self.clock()

    def idle_for(self) -> float:
        """Secondes écoulées depuis la dernière demande (0 tant qu'une demande est en cours)."""
        with self._lock:
            return 0.0 if self.in_flight else self.clock() - self.last


class ActivityTracker:
    """Middleware ASGI : chaque requête compte. Le HUD ouvert en envoie toutes les 3 secondes,
    si bien que Jarvis ne s'arrête jamais tant qu'une interface est ouverte quelque part."""

    def __init__(self, app, activity: Activity):
        self.app = app
        self.activity = activity

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        self.activity.begin()
        try:
            await self.app(scope, receive, send)
        finally:
            self.activity.end()


def should_sleep(idle_seconds: float, idle_minutes: int, alarms_pending: bool) -> bool:
    """Jarvis peut-il s'arrêter ? Jamais si une alarme attend : c'est lui qui doit la faire sonner."""
    return idle_minutes > 0 and not alarms_pending and idle_seconds >= idle_minutes * 60


def watch_idle(
    activity: Activity,
    idle_minutes: int,
    alarms_pending: Callable[[], bool],
    go_to_sleep: Callable[[], None],
    interval: float = 30,
) -> threading.Thread:
    """Surveille l'inactivité en tâche de fond et appelle go_to_sleep() le moment venu."""

    def loop() -> None:
        while True:
            time.sleep(interval)
            if should_sleep(activity.idle_for(), idle_minutes, alarms_pending()):
                go_to_sleep()
                return

    thread = threading.Thread(target=loop, daemon=True, name="jarvis-idle")
    thread.start()
    return thread
