"""Agent musique : Spotify s'il est installé, sinon l'app Musique (AppleScript)."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from agents.system import SYSTEM, _run, _unsupported
from core.agent import Agent, Handler
from persona import Reply, TITLE, ack

SPOTIFY = "Spotify"
MUSIC = "Music"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def player() -> str:
    """Le lecteur à piloter : Spotify en priorité."""
    installed = any(Path(root, "Spotify.app").exists() for root in ("/Applications", str(Path.home() / "Applications")))
    return SPOTIFY if installed else MUSIC


def _tell(app: str, command: str) -> tuple[bool, str]:
    return _run(["osascript", "-e", f'tell application "{app}" to {command}'], timeout=15)


class MusicAgent(Agent):
    """Lecture, pause, morceau suivant ou précédent, ce qui passe, et lancer un titre ou un artiste."""

    name = "musique"
    local_only = frozenset({"music"})

    def handlers(self) -> dict[str, Handler]:
        return {"music": self.music}

    def music(self, params: dict) -> Reply:
        if SYSTEM != "darwin":
            return _unsupported("le pilotage de la musique")
        app = player()
        command = params.get("command") or "play"
        label = "Spotify" if app == SPOTIFY else "Musique"

        if command == "current":
            ok, playing = _tell(app, 'if player state is playing then return (name of current track) & " — " & (artist of current track)')
            if not ok or not playing.strip():
                return Reply(text=f"Rien ne joue en ce moment, {TITLE}.")
            title, _, artist = playing.partition(" — ")
            return Reply(text=f"En ce moment : {playing}.", speech=f"C'est {title}, de {artist}, {TITLE}.")

        if command == "play_query":
            query = str(params.get("query") or "").strip()
            if not query:
                command = "play"
            elif app == SPOTIFY:
                # Spotify ne lance pas une recherche par AppleScript : on ouvre ses résultats.
                ok, detail = _run(["open", f"spotify:search:{quote(query)}"])
                if not ok:
                    return Reply(text=f"Je ne parviens pas à ouvrir Spotify, {TITLE}.")
                return Reply(text=f"{ack()} Voici « {query} » dans Spotify.", speech=f"{ack()} Je vous ouvre {query} dans Spotify.")
            else:
                script = (
                    f'set found to (search library playlist 1 for "{_escape(query)}")\n'
                    "if found is {} then return \"\"\nplay item 1 of found\n"
                    'return (name of current track) & " — " & (artist of current track)'
                )
                ok, playing = _run(["osascript", "-e", f'tell application "Music"\n{script}\nend tell'], timeout=20)
                if not ok or not playing:
                    return Reply(text=f"Je ne trouve pas « {query} » dans votre bibliothèque, {TITLE}.")
                return Reply(text=f"{ack()} Je lance {playing}.")

        verbs = {
            "play": ("play", "Lecture"),
            "pause": ("pause", "Pause"),
            "toggle": ("playpause", "C'est fait"),
            "next": ("next track", "Morceau suivant"),
            "previous": ("previous track", "Morceau précédent"),
        }
        script, done = verbs.get(command, verbs["play"])
        ok, detail = _tell(app, script)
        if not ok:
            print(f"[MUSIQUE] {label} : {detail}", flush=True)
            return Reply(text=f"Je ne parviens pas à piloter {label}, {TITLE}. Autorisez Jarvis dans Réglages Système › Confidentialité et sécurité › Automatisation.")
        return Reply(text=f"{done}, {TITLE}.")
