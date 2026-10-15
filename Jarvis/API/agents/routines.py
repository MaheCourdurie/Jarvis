"""Agent routines : « mode travail », « routine bonne nuit » — des phrases que Jarvis exécute à la suite.

Une routine est une simple liste de phrases, comme on les dirait à Jarvis :
    {"travail": ["active ne pas déranger", "ouvre Visual Studio Code", "mets le volume à 30"]}
Jarvis confie chaque étape à l'agent compétent, avec les mêmes règles que si on la disait.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Callable, Optional

from config import ROUTINES_FILE
from core.agent import Agent, Handler
from persona import Reply, TITLE, fold, plural

DEFAULT_ROUTINES = {
    "travail": ["active ne pas déranger", "ouvre Visual Studio Code", "mets le volume à 30"],
    "pause": ["mets la musique en pause", "mets le volume à 20"],
    "bonne nuit": ["mets la musique en pause", "quelles sont mes alarmes", "mets l'écran en veille"],
    "matin": ["fais-moi un briefing", "quelle est la météo aujourd'hui"],
}


class RoutineAgent(Agent):
    """Exécute, liste et enregistre des routines."""

    name = "routines"
    needs_origin = True

    def __init__(self, context, path: Path = ROUTINES_FILE) -> None:
        self.path = path
        self._lock = threading.Lock()
        # Branché par main.py une fois Jarvis créé : exécute une phrase comme si on la disait.
        self.dispatch: Optional[Callable[[str, bool], dict]] = None
        super().__init__(context)

    def handlers(self) -> dict[str, Handler]:
        return {"run_routine": self.run_routine, "list_routines": self.list_routines, "create_routine": self.create_routine}

    def routines(self) -> dict[str, list[str]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(name): [str(step) for step in steps] for name, steps in data.items() if isinstance(steps, list)}
        except (OSError, ValueError):
            pass
        return dict(DEFAULT_ROUTINES)

    def _find(self, name: str) -> Optional[tuple[str, list[str]]]:
        wanted = fold(name).strip(" .!?")
        routines = self.routines()
        for key, steps in routines.items():
            if fold(key) == wanted:
                return key, steps
        for key, steps in routines.items():
            if fold(key) in wanted or wanted in fold(key):
                return key, steps
        return None

    def run_routine(self, params: dict) -> Reply:
        found = self._find(str(params.get("name") or ""))
        if found is None:
            names = ", ".join(self.routines())
            return Reply(text=f"Je ne connais pas cette routine, {TITLE}. Vos routines : {names}.")
        if self.dispatch is None:
            return Reply(text=f"Les routines ne sont pas encore branchées, {TITLE}.")
        name, steps = found
        lines, failures = [], 0
        for step in steps:
            result = self.dispatch(step, bool(params.get("remote")))
            reply = (result.get("reply") or "").splitlines()[0] if result else ""
            if not result or result.get("pending") or not result.get("action"):
                failures += 1
                reply = reply or "non exécutée"
            lines.append(f"- {step} → {reply}")
        speech = f"Routine {name} exécutée, {TITLE}."
        if failures:
            speech = f"Routine {name} exécutée, {TITLE}, sauf {plural(failures, 'étape')} : le détail est à l'écran."
        return Reply(text=f"Routine « {name} », {TITLE} :\n" + "\n".join(lines), speech=speech)

    def list_routines(self, params: dict) -> Reply:
        routines = self.routines()
        lines = [f"- {name} : " + " · ".join(steps) for name, steps in routines.items()]
        return Reply(
            text=f"Vos routines, {TITLE} (dites « lance la routine … ») :\n" + "\n".join(lines) + f"\nFichier : {self.path}",
            speech=f"Vous avez {plural(len(routines), 'routine')}, {TITLE} : {', '.join(routines)}.",
        )

    def create_routine(self, params: dict) -> Reply:
        name = str(params.get("name") or "").strip(" .:").lower()
        steps = [step.strip(" .") for step in re.split(r",|;|\bpuis\b|\bet ensuite\b", str(params.get("steps") or "")) if step.strip(" .")]
        if not name or not steps:
            return Reply(text=f"Dites par exemple, {TITLE} : crée une routine soirée : baisse le son, puis ouvre Spotify.")
        with self._lock:
            routines = self.routines()
            routines[name] = steps
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(routines, ensure_ascii=False, indent=2), encoding="utf-8")
        return Reply(
            text=f"Routine « {name} » enregistrée, {TITLE} :\n" + "\n".join(f"{i}. {step}" for i, step in enumerate(steps, 1)),
            speech=f"Routine {name} enregistrée, {TITLE}, avec {plural(len(steps), 'étape')}.",
        )
