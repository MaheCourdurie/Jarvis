"""Agent vision : « regarde mon écran », « qu'est-ce qu'il y a sur cette image ? » (le modèle voit les images)."""

from __future__ import annotations

import base64
import subprocess
import tempfile
from pathlib import Path

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
        subprocess.run(["sips", "-Z", str(width), "-s", "format", "jpeg", str(path), "--out", str(small)],
                       capture_output=True, timeout=30)
        source = small if small.exists() else path
        return base64.b64encode(source.read_bytes()).decode()


class VisionAgent(Agent):
    """Regarde l'écran ou une image et répond à la question posée."""

    name = "vision"
    local_only = frozenset({"look_screen"})

    def handlers(self) -> dict[str, Handler]:
        return {"look_screen": self.look_screen}

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
