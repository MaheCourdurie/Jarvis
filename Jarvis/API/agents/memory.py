"""Agent mémoire : ce que Jarvis doit retenir de vous (« souviens-toi que je prends mon café sans sucre »)."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path

from config import MEMORY_FILE
from core.agent import Agent, Handler
from persona import Reply, TITLE, fold, plural

MAX_FACTS = 200


class MemoryAgent(Agent):
    """Retient, rappelle et oublie des faits ; l'agent de conversation s'en sert pour répondre."""

    name = "mémoire"

    def __init__(self, context, path: Path = MEMORY_FILE) -> None:
        self.path = path
        self._lock = threading.Lock()
        super().__init__(context)

    def handlers(self) -> dict[str, Handler]:
        return {"remember": self.remember, "recall": self.recall, "forget": self.forget}

    def facts(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _save(self, facts: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(facts[-MAX_FACTS:], ensure_ascii=False, indent=2), encoding="utf-8")

    def remember(self, params: dict) -> Reply:
        fact = str(params.get("fact") or "").strip(" .")
        if len(fact) < 3:
            return Reply(text=f"Que dois-je retenir, {TITLE} ?")
        with self._lock:
            facts = [item for item in self.facts() if fold(item["fact"]) != fold(fact)]
            facts.append({"fact": fact, "since": datetime.now().isoformat(timespec="minutes")})
            self._save(facts)
        return Reply(text=f"C'est noté, {TITLE} : « {fact} ».", speech=f"C'est noté, {TITLE}. Je m'en souviendrai.")

    def recall(self, params: dict) -> Reply:
        facts = self.facts()
        if not facts:
            return Reply(text=f"Vous ne m'avez encore rien confié, {TITLE}. Dites « souviens-toi que… ».")
        lines = [f"- « {item['fact']} »" for item in facts]
        return Reply(
            text=f"Ce que je sais de vous, {TITLE} :\n" + "\n".join(lines),
            speech=f"Je retiens {plural(len(facts), 'chose')} à votre sujet, {TITLE}. La liste est à l'écran.",
        )

    def forget(self, params: dict) -> Reply:
        topic = fold(str(params.get("fact") or ""))
        words = [word for word in re.findall(r"\w+", topic) if len(word) > 2]
        with self._lock:
            facts = self.facts()
            if params.get("all"):
                kept = []
            else:
                kept = [item for item in facts if not words or not all(word in fold(item["fact"]) for word in words)]
            if len(kept) == len(facts):
                return Reply(text=f"Je ne retenais rien à ce sujet, {TITLE}.")
            self._save(kept)
        return Reply(text=f"C'est oublié, {TITLE}.")

    def as_context(self) -> str:
        """Ce que le modèle doit savoir de l'utilisateur pendant la conversation."""
        facts = self.facts()[-40:]
        if not facts:
            return ""
        return "Ce que l'utilisateur vous a demandé de retenir : " + " ; ".join(item["fact"] for item in facts) + "."
