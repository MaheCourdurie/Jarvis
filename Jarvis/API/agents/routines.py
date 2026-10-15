"""Agent routines : « mode travail », « routine bonne nuit » — des phrases que Jarvis exécute à la suite.

Une routine est une simple liste de phrases, comme on les dirait à Jarvis :
    {"travail": ["active ne pas déranger", "ouvre Visual Studio Code", "mets le volume à 30"]}
Jarvis confie chaque étape à l'agent compétent, avec les mêmes règles que si on la disait.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from config import ROUTINE_SCHEDULE_FILE, ROUTINES_FILE
from core.agent import Agent, Handler
from persona import Reply, TITLE, fold, plural
from services import events, voice
from services.alarm_store import repeat_days

# Une routine programmée ne part plus si Jarvis était éteint depuis plus longtemps que ça.
SCHEDULE_GRACE = timedelta(minutes=10)
TICK_SECONDS = 30

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

    def __init__(self, context, path: Path = ROUTINES_FILE, schedule_path: Path = ROUTINE_SCHEDULE_FILE) -> None:
        self.path = path
        self.schedule_path = schedule_path
        self._lock = threading.Lock()
        self._started = False
        # Branché par main.py une fois Jarvis créé : exécute une phrase comme si on la disait.
        self.dispatch: Optional[Callable[[str, bool], dict]] = None
        super().__init__(context)

    def handlers(self) -> dict[str, Handler]:
        return {
            "run_routine": self.run_routine,
            "list_routines": self.list_routines,
            "create_routine": self.create_routine,
            "schedule_routine": self.schedule_routine,
            "unschedule_routine": self.unschedule_routine,
        }

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
        planned = [f"- {item['routine']} : {schedule_label(item)}" for item in self.schedules()]
        if planned:
            lines += ["", "À heure fixe :", *planned]
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

    # ── Routines à heure fixe ─────────────────────────────────────────────

    def schedules(self) -> list[dict]:
        try:
            data = json.loads(self.schedule_path.read_text(encoding="utf-8"))
            return [item for item in data if isinstance(item, dict) and item.get("routine") and item.get("time")]
        except (OSError, ValueError, TypeError):
            return []

    def _save_schedules(self, items: list[dict]) -> None:
        self.schedule_path.parent.mkdir(parents=True, exist_ok=True)
        self.schedule_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    def schedule_routine(self, params: dict) -> Reply:
        found = self._find(str(params.get("name") or ""))
        if found is None:
            return Reply(text=f"Je ne connais pas cette routine, {TITLE}. Vos routines : {', '.join(self.routines())}.")
        name = found[0]
        clock, repeat = str(params.get("time") or ""), str(params.get("repeat") or "daily")
        if not re.fullmatch(r"\d{2}:\d{2}", clock) or not repeat_days(repeat):
            return Reply(text=f"À quelle heure, {TITLE} ? Par exemple : lance la routine {name} tous les jours à 22 h.")
        item = {"routine": name, "time": clock, "repeat": repeat, "last_run": ""}
        with self._lock:
            items = [old for old in self.schedules() if fold(old["routine"]) != fold(name)] + [item]
            self._save_schedules(items)
        return Reply(
            text=f"Entendu, {TITLE} : la routine « {name} » se lancera {schedule_label(item)}.",
            speech=f"Entendu, {TITLE}. La routine {name} se lancera {schedule_label(item)}.",
        )

    def unschedule_routine(self, params: dict) -> Reply:
        wanted = fold(str(params.get("name") or "")).strip()
        with self._lock:
            items = self.schedules()
            kept = [item for item in items if wanted and wanted not in fold(item["routine"]) and fold(item["routine"]) not in wanted]
            if len(kept) == len(items):
                return Reply(text=f"Aucune routine programmée de ce nom, {TITLE}.")
            self._save_schedules(kept)
        return Reply(text=f"C'est fait, {TITLE} : cette routine ne se lancera plus d'elle-même.")

    def due(self, now: datetime) -> list[str]:
        """Les routines dont l'heure est venue (une fois par jour au plus), marquées comme lancées."""
        today = now.date().isoformat()
        names = []
        with self._lock:
            items = self.schedules()
            for item in items:
                hour, minute = (int(part) for part in item["time"].split(":"))
                planned = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if item.get("last_run") == today or now.weekday() not in repeat_days(item["repeat"]):
                    continue
                if planned <= now < planned + SCHEDULE_GRACE:
                    item["last_run"] = today
                    names.append(item["routine"])
            if names:
                self._save_schedules(items)
        return names

    def soon(self, now: datetime, within: timedelta = timedelta(hours=1)) -> bool:
        """Une routine programmée part bientôt : Jarvis (lancé à la demande) reste allumé."""
        for item in self.schedules():
            hour, minute = (int(part) for part in item["time"].split(":"))
            planned = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if now.weekday() in repeat_days(item["repeat"]) and now <= planned <= now + within:
                return True
        return False

    def _loop(self) -> None:
        while True:
            try:
                for name in self.due(datetime.now(self.context.timezone).replace(tzinfo=None)):
                    reply = self.run_routine({"name": name})
                    print(f"[ROUTINES] {name} lancée à l'heure prévue", flush=True)
                    events.publish("notice", label=f"Routine {name}", text=reply.text, speech=reply.spoken)
                    if not events.hud_is_listening():
                        voice.speak_local(reply.spoken)
            except Exception as exc:
                print(f"[ROUTINES] Routine programmée en erreur: {exc}", flush=True)
            time.sleep(TICK_SECONDS)

    def start(self) -> None:
        if not self._started:
            self._started = True
            threading.Thread(target=self._loop, daemon=True, name="jarvis-routines").start()


WEEKDAY_NAMES = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def schedule_label(item: dict) -> str:
    """« tous les jours à 22 h 00 », « du lundi au vendredi à 9 h 00 »."""
    repeat = item["repeat"]
    if repeat == "daily":
        rhythm = "tous les jours"
    elif repeat == "weekdays":
        rhythm = "du lundi au vendredi"
    else:
        names = [WEEKDAY_NAMES[day] + "s" for day in sorted(repeat_days(repeat))]
        rhythm = "tous les " + (names[0] if len(names) == 1 else ", ".join(names[:-1]) + " et " + names[-1])
    return f"{rhythm} à {item['time'].replace(':', ' h ')}"
