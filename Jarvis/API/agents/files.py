"""Agent fichiers : retrouver un fichier (Spotlight), l'ouvrir, résumer un document."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agents.system import SYSTEM, _run, _unsupported
from core.agent import Agent, Handler
from persona import Reply, TITLE, ack, plural
from services import llm

TEXT_SUFFIXES = {".txt", ".md", ".py", ".js", ".html", ".css", ".csv", ".json", ".log", ".sh", ".yaml", ".yml", ".xml"}
TEXTUTIL_SUFFIXES = {".docx", ".doc", ".rtf", ".odt", ".rtfd", ".webarchive"}
# Dossiers qu'on n'affiche pas : bibliothèques, caches, environnements.
NOISE = ("/Library/", "/.", "/node_modules/", "/.venv/", "/site-packages/", "/__pycache__/")
SUMMARY_PROMPT = (
    "Tu résumes un document en français pour J.A.R.V.I.S. : de quoi il s'agit, puis les points essentiels, "
    "en 3 à 6 phrases simples. N'invente rien."
)
# Lit le texte d'un PDF avec PDFKit, sans aucune dépendance.
PDF_SCRIPT = (
    "ObjC.import('PDFKit');"
    "var doc = $.PDFDocument.alloc.initWithURL($.NSURL.fileURLWithPath('{path}'));"
    "doc ? ObjC.unwrap(doc.string) : ''"
)


def find(query: str, limit: int = 8) -> list[Path]:
    """Cherche par nom avec Spotlight, dans le dossier personnel, les plus récents d'abord."""
    if SYSTEM != "darwin":
        return []
    ok, output = _run(["mdfind", "-onlyin", str(Path.home()), "-name", query], timeout=15)
    if not ok:
        return []
    paths = [Path(line) for line in output.splitlines() if line and not any(part in line for part in NOISE)]
    files = [path for path in paths if path.is_file()]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return files[:limit]


def read_text(path: Path, budget: int = 7000) -> str:
    suffix = path.suffix.lower()
    try:
        if suffix in TEXT_SUFFIXES:
            return path.read_text(encoding="utf-8", errors="replace")[:budget]
        if suffix in TEXTUTIL_SUFFIXES:
            proc = subprocess.run(["textutil", "-convert", "txt", "-stdout", str(path)], capture_output=True, text=True, timeout=30)
            return proc.stdout[:budget]
        if suffix == ".pdf":
            script = PDF_SCRIPT.replace("{path}", str(path).replace("'", "\\'"))
            proc = subprocess.run(["osascript", "-l", "JavaScript", "-e", script], capture_output=True, text=True, timeout=60)
            return proc.stdout[:budget]
    except Exception as exc:
        print(f"[FICHIERS] Lecture impossible ({path}): {exc}", flush=True)
    return ""


def _home(path: Path) -> str:
    return str(path).replace(str(Path.home()), "~", 1)


class FilesAgent(Agent):
    """Retrouve, ouvre et résume les fichiers du Mac."""

    name = "fichiers"
    local_only = frozenset({"open_file"})

    def handlers(self) -> dict[str, Handler]:
        return {"find_file": self.find_file, "open_file": self.open_file, "summarize_file": self.summarize_file}

    def _query(self, params: dict) -> str:
        return str(params.get("query") or "").strip(" «»\"'.?!")

    def find_file(self, params: dict) -> Reply:
        query = self._query(params)
        if SYSTEM != "darwin":
            return _unsupported("la recherche de fichiers")
        files = find(query)
        if not files:
            return Reply(text=f"Je ne trouve aucun fichier nommé « {query} », {TITLE}.")
        return Reply(
            text=f"{plural(len(files), 'fichier trouvé', 'fichiers trouvés')}, {TITLE} :\n" + "\n".join(f"- {_home(path)}" for path in files),
            speech=f"J'ai trouvé {plural(len(files), 'fichier')}, {TITLE}. Le plus récent : {files[0].name}.",
            data={"files": [str(path) for path in files]},
        )

    def open_file(self, params: dict) -> Reply:
        query = self._query(params)
        files = find(query, limit=1)
        if not files:
            return Reply(text=f"Je ne trouve aucun fichier nommé « {query} », {TITLE}.")
        ok, _ = _run(["open", str(files[0])])
        if not ok:
            return Reply(text=f"Je ne parviens pas à ouvrir {files[0].name}, {TITLE}.")
        return Reply(text=f"{ack()} J'ouvre {_home(files[0])}.", speech=f"{ack()} J'ouvre {files[0].stem}.")

    def summarize_file(self, params: dict) -> Reply:
        query = self._query(params)
        files = find(query, limit=3)
        readable = next(((path, text) for path in files if (text := read_text(path)).strip()), None)
        if readable is None:
            return Reply(text=f"Je ne trouve pas de document lisible nommé « {query} », {TITLE}.")
        path, text = readable
        try:
            summary = llm.clean_reply(llm.complete(SUMMARY_PROMPT, f"Document {path.name} :\n{text}", 0.2, 450, timeout=120))
        except Exception as exc:
            print(f"[FICHIERS] Résumé impossible: {exc}", flush=True)
            return Reply(text=f"Je n'ai pas réussi à résumer {path.name}, {TITLE}.")
        return Reply(text=f"{path.name} ({_home(path)}) :\n\n{summary}", speech=summary)
