"""Agent vision : « regarde mon écran », « qu'est-ce qu'il y a sur cette image ? » (le modèle voit les images)."""

from __future__ import annotations

import base64
import shutil
import subprocess
import tempfile
from pathlib import Path

from agents import files
from agents.system import SYSTEM, _run, _unsupported
from core.agent import Agent, Handler
from persona import Reply, TITLE
from services import llm

PROMPT = (
    "Tu es J.A.R.V.I.S. et tu regardes l'écran de l'utilisateur (ou l'image qu'il te montre). "
    "Réponds en français, brièvement et précisément, à sa question. Décris ce que tu vois vraiment ; "
    "si un texte est illisible, dis-le plutôt que d'inventer."
)


def _encode(path: Path, width: int = 1280) -> str:
    """Réduit l'image (le modèle n'a pas besoin de la pleine résolution) et l'encode en base64."""
    with tempfile.TemporaryDirectory(prefix="jarvis-vue-") as folder:
        small = Path(folder) / "vue.jpg"
        if shutil.which("sips"):
            subprocess.run(["sips", "-Z", str(width), "-s", "format", "jpeg", str(path), "--out", str(small)],
                           capture_output=True, timeout=30)
        source = small if small.exists() else path
        return base64.b64encode(source.read_bytes()).decode()


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".gif", ".webp", ".tif", ".tiff", ".bmp"}


class VisionAgent(Agent):
    """Regarde l'écran ou une image et répond à la question posée."""

    name = "vision"
    local_only = frozenset({"look_screen"})

    def handlers(self) -> dict[str, Handler]:
        return {"look_screen": self.look_screen, "look_image": self.look_image}

    def look_image(self, params: dict) -> Reply:
        """« Décris la photo plage.jpg » : une image du Mac, retrouvée par son nom."""
        query = str(params.get("query") or "").strip(" «»\"'.?!")
        candidate = Path(query).expanduser()
        found = [candidate] if candidate.is_absolute() and candidate.is_file() else files.find(query, limit=10)
        images = [path for path in found if path.suffix.lower() in IMAGE_SUFFIXES]
        if not images:
            return Reply(text=f"Je ne trouve aucune image nommée « {query} » sur ce Mac, {TITLE}.")
        question = str(params.get("question") or "").strip() or "Décris cette image."
        try:
            answer = llm.complete(PROMPT, question, 0.2, 400, timeout=120, images=[_encode(images[0])])
        except Exception as exc:
            print(f"[VISION] {exc}", flush=True)
            return Reply(text=f"Je n'arrive pas à analyser {images[0].name}, {TITLE}.")
        answer = llm.clean_reply(answer)
        return Reply(text=f"{images[0].name} :\n\n{answer}", speech=answer, data={"path": str(images[0])})

    def look_screen(self, params: dict) -> Reply:
        if SYSTEM != "darwin":
            return _unsupported("la vision de l'écran")
        question = str(params.get("question") or "").strip() or "Que vois-tu sur mon écran ?"
        with tempfile.TemporaryDirectory(prefix="jarvis-ecran-") as folder:
            shot = Path(folder) / "ecran.png"
            ok, detail = _run(["screencapture", "-x", "-m", str(shot)])
            if not ok or not shot.exists():
                print(f"[VISION] Capture impossible: {detail}", flush=True)
                return Reply(text=f"Je ne parviens pas à voir l'écran, {TITLE}. Autorisez l'enregistrement de l'écran dans Réglages Système › Confidentialité et sécurité.")
            image = _encode(shot)
        try:
            answer = llm.complete(PROMPT, question, 0.2, 400, timeout=120, images=[image])
        except Exception as exc:
            print(f"[VISION] {exc}", flush=True)
            return Reply(text=f"Je n'arrive pas à analyser l'écran, {TITLE}.")
        answer = llm.clean_reply(answer)
        return Reply(text=answer, speech=answer)
