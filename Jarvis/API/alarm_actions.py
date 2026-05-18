from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def _env_flag(name: str, default: bool) -> bool:
    """Lit un booléen depuis une variable d'environnement avec valeur par défaut."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, min_value: int, max_value: int) -> int:
    """Lit un entier de configuration et le borne entre min_value et max_value."""
    raw = str(os.getenv(name, str(default))).strip()
    try:
        parsed = int(raw)
    except ValueError:
        parsed = default
    return max(min_value, min(max_value, parsed))


ALARM_NOTIFICATION_ENABLED = _env_flag("ALARM_NOTIFICATION_ENABLED", True)
ALARM_SOUND_ENABLED = _env_flag("ALARM_SOUND_ENABLED", True)
ALARM_SOUND_REPEAT = _env_int("ALARM_SOUND_REPEAT", default=1, min_value=1, max_value=10)
ALARM_SOUND_FILE = os.getenv("ALARM_SOUND_FILE", "").strip()


def format_alarm_datetime(value: datetime, timezone: Any) -> str:
    """Formate une date d'alarme dans le fuseau de l'utilisateur."""
    local = value
    if value.tzinfo is None:
        local = value.replace(tzinfo=timezone)
    local = local.astimezone(timezone)
    return local.strftime("%A %d/%m %H:%M")


def format_alarm_list(items: list[dict], timezone: Any) -> str:
    """Construit l'affichage texte des alarmes actives."""
    if not items:
        return "Aucune alarme active."

    lines = ["Alarmes actives :"]
    for item in items:
        raw = item.get("when", "")
        label = item.get("label", "Alarme Jarvis")
        alarm_id = item.get("id", "?")
        try:
            when = datetime.fromisoformat(raw)
            when_text = format_alarm_datetime(when, timezone)
        except ValueError:
            when_text = raw
        lines.append(f"- {alarm_id} -> {when_text} : {label}")

    lines.append("\nUtilise /deletealarm \"id\" pour supprimer une alarme.")
    return "\n".join(lines)


def _run_command(command: list[str]) -> tuple[bool, str]:
    """Exécute une commande système et renvoie succès + détail d'erreur."""
    try:
        proc = subprocess.run(command, check=False, capture_output=True, text=True)
    except Exception as exc:
        return False, str(exc)

    if proc.returncode == 0:
        return True, ""

    detail = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
    if not detail:
        detail = f"exit {proc.returncode}"
    return False, detail


def _escape_applescript(value: str) -> str:
    """Échappe une chaîne pour une utilisation sûre dans AppleScript."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _notify_alarm_desktop(label: str, when: str) -> bool:
    """Affiche une notification locale adaptée à l'OS disponible."""
    if not ALARM_NOTIFICATION_ENABLED:
        return True

    system = platform.system().lower()
    title = "Jarvis"
    message = f"Alarme: {label} ({when})"

    if system == "darwin":
        osascript = shutil.which("osascript")
        if not osascript:
            print("[ALARM] Notification impossible: osascript introuvable.", flush=True)
            return False

        safe_title = _escape_applescript(title)
        safe_message = _escape_applescript(message)
        script = f'display notification "{safe_message}" with title "{safe_title}"'
        ok, error = _run_command([osascript, "-e", script])
        if not ok:
            print(f"[ALARM] Notification échouée: {error}", flush=True)
        return ok

    if system == "linux":
        notify_send = shutil.which("notify-send")
        if notify_send:
            ok, error = _run_command([notify_send, title, message])
            if not ok:
                print(f"[ALARM] Notification échouée: {error}", flush=True)
            return ok

        print(f"[ALARM] notify-send introuvable, notification texte: {message}", flush=True)
        return False

    if system == "windows":
        try:
            import ctypes

            result = ctypes.windll.user32.MessageBoxW(0, message, title, 0x40)
            return result != 0
        except Exception as exc:
            print(f"[ALARM] Notification Windows échouée: {exc}", flush=True)
            return False

    print(f"[ALARM] Notification texte: {message}", flush=True)
    return False


def _play_alarm_sound() -> bool:
    """Joue un son d'alarme avec plusieurs stratégies de repli."""
    if not ALARM_SOUND_ENABLED:
        return True

    system = platform.system().lower()

    if system == "darwin":
        afplay = shutil.which("afplay")
        if afplay and ALARM_SOUND_FILE and Path(ALARM_SOUND_FILE).exists():
            any_ok = False
            for _ in range(ALARM_SOUND_REPEAT):
                ok, error = _run_command([afplay, ALARM_SOUND_FILE])
                if ok:
                    any_ok = True
                else:
                    print(f"[ALARM] afplay échoué: {error}", flush=True)
            if any_ok:
                return True

        say_cmd = shutil.which("say")
        if say_cmd:
            ok, error = _run_command([say_cmd, "Alarme Jarvis"])
            if ok:
                return True
            print(f"[ALARM] Fallback say échoué: {error}", flush=True)

        osascript = shutil.which("osascript")
        if osascript:
            ok, error = _run_command([osascript, "-e", f"beep {ALARM_SOUND_REPEAT}"])
            if ok:
                return True
            print(f"[ALARM] Fallback beep échoué: {error}", flush=True)

    elif system == "linux":
        for candidate in ["paplay", "aplay", "play"]:
            cmd = shutil.which(candidate)
            if cmd and ALARM_SOUND_FILE and Path(ALARM_SOUND_FILE).exists():
                any_ok = False
                for _ in range(ALARM_SOUND_REPEAT):
                    ok, error = _run_command([cmd, ALARM_SOUND_FILE])
                    if ok:
                        any_ok = True
                    else:
                        print(f"[ALARM] {candidate} échoué: {error}", flush=True)
                if any_ok:
                    return True

        print("\a", end="", flush=True)
        return False

    elif system == "windows":
        try:
            import winsound

            if ALARM_SOUND_FILE and Path(ALARM_SOUND_FILE).exists():
                any_ok = False
                for _ in range(ALARM_SOUND_REPEAT):
                    try:
                        winsound.PlaySound(ALARM_SOUND_FILE, winsound.SND_FILENAME)
                        any_ok = True
                    except Exception as exc:
                        print(f"[ALARM] winsound.PlaySound échoué: {exc}", flush=True)
                if any_ok:
                    return True

            frequency = 880
            duration_ms = 500
            for _ in range(ALARM_SOUND_REPEAT):
                winsound.Beep(frequency, duration_ms)
            return True
        except Exception as exc:
            print(f"[ALARM] Son Windows échoué: {exc}", flush=True)

    print("\a", end="", flush=True)
    return False


def trigger_local_alarm(label: str, when: str) -> tuple[bool, bool]:
    """Déclenche la notification et le son locaux pour une alarme."""
    notification_ok = _notify_alarm_desktop(label, when)
    sound_ok = _play_alarm_sound()
    return notification_ok, sound_ok


def alarm_scheduler_loop(alarms: Any) -> None:
    """Boucle de fond qui détecte les alarmes arrivées à échéance."""
    while True:
        due = alarms.trigger_due_alarms()
        for item in due:
            alarm_id = item.get("id", "?")
            label = item.get("label", "Alarme Jarvis")
            when = item.get("when", "")
            print(f"[ALARM] {alarm_id} {when} -> {label}", flush=True)
            notification_ok, sound_ok = trigger_local_alarm(label, when)
            print(f"[ALARM] local-alert notification={notification_ok} sound={sound_ok}", flush=True)
        time.sleep(5)


def handle_set_alarm(alarms: Any, timezone: Any, params: dict) -> str:
    """Crée une alarme locale."""
    when = datetime.fromisoformat(params["when"])
    title = params["title"]
    created = alarms.create_alarm(when, title)
    when_text = format_alarm_datetime(datetime.fromisoformat(created["when"]), timezone)
    return f"Alarme créée: {created['id']} -> {when_text} ({created['label']})"


def handle_list_alarms(alarms: Any, timezone: Any) -> str:
    """Retourne la liste des alarmes formatée."""
    return format_alarm_list(alarms.list_alarms(), timezone)


def handle_delete_alarm(alarms: Any, params: dict) -> str:
    """Supprime une alarme par identifiant."""
    alarm_id = params["alarm_id"]
    deleted = alarms.delete_alarm(alarm_id)
    if deleted:
        return f"Alarme supprimée: {alarm_id}"
    return f"Aucune alarme trouvée pour: {alarm_id}"


def handle_delete_alarms_range(alarms: Any, params: dict) -> str:
    """Supprime les alarmes sur une plage de dates."""
    start = datetime.fromisoformat(params["start"])
    end = datetime.fromisoformat(params["end"])
    deleted_count = alarms.delete_alarms_in_range(start, end)

    period_start = start.strftime("%d/%m/%Y")
    period_end = (end - timedelta(seconds=1)).strftime("%d/%m/%Y")

    if deleted_count == 0:
        if period_start == period_end:
            return f"Aucune alarme trouvée à supprimer le {period_start}."
        return f"Aucune alarme trouvée à supprimer entre le {period_start} et le {period_end}."

    if period_start == period_end:
        return f"{deleted_count} alarme(s) supprimée(s) le {period_start}."
    return f"{deleted_count} alarme(s) supprimée(s) entre le {period_start} et le {period_end}."


def handle_delete_alarms_all(alarms: Any) -> str:
    """Supprime toutes les alarmes actives et déclenchées."""
    deleted_count = alarms.delete_all_alarms(include_triggered=True)
    if deleted_count == 0:
        return "Aucune alarme à supprimer."
    return f"Toutes les alarmes ont été supprimées ({deleted_count})."
