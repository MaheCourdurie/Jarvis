"""Établir ou couper la liaison avec le compte Google (Gmail + Agenda)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.agent import Context
from persona import TITLE
from services.google_client import GoogleApiError, GoogleConfigError


def router(context: Context) -> APIRouter:
    routes = APIRouter(prefix="/api/google")

    @routes.post("/connect")
    def api_google_connect() -> dict:
        """Lance le flux OAuth Google et enregistre le token local."""
        try:
            token_path = context.google.setup_oauth_token()
            context.dashboard.invalidate()
            return {
                "ok": True,
                "message": f"Liaison Google établie, {TITLE}.",
                "token_path": token_path,
                "mail": context.google.status(),
            }
        except GoogleConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @routes.post("/disconnect")
    def api_google_disconnect() -> dict:
        """Révoque la connexion Google et supprime le token local."""
        try:
            result = context.google.disconnect(revoke=True)
            context.dashboard.invalidate()
            return {
                "ok": True,
                "message": f"Liaison Google coupée, {TITLE}.",
                "result": result,
                "mail": context.google.status(),
            }
        except GoogleConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except GoogleApiError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return routes
