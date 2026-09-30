from __future__ import annotations

import platform
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import events
import voice
from config import (
    ALARM_NOTIFICATION_ENABLED,
    ALARM_SOUND_ENABLED,
    ALARM_SOUND_FILE,
    ALARM_SOUND_REPEAT,
)
from persona import Reply, TITLE, format_time, format_when, period_label, plural, spoken_time, spoken_when


MACOS_DEFAULT_CHIME = "/System/Library/Sounds/Glass.aiff"
DELETE_HINT = "\nPour en supprimer une : /deletealarm \"id\""


def _localize(value: datetime, timezone: Any) -> datetime:
    """Place une date sans fuseau dans le fuseau de l'utilisateur."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone)
    return value.astimezone(timezone)


def format_alarm_datetime(value: datetime, timezone: Any) -> str:
    """Formate une date d'alarme dans le fuseau de l'utilisateur."""
    local = _localize(value, timezone)
    return format_when(local, datetime.now(timezone))


def _parse_when(item: dict, timezone: Any) -> datetime | None:
    try:
        return _localize(datetime.fromisoformat(str(item.get("when") or "")), timezone)
    except ValueError:
        return None


def format_alarm_list(items: list[dict], timezone: Any) -> Reply:
    """Construit l'affichage des alarmes actives."""
    if not items:
        return Reply(text=f"Aucune alarme active, {TITLE}.", data={"alarms": 0})

    now = datetime.now(timezone)
    lines = [f"Vos alarmes actives, {TITLE} :"]
    for item in items:
        when = _parse_when(item, timezone)
        when_text = format_when(when, now) if when else str(item.get("when", ""))
        lines.append(f"- {when_text} : {item.get('label', 'Alarme')} [id: {item.get('id', '?')}]")

    speech = f"Vous avez {plural(len(items), 'alarme active', 'alarmes actives')}, {TITLE}."
    first_when = _parse_when(items[0], timezone)
    if first_when:
        speech += f" La prochaine : {items[0].get('label', 'Alarme')}, {spoken_when(first_when, now)}."
    return Reply(text="\n".join(lines) + DELETE_HINT, speech=speech, data={"alarms": len(items)})


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
    title = "J.A.R.V.I.S."
    message = f"{label} ({when})"

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
    custom_sound = ALARM_SOUND_FILE if ALARM_SOUND_FILE and Path(ALARM_SOUND_FILE).exists() else ""

    if system == "darwin":
        afplay = shutil.which("afplay")
        sound = custom_sound or (MACOS_DEFAULT_CHIME if Path(MACOS_DEFAULT_CHIME).exists() else "")
        if afplay and sound:
            any_ok = False
            for _ in range(ALARM_SOUND_REPEAT):
                ok, error = _run_command([afplay, sound])
                if ok:
                    any_ok = True
                else:
                    print(f"[ALARM] afplay échoué: {error}", flush=True)
            if any_ok:
                return True

        osascript = shutil.which("osascript")
        if osascript:
            ok, error = _run_command([osascript, "-e", f"beep {ALARM_SOUND_REPEAT}"])
            if ok:
                return True
            print(f"[ALARM] Fallback beep échoué: {error}", flush=True)

    elif system == "linux":
        for candidate in ["paplay", "aplay", "play"]:
            cmd = shutil.which(candidate)
            if cmd and custom_sound:
                any_ok = False
                for _ in range(ALARM_SOUND_REPEAT):
                    ok, error = _run_command([cmd, custom_sound])
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

            if custom_sound:
                any_ok = False
                for _ in range(ALARM_SOUND_REPEAT):
                    try:
                        winsound.PlaySound(custom_sound, winsound.SND_FILENAME)
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


def alarm_announcement(label: str, now: datetime | None = None) -> str:
    """Phrase prononcée par Jarvis quand une alarme sonne."""
    label = (label or "").strip()
    if label.lower().startswith("minuteur"):
        subject = label.partition(":")[2].strip()
        return f"{TITLE}, votre minuteur est écoulé : {subject}." if subject else f"{TITLE}, votre minuteur est écoulé."
    moment = spoken_time(now or datetime.now())
    if not label or label.lower() in {"alarme", "alarme jarvis", "réveil"}:
        return f"{TITLE}, il est {moment}."
    return f"{TITLE}, il est {moment}. {label}."


def trigger_local_alarm(label: str, when: str, speak: bool = True) -> tuple[bool, bool]:
    """Déclenche la notification, le son puis l'annonce vocale d'une alarme."""
    notification_ok = _notify_alarm_desktop(label, when)
    sound_ok = _play_alarm_sound()
    if speak and ALARM_SOUND_ENABLED:
        voice.speak_local(alarm_announcement(label))
    return notification_ok, sound_ok


def alarm_scheduler_loop(alarms: Any) -> None:
    """Boucle de fond qui détecte les alarmes arrivées à échéance."""
    while True:
        due = alarms.trigger_due_alarms()
        for item in due:
            alarm_id = item.get("id", "?")
            label = item.get("label", "Alarme")
            when = item.get("when", "")
            print(f"[ALARM] {alarm_id} {when} -> {label}", flush=True)

            # Si un HUD est ouvert, c'est lui qui prend la parole (avec l'animation) ;
            # sinon Jarvis parle directement sur les haut-parleurs du poste.
            hud_present = events.hud_is_listening()
            events.publish(
                "alarm",
                alarm_id=alarm_id,
                label=label,
                when=when,
                speech=alarm_announcement(label, datetime.now(alarms.timezone)),
            )
            notification_ok, sound_ok = trigger_local_alarm(label, when, speak=not hud_present)
            print(f"[ALARM] local-alert notification={notification_ok} sound={sound_ok}", flush=True)
        time.sleep(2)


def format_delay(seconds: float) -> str:
    """Formate une durée de minuteur (« 45 secondes », « 10 minutes », « 1 h 30 »)."""
    total = max(1, round(seconds))
    if total < 60:
        return plural(total, "seconde")
    minutes = round(total / 60)
    if minutes < 60:
        return plural(minutes, "minute")
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest:02d}" if rest else plural(hours, "heure")


def handle_set_alarm(alarms: Any, timezone: Any, params: dict) -> Reply:
    """Crée une alarme, un minuteur ou un rappel local."""
    now = datetime.now(timezone)
    when = _localize(datetime.fromisoformat(params["when"]), timezone)
    title = params["title"]
    kind = params.get("kind", "alarm")

    if when < now - timedelta(seconds=30):
        return Reply(text=f"Cette heure est déjà passée, {TITLE}. Quelle échéance souhaitez-vous ?")

    created = alarms.create_alarm(when, title)
    when = _localize(datetime.fromisoformat(created["when"]), timezone)
    suffix = f" [id: {created['id']}]"

    if kind == "timer":
        duration = format_delay((when - now).total_seconds())
        return Reply(
            text=f"Minuteur lancé, {TITLE} : {duration} (fin à {format_time(when)}).{suffix}",
            speech=f"Minuteur lancé, {TITLE} : {duration}.",
            data={"alarm": created},
        )

    if kind == "reminder":
        return Reply(
            text=f"Entendu, {TITLE}. Je vous le rappellerai {format_when(when, now)} : « {created['label']} ».{suffix}",
            speech=f"Entendu, {TITLE}. Je vous le rappellerai {spoken_when(when, now)}.",
            data={"alarm": created},
        )

    label = created["label"]
    if label == "Réveil":
        headline, spoken = "Réveil programmé", "Réveil programmé"
    else:
        headline = spoken = "Alarme programmée"
    # Un titre par défaut n'apporte rien : on ne l'affiche que s'il a été choisi.
    detail = "" if label in {"Alarme", "Réveil"} else f" : « {label} »"
    return Reply(
        text=f"{headline} pour {format_when(when, now)}, {TITLE}{detail}.{suffix}",
        speech=f"{spoken} pour {spoken_when(when, now)}, {TITLE}.",
        data={"alarm": created},
    )


def handle_list_alarms(alarms: Any, timezone: Any) -> Reply:
    """Retourne la liste des alarmes formatée."""
    return format_alarm_list(alarms.list_alarms(), timezone)


def handle_delete_alarm(alarms: Any, params: dict) -> Reply:
    """Supprime une alarme par identifiant."""
    alarm_id = params["alarm_id"]
    if alarms.delete_alarm(alarm_id):
        return Reply(text=f"Alarme supprimée, {TITLE} ({alarm_id}).", speech=f"Alarme supprimée, {TITLE}.")
    return Reply(
        text=f"Je ne trouve aucune alarme portant l'identifiant {alarm_id}, {TITLE}.",
        speech=f"Je ne trouve aucune alarme portant cet identifiant, {TITLE}.",
    )


def handle_delete_alarms_range(alarms: Any, params: dict) -> Reply:
    """Supprime les alarmes sur une plage de dates."""
    timezone = alarms.timezone
    start = _localize(datetime.fromisoformat(params["start"]), timezone)
    end = _localize(datetime.fromisoformat(params["end"]), timezone)
    deleted_count = alarms.delete_alarms_in_range(start, end)

    period = period_label(start, end, datetime.now(timezone))

    if deleted_count == 0:
        return Reply(text=f"Aucune alarme à supprimer {period}, {TITLE}.")
    return Reply(
        text=f"C'est fait, {TITLE} : {plural(deleted_count, 'alarme supprimée', 'alarmes supprimées')} {period}."
    )


def handle_delete_timers(alarms: Any) -> Reply:
    """Arrête les minuteurs en cours."""
    deleted_count = alarms.delete_alarms_with_label_prefix("Minuteur")
    if deleted_count == 0:
        return Reply(text=f"Aucun minuteur en cours, {TITLE}.")
    if deleted_count == 1:
        return Reply(text=f"Minuteur arrêté, {TITLE}.")
    return Reply(text=f"C'est fait, {TITLE} : {deleted_count} minuteurs arrêtés.")


def handle_delete_alarms_all(alarms: Any, params: dict | None = None) -> Reply:
    """Supprime toutes les alarmes (après confirmation si params["confirm"] est vrai)."""
    if (params or {}).get("confirm"):
        active = alarms.list_alarms()
        if not active:
            return Reply(text=f"Aucune alarme à supprimer, {TITLE}.")
        count = plural(len(active), "alarme active", "alarmes actives")
        return Reply(
            text=f"Vous avez {count}, {TITLE}. Dois-je tout supprimer ?",
            pending={"action": "delete_alarms_all", "params": {}},
        )

    deleted_count = alarms.delete_all_alarms(include_triggered=True)
    if deleted_count == 0:
        return Reply(text=f"Aucune alarme à supprimer, {TITLE}.")
    return Reply(text=f"C'est fait, {TITLE} : toutes les alarmes sont supprimées.")
