"""Les créations de l'atelier, consultables depuis le téléphone (pages, logos, documents, code).

Elles restent sur le Mac (JARVIS_CREATIONS_DIR) ; l'API les sert telles quelles. Comme toute
l'API, ces adresses exigent le code d'accès quand la demande vient d'un autre appareil.
"""

from __future__ import annotations

import mimetypes
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from agents.atelier import Workshop

PREFIX = "/api/creations"
# Le code s'affiche comme du texte dans le navigateur du téléphone, au lieu d'être téléchargé.
AS_TEXT = {".py", ".js", ".ts", ".sh", ".swift", ".java", ".kt", ".c", ".cpp", ".rs", ".go", ".php", ".rb", ".lua", ".sql", ".json", ".applescript", ".md", ".txt"}


def creation_url(path: Path, root: Path) -> str | None:
    """L'adresse d'une création (None si elle n'est pas dans le dossier des créations)."""
    try:
        relative = Path(path).resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return f"{PREFIX}/{quote(relative.as_posix())}"


def router(workshop: Workshop) -> APIRouter:
    routes = APIRouter(prefix=PREFIX)

    @routes.get("")
    def list_creations() -> dict:
        """Les dernières créations, avec leur adresse."""
        return {
            "creations": [
                {
                    "name": path.name,
                    "folder": path.parent.name,
                    "url": creation_url(path, workshop.root),
                    "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="minutes"),
                }
                for path in workshop.recent(limit=30)
            ]
        }

    @routes.get("/{relative:path}")
    def creation_file(relative: str) -> FileResponse:
        root = workshop.root.resolve()
        target = (root / relative).resolve()
        # Rien en dehors du dossier des créations, ni fichier caché.
        if not target.is_relative_to(root) or not target.is_file() or any(part.startswith(".") for part in target.relative_to(root).parts):
            raise HTTPException(status_code=404, detail="Création introuvable.")
        media = "text/plain; charset=utf-8" if target.suffix.lower() in AS_TEXT else (mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        return FileResponse(target, media_type=media, headers={"Cache-Control": "no-store"})

    return routes
