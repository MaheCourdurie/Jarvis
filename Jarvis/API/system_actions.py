"""Capteurs système et pilotage du poste de travail (applications, volume, veille).

Toutes les commandes système passent par _run() avec une liste d'arguments :
aucune chaîne utilisateur n'est jamais interprétée par un shell.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import threading
import time
import webbrowser
from datetime import datetime
from typing import Any
from urllib.parse import quote_plus

from persona import Reply, TITLE, ack, format_date, format_time, spoken_time, strip_accents

try:
    import psutil
except ImportError:  # psutil est optionnel : sans lui, le diagnostic est simplement réduit.
    psutil = None


SYSTEM = platform.system().lower()

# Actions qui agissent physiquement sur le poste : réservées aux clients locaux.
SYSTEM_CONTROL_ACTIONS = {"open_app", "quit_app", "open_url", "web_search", "volume", "sleep_display"}

# Noms français (ou familiers) → nom réel de l'application macOS.
APP_ALIASES = {
    "navigateur": "Safari",
    "safari": "Safari",
    "mail": "Mail",
    "mails": "Mail",
    "messagerie": "Mail",
    "boite mail": "Mail",
    "calendrier": "Calendar",
    "agenda": "Calendar",
    "musique": "Music",
    "notes": "Notes",
    "rappels": "Reminders",
    "terminal": "Terminal",
    "reglages": "System Settings",
    "preferences": "System Settings",
    "preferences systeme": "System Settings",
    "parametres": "System Settings",
    "finder": "Finder",
    "calculatrice": "Calculator",
    "calculette": "Calculator",
    "photos": "Photos",
    "messages": "Messages",
    "plans": "Maps",
    "cartes": "Maps",
    "facetime": "FaceTime",
    "contacts": "Contacts",
    "horloge": "Clock",
    "meteo": "Weather",
    "apercu": "Preview",
    "livres": "Books",
    "dictaphone": "Voice Memos",
    "raccourcis": "Shortcuts",
    "moniteur d'activite": "Activity Monitor",
    "app store": "App Store",
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "vs code": "Visual Studio Code",
    "vscode": "Visual Studio Code",
    "code": "Visual Studio Code",
    "visual studio code": "Visual Studio Code",
    "word": "Microsoft Word",
    "excel": "Microsoft Excel",
    "powerpoint": "Microsoft PowerPoint",
    "teams": "Microsoft Teams",
    "zoom": "zoom.us",
}

SEARCH_ENGINES = {
    "web": ("le web", "https://duckduckgo.com/?q={q}"),
    "google": ("Google", "https://www.google.com/search?q={q}"),
    "youtube": ("YouTube", "https://www.youtube.com/results?search_query={q}"),
    "wikipedia": ("Wikipédia", "https://fr.wikipedia.org/w/index.php?search={q}"),
}

_SAFE_APP_NAME = re.compile(r"^[\w .+\-']{1,60}$", flags=re.UNICODE)
_SAFE_URL = re.compile(r"^https?://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?::\d{1,5})?(?:/[^\s\"'<>]*)?$")
_LEADING_WORDS = re.compile(
    r"^(?:l'application|l'appli|l'app|le logiciel|le programme|application|appli)\s+"
    r"|^(?:le|la|les|mon|ma|mes|un|une|du|de la|des)\s+"
    r"|^l'",
    flags=re.IGNORECASE,
)
_TRAILING_WORDS = re.compile(
    r"[\s,]*(?:s'il te pla[iî]t|s'il vous pla[iî]t|stp|svp|pour moi|maintenant|merci)[\s.!?]*$",
    flags=re.IGNORECASE,
)


def _run(command: list[str], timeout: float = 10.0) -> tuple[bool, str]:
    """Exécute une commande système sans shell et renvoie (succès, sortie)."""
    try:
        proc = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        return False, str(exc)

    output = (proc.stdout or "").strip()
    if proc.returncode == 0:
        return True, output
    return False, (proc.stderr or output or f"exit {proc.returncode}").strip()


def _unsupported(what: str) -> Reply:
    return Reply(text=f"Je crains que {what} ne soit pas pris en charge sur ce système, {TITLE}.")


def _decimal(value: float, digits: int = 1) -> str:
    """Formate un nombre à la française (virgule décimale)."""
    return f"{value:.{digits}f}".replace(".", ",")


# ── Heure et date ──────────────────────────────────────────────────────────

def handle_time(timezone: Any) -> Reply:
    """Donne l'heure locale."""
    now = datetime.now(timezone)
    return Reply(
        text=f"Il est {format_time(now)}, {TITLE}.",
        speech=f"Il est {spoken_time(now)}, {TITLE}.",
    )


def handle_date(timezone: Any) -> Reply:
    """Donne la date du jour."""
    now = datetime.now(timezone)
    return Reply(text=f"Nous sommes le {format_date(now)} {now.year}, {TITLE}.")


# ── Diagnostic système ─────────────────────────────────────────────────────

_cpu_lock = threading.Lock()
_cpu_sample = (0.0, 0)

if psutil is not None:
    # Premier appel de référence : psutil mesure l'usage CPU entre deux appels.
    psutil.cpu_percent(interval=None)
    _cpu_sample = (time.time(), 0)


def _cpu_percent() -> int:
    """Usage CPU lissé : deux relevés trop rapprochés donneraient une valeur aberrante."""
    global _cpu_sample
    with _cpu_lock:
        measured_at, value = _cpu_sample
        if time.time() - measured_at >= 1.0:
            value = round(psutil.cpu_percent(interval=None))
            _cpu_sample = (time.time(), value)
        return value


def _os_label() -> str:
    if SYSTEM == "darwin":
        return f"macOS {platform.mac_ver()[0]}".strip()
    return f"{platform.system()} {platform.release()}".strip()


def read_system_metrics() -> dict:
    """Relève l'état du poste : processeur, mémoire, disque, batterie, durée de service."""
    metrics: dict = {
        "hostname": platform.node().split(".")[0],
        "os": _os_label(),
        "cpu_percent": None,
        "cpu_count": os.cpu_count(),
        "memory": None,
        "disk": None,
        "battery": None,
        "uptime_seconds": None,
    }
    if psutil is None:
        return metrics

    metrics["cpu_percent"] = _cpu_percent()

    memory = psutil.virtual_memory()
    metrics["memory"] = {
        "percent": round(memory.percent),
        # La mémoire se compte en puissances de deux (un Mac « 24 Go » affiche bien 24).
        "used_gb": round((memory.total - memory.available) / 2**30, 1),
        "total_gb": round(memory.total / 2**30, 1),
    }

    try:
        disk = psutil.disk_usage(os.path.expanduser("~"))
        metrics["disk"] = {
            "percent": round(100 * (1 - disk.free / disk.total)) if disk.total else 0,
            "free_gb": round(disk.free / 1e9),
            "total_gb": round(disk.total / 1e9),
        }
    except OSError:
        pass

    try:
        battery = psutil.sensors_battery()
    except Exception:
        battery = None
    if battery is not None:
        seconds_left = battery.secsleft if isinstance(battery.secsleft, (int, float)) else -1
        metrics["battery"] = {
            "percent": round(battery.percent),
            "plugged": bool(battery.power_plugged),
            "minutes_left": int(seconds_left // 60) if seconds_left and seconds_left > 0 else None,
        }

    metrics["uptime_seconds"] = int(time.time() - psutil.boot_time())
    return metrics


def format_uptime(seconds: int | None) -> str:
    """Formate une durée de service (« 3 j 4 h », « 12 min »)."""
    if not seconds or seconds < 0:
        return "inconnue"
    days, remainder = divmod(int(seconds), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return f"{days} j {hours} h"
    if hours:
        return f"{hours} h {minutes:02d} min"
    return f"{max(minutes, 1)} min"


def _battery_phrase(battery: dict) -> str:
    source = "sur secteur" if battery["plugged"] else "sur batterie"
    return f"{battery['percent']} %, {source}"


def system_alerts(metrics: dict) -> list[str]:
    """Liste les points d'attention que Jarvis signale de lui-même."""
    alerts = []
    battery = metrics.get("battery")
    if battery and not battery["plugged"] and battery["percent"] <= 20:
        alerts.append(f"La batterie est à {battery['percent']} % : je recommande de brancher le chargeur.")
    memory = metrics.get("memory")
    if memory and memory["percent"] >= 90:
        alerts.append(f"La mémoire est occupée à {memory['percent']} %.")
    disk = metrics.get("disk")
    if disk and disk["percent"] >= 90:
        alerts.append(f"Il ne reste que {disk['free_gb']} Go d'espace disque.")
    cpu = metrics.get("cpu_percent")
    if cpu is not None and cpu >= 90:
        alerts.append(f"Le processeur est sollicité à {cpu} %.")
    return alerts


def handle_system_status(params: dict | None = None) -> Reply:
    """Rapport de diagnostic : « Tous les systèmes sont opérationnels, Monsieur. »"""
    focus = (params or {}).get("focus")
    metrics = read_system_metrics()
    battery = metrics.get("battery")

    if focus == "battery":
        if not battery:
            return Reply(text=f"Ce poste n'a pas de batterie, {TITLE} : il est alimenté sur secteur.", data=metrics)
        text = f"La batterie est à {_battery_phrase(battery)}, {TITLE}."
        if battery.get("minutes_left"):
            hours, minutes = divmod(battery["minutes_left"], 60)
            text += f" Autonomie estimée : {hours} h {minutes:02d}."
        return Reply(text=text, data=metrics)

    if metrics["cpu_percent"] is None:
        return Reply(
            text=(
                f"Mes capteurs système sont hors ligne, {TITLE} : le module psutil n'est pas installé. "
                "Lancez ./run_jarvis.sh setup pour les activer."
            ),
            data=metrics,
        )

    memory = metrics["memory"]
    disk = metrics.get("disk")
    lines = [
        f"Diagnostic de {metrics['hostname']} ({metrics['os']}) :",
        f"- Processeur : {metrics['cpu_percent']} % ({metrics['cpu_count']} cœurs)",
        f"- Mémoire : {memory['percent']} % ({_decimal(memory['used_gb'])} / {memory['total_gb']:g} Go)",
    ]
    if disk:
        lines.append(f"- Disque : {disk['free_gb']} Go libres sur {disk['total_gb']} Go")
    if battery:
        lines.append(f"- Batterie : {_battery_phrase(battery)}")
    lines.append(f"- En service depuis {format_uptime(metrics['uptime_seconds'])}")

    alerts = system_alerts(metrics)
    if alerts:
        headline = f"Un point mérite votre attention, {TITLE}."
        lines.extend(f"⚠ {alert}" for alert in alerts)
    else:
        headline = f"Tous les systèmes sont opérationnels, {TITLE}."

    speech_parts = [
        headline,
        f"Processeur à {metrics['cpu_percent']} pour cent, mémoire à {memory['percent']} pour cent.",
    ]
    # Si une alerte parle déjà de la batterie, inutile de l'annoncer deux fois.
    if battery and not any("batterie" in alert for alert in alerts):
        source = "sur secteur" if battery["plugged"] else "sur batterie"
        speech_parts.append(f"Batterie à {battery['percent']} pour cent, {source}.")
    speech_parts.extend(alerts)

    return Reply(text="\n".join([headline] + lines), speech=" ".join(speech_parts), data=metrics)


# ── Applications ───────────────────────────────────────────────────────────

def resolve_app(raw: str) -> tuple[str, str] | None:
    """Transforme « l'application Calculette, s'il te plaît » en (application à lancer, nom à prononcer)."""
    name = (raw or "").replace("’", "'").strip().strip("\"'«» ")
    name = _TRAILING_WORDS.sub("", name).strip(" .!?,;:")
    previous = None
    while previous != name:
        previous = name
        name = _LEADING_WORDS.sub("", name, count=1).strip()
    if not name:
        return None

    key = strip_accents(name.lower())
    if key in APP_ALIASES:
        # Jarvis reprend le mot de l'utilisateur (« Calculette »), pas le nom technique (« Calculator »).
        return APP_ALIASES[key], name[:1].upper() + name[1:]
    if not _SAFE_APP_NAME.match(name):
        return None
    return name, name


def resolve_app_name(raw: str) -> str | None:
    """Retourne seulement le nom de l'application à lancer."""
    resolved = resolve_app(raw)
    return resolved[0] if resolved else None


def handle_open_app(params: dict) -> Reply:
    """Ouvre une application du poste."""
    resolved = resolve_app(str(params.get("name") or ""))
    if not resolved:
        return Reply(text=f"Quelle application dois-je ouvrir, {TITLE} ?")
    name, label = resolved

    if SYSTEM == "darwin":
        ok, detail = _run(["open", "-a", name])
    elif SYSTEM == "windows":
        ok, detail = _run(["cmd", "/c", "start", "", name])
    else:
        binary = shutil.which(name) or shutil.which(name.lower().replace(" ", "-"))
        if binary:
            try:
                subprocess.Popen([binary], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                ok, detail = True, ""
            except OSError as exc:
                ok, detail = False, str(exc)
        else:
            ok, detail = False, "introuvable"

    if ok:
        return Reply(text=f"{ack()} J'ouvre {label}.", data={"app": name})
    print(f"[SYSTEM] Ouverture impossible ({name}): {detail}", flush=True)
    return Reply(text=f"Je ne trouve aucune application nommée « {label} » sur ce poste, {TITLE}.")


def handle_quit_app(params: dict) -> Reply:
    """Ferme proprement une application (elle propose d'enregistrer si besoin)."""
    resolved = resolve_app(str(params.get("name") or ""))
    if not resolved:
        return Reply(text=f"Quelle application dois-je fermer, {TITLE} ?")
    name, label = resolved
    if SYSTEM != "darwin":
        return _unsupported("la fermeture d'applications")

    # _SAFE_APP_NAME interdit les guillemets et antislashs : le nom peut être inséré tel quel.
    ok, detail = _run(
        [
            "osascript",
            "-e", f'if application "{name}" is running then',
            "-e", f'tell application "{name}" to quit',
            "-e", 'return "quit"',
            "-e", "else",
            "-e", 'return "absent"',
            "-e", "end if",
        ]
    )
    if ok and detail == "quit":
        return Reply(text=f"{ack()} J'ai fermé {label}.", data={"app": name})
    if ok:
        return Reply(text=f"{label} n'est pas en cours d'exécution, {TITLE}.")
    print(f"[SYSTEM] Fermeture impossible ({name}): {detail}", flush=True)
    return Reply(text=f"Je ne parviens pas à fermer « {label} », {TITLE}.")


# ── Web ────────────────────────────────────────────────────────────────────

def normalize_url(raw: str) -> str | None:
    """Valide une adresse web et lui ajoute https:// si besoin."""
    url = (raw or "").strip().strip("\"'«» .,;!?")
    if not url:
        return None
    if not re.match(r"^https?://", url, flags=re.IGNORECASE):
        url = "https://" + url
    return url if _SAFE_URL.match(url) else None


def handle_open_url(params: dict) -> Reply:
    """Ouvre un site dans le navigateur par défaut."""
    url = normalize_url(str(params.get("url") or ""))
    if not url:
        return Reply(text=f"Cette adresse ne me paraît pas valide, {TITLE}.")
    if not webbrowser.open(url):
        return Reply(text=f"Je ne parviens pas à ouvrir le navigateur, {TITLE}.")
    host = re.sub(r"^https?://(?:www\.)?", "", url).split("/")[0]
    return Reply(text=f"{ack()} J'ouvre {host}.", data={"url": url})


def handle_web_search(params: dict) -> Reply:
    """Lance une recherche dans le navigateur par défaut."""
    query = str(params.get("query") or "").strip().strip("\"'«» .,;!?")
    if not query:
        return Reply(text=f"Que dois-je rechercher, {TITLE} ?")
    label, template = SEARCH_ENGINES.get(str(params.get("engine") or "web"), SEARCH_ENGINES["web"])
    url = template.format(q=quote_plus(query))
    if not webbrowser.open(url):
        return Reply(text=f"Je ne parviens pas à ouvrir le navigateur, {TITLE}.")
    return Reply(
        text=f"{ack()} Je lance la recherche « {query} » sur {label}.",
        speech=f"{ack()} Les résultats pour {query} sont à l'écran.",
        data={"url": url},
    )


# ── Volume ─────────────────────────────────────────────────────────────────

def _get_volume() -> tuple[int | None, bool | None]:
    """Retourne (volume 0-100, muet) ou (None, None) si indisponible."""
    if SYSTEM == "darwin":
        ok, out = _run(["osascript", "-e", "get volume settings"])
        if not ok:
            return None, None
        level = re.search(r"output volume:(\d+)", out)
        muted = re.search(r"output muted:(true|false)", out)
        return (int(level.group(1)) if level else None, muted.group(1) == "true" if muted else None)

    if SYSTEM == "linux" and shutil.which("pactl"):
        ok, out = _run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
        level = re.search(r"(\d+)%", out) if ok else None
        ok_mute, out_mute = _run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"])
        muted = ("yes" in out_mute or "oui" in out_mute) if ok_mute else None
        return (int(level.group(1)) if level else None, muted)

    return None, None


def _set_volume(level: int) -> bool:
    level = max(0, min(100, int(level)))
    if SYSTEM == "darwin":
        return _run(["osascript", "-e", f"set volume output volume {level}"])[0]
    if SYSTEM == "linux" and shutil.which("pactl"):
        return _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"])[0]
    return False


def _set_muted(muted: bool) -> bool:
    if SYSTEM == "darwin":
        clause = "with" if muted else "without"
        return _run(["osascript", "-e", f"set volume {clause} output muted"])[0]
    if SYSTEM == "linux" and shutil.which("pactl"):
        return _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if muted else "0"])[0]
    return False


def handle_volume(params: dict) -> Reply:
    """Règle le volume de sortie : niveau absolu, variation, coupure ou rétablissement."""
    mode = params.get("mode")
    current, muted = _get_volume()
    if current is None:
        return _unsupported("le réglage du volume")

    if mode == "get":
        state = " (son coupé)" if muted else ""
        return Reply(text=f"Le volume est à {current} %{state}, {TITLE}.", data={"volume": current, "muted": muted})

    if mode == "mute":
        if not _set_muted(True):
            return Reply(text=f"Je ne parviens pas à couper le son, {TITLE}.")
        return Reply(text=f"{ack()} Le son est coupé.", data={"volume": current, "muted": True})

    if mode == "unmute":
        if not _set_muted(False):
            return Reply(text=f"Je ne parviens pas à rétablir le son, {TITLE}.")
        return Reply(text=f"{ack()} Le son est rétabli à {current} %.", data={"volume": current, "muted": False})

    if mode == "set":
        target = int(params.get("level", current))
    else:
        step = int(params.get("step", 15))
        target = current + step if mode == "up" else current - step
    target = max(0, min(100, target))

    if not _set_volume(target):
        return Reply(text=f"Je ne parviens pas à régler le volume, {TITLE}.")
    if muted and target > 0:
        _set_muted(False)
    return Reply(
        text=f"{ack()} Volume à {target} %.",
        speech=f"{ack()} Volume à {target} pour cent.",
        data={"volume": target, "muted": False},
    )


# ── Veille ─────────────────────────────────────────────────────────────────

def keep_awake(mode: str) -> subprocess.Popen | None:
    """Empêche le Mac de s'endormir tant que Jarvis tourne, pour qu'il réponde au téléphone.

    « secteur » : seulement quand le Mac est branché ; « toujours » : sur batterie aussi.
    caffeinate relâche la consigne de lui-même quand Jarvis s'arrête (-w).
    """
    flags = {"secteur": ["-s"], "toujours": ["-i", "-s"]}.get(mode)
    if SYSTEM != "darwin" or not flags or not shutil.which("caffeinate"):
        return None
    command = ["caffeinate", *flags, "-w", str(os.getpid())]
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def handle_sleep_display(params: dict | None = None) -> Reply:
    """Met l'écran en veille (verrouille la session si un mot de passe est exigé)."""
    if SYSTEM == "darwin":
        ok, detail = _run(["pmset", "displaysleepnow"])
    elif SYSTEM == "windows":
        ok, detail = _run(["rundll32.exe", "user32.dll,LockWorkStation"])
    elif shutil.which("loginctl"):
        ok, detail = _run(["loginctl", "lock-session"])
    elif shutil.which("xdg-screensaver"):
        ok, detail = _run(["xdg-screensaver", "lock"])
    else:
        return _unsupported("la mise en veille de l'écran")

    if ok:
        return Reply(text=f"{ack()} Je mets l'écran en veille.")
    print(f"[SYSTEM] Mise en veille impossible: {detail}", flush=True)
    return Reply(text=f"Je ne parviens pas à mettre l'écran en veille, {TITLE}.")
