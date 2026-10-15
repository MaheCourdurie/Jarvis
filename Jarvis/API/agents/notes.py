"""Agent notes : l'app Notes (« prends une note ») et l'app Rappels (« ajoute du lait à ma liste de courses »)."""

from __future__ import annotations

from agents.system import SYSTEM, _run, _unsupported
from core.agent import Agent, Handler
from persona import Reply, TITLE, plural

DEFAULT_LIST = "Courses"


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _osascript(script: str) -> tuple[bool, str]:
    return _run(["osascript", "-e", script], timeout=20)


PERMISSION = "Autorisez Jarvis dans Réglages Système › Confidentialité et sécurité › Automatisation (et Rappels)."


class NotesAgent(Agent):
    """Prend des notes et tient des listes (courses, tâches…), synchronisées sur l'iPhone par iCloud."""

    name = "notes"

    def handlers(self) -> dict[str, Handler]:
        return {"add_note": self.add_note, "add_to_list": self.add_to_list, "read_list": self.read_list}

    def add_note(self, params: dict) -> Reply:
        if SYSTEM != "darwin":
            return _unsupported("les notes")
        text = str(params.get("text") or "").strip()
        if not text:
            return Reply(text=f"Que dois-je noter, {TITLE} ?")
        title = text.split(".")[0][:60]
        body = f"<h1>{title}</h1><p>{text}</p>" if title != text else f"<p>{text}</p>"
        ok, detail = _osascript(f'tell application "Notes" to make new note with properties {{name:{_quote(title)}, body:{_quote(body)}}}')
        if not ok:
            print(f"[NOTES] {detail}", flush=True)
            return Reply(text=f"Je ne parviens pas à écrire dans Notes, {TITLE}. {PERMISSION}")
        return Reply(text=f"C'est noté dans Notes, {TITLE} : « {text} ».", speech=f"C'est noté, {TITLE}.")

    def add_to_list(self, params: dict) -> Reply:
        if SYSTEM != "darwin":
            return _unsupported("les listes")
        items = [item.strip() for item in params.get("items") or [] if item.strip()]
        name = str(params.get("list") or DEFAULT_LIST).strip().capitalize()
        if not items:
            return Reply(text=f"Qu'est-ce que j'ajoute à la liste {name}, {TITLE} ?")
        adds = "\n".join(f"make new reminder at end of list {_quote(name)} with properties {{name:{_quote(item)}}}" for item in items)
        script = (
            'tell application "Reminders"\n'
            f"if not (exists list {_quote(name)}) then make new list with properties {{name:{_quote(name)}}}\n"
            f"{adds}\nend tell"
        )
        ok, detail = _osascript(script)
        if not ok:
            print(f"[RAPPELS] {detail}", flush=True)
            return Reply(text=f"Je ne parviens pas à écrire dans Rappels, {TITLE}. {PERMISSION}")
        listed = ", ".join(items)
        return Reply(text=f"Ajouté à la liste {name}, {TITLE} : {listed}.", speech=f"C'est ajouté à la liste {name}, {TITLE}.")

    def read_list(self, params: dict) -> Reply:
        if SYSTEM != "darwin":
            return _unsupported("les listes")
        name = str(params.get("list") or DEFAULT_LIST).strip().capitalize()
        script = (
            'tell application "Reminders"\n'
            f"if not (exists list {_quote(name)}) then return \"\"\n"
            f"set AppleScript's text item delimiters to linefeed\n"
            f"return (name of reminders of list {_quote(name)} whose completed is false) as text\nend tell"
        )
        ok, output = _osascript(script)
        if not ok:
            return Reply(text=f"Je ne parviens pas à lire Rappels, {TITLE}. {PERMISSION}")
        items = [line.strip() for line in output.splitlines() if line.strip()]
        if not items:
            return Reply(text=f"Votre liste {name} est vide, {TITLE}.")
        return Reply(
            text=f"Liste {name}, {TITLE} :\n" + "\n".join(f"- {item}" for item in items),
            speech=f"Sur votre liste {name}, {plural(len(items), 'élément')} : {', '.join(items[:8])}.",
        )
