"""Qui a le droit de parler à l'API : ce poste, ou un appareil muni du code d'accès."""

from __future__ import annotations

import hmac
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from config import ACCESS_TOKEN, EXTRA_ALLOWED_ORIGINS

# Seules les pages servies depuis ce poste peuvent piloter l'API : Jarvis envoie des
# mails et agit sur l'ordinateur, il ne doit pas obéir à un site web quelconque.
LOCAL_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
LOCAL_HOSTS = {"localhost", "127.0.0.1"}
# En-têtes posés par un relais (Tailscale, proxy) : la requête vient alors d'un autre appareil.
FORWARDING_HEADERS = {"x-forwarded-for", "x-forwarded-host", "forwarded", "tailscale-user-login"}


def allowed_hosts() -> list[str]:
    """Noms d'hôte acceptés : ce poste, plus ceux des origines explicitement autorisées."""
    hosts = {"localhost", "127.0.0.1"}
    for origin in EXTRA_ALLOWED_ORIGINS:
        hostname = urlparse(origin).hostname
        if hostname:
            hosts.add(hostname)
    return sorted(hosts)


def is_remote_request(headers: dict) -> bool:
    """Vrai si la requête ne vient pas directement de ce poste (autre nom d'hôte, ou relayée)."""
    host = headers.get("host", "").rsplit(":", 1)[0].lower()
    return host not in LOCAL_HOSTS or any(name in headers for name in FORWARDING_HEADERS)


class RemoteAccessGuard:
    """Exige le code d'accès (JARVIS_ACCESS_TOKEN) pour tout appel à l'API venu d'un autre appareil.

    Le HUD lui-même (fichiers statiques) reste accessible : il ne contient rien de personnel,
    et c'est lui qui demande le code avant de parler à l'API.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith("/api/"):
            headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
            if is_remote_request(headers):
                supplied = headers.get("x-jarvis-token", "")
                if not ACCESS_TOKEN:
                    problem = (403, "Accès à distance désactivé : lancez ./run_jarvis.sh phone sur le Mac.")
                elif not hmac.compare_digest(supplied.encode(), ACCESS_TOKEN.encode()):
                    problem = (401, "Code d'accès requis.")
                else:
                    problem = None
                if problem:
                    await JSONResponse({"detail": problem[1]}, status_code=problem[0])(scope, receive, send)
                    return
        await self.app(scope, receive, send)


def protect(app: FastAPI, *inner_middlewares: tuple) -> None:
    """Pose les protections, de la plus profonde à la plus externe.

    Les intergiciels passés en plus (classe, options) se placent entre le code d'accès
    et le contrôle du nom d'hôte.
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=EXTRA_ALLOWED_ORIGINS,
        allow_origin_regex=LOCAL_ORIGIN_REGEX,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Jarvis-Token"],
    )
    app.add_middleware(RemoteAccessGuard)
    for middleware, options in inner_middlewares:
        app.add_middleware(middleware, **options)
    # Refuse les requêtes adressées à un autre nom d'hôte (protection contre le DNS rebinding).
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts())
