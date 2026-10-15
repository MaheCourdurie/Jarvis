"""Bot Telegram de Jarvis : lancer, arrêter, redémarrer et surveiller Jarvis depuis le téléphone.

Il tourne à part de Jarvis (service macOS « fr.jarvis.telegram ») pour rester joignable quand
Jarvis est arrêté. Il interroge Telegram lui-même (aucun port n'est ouvert sur le Mac) et n'obéit
qu'aux comptes appairés (TELEGRAM_ALLOWED_USERS) : les messages des autres sont ignorés.

Usage (via ./run_jarvis.sh telegram) :
    python Telegram/telegram_bot.py setup   → token du bot et appairage de ton compte
    python Telegram/telegram_bot.py run     → le bot lui-même (lancé par le service)
"""

from __future__ import annotations

import getpass
import os
import re
import secrets
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from typing import Callable, Optional

import requests

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "Jarvis" / "API"))

import config  # noqa: E402  (premier import local : charge le .env)
from phone_setup import set_env_values, show_qr  # noqa: E402
from agents.system import keep_awake  # noqa: E402


LAUNCHER = ROOT_DIR / "run_jarvis.sh"
SERVICE_LABEL = "fr.jarvis.assistant"
SERVICE_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
STATUS_URL = f"http://127.0.0.1:{config.PORT}/api/status"
TOKEN_PATTERN = re.compile(r"^\d{5,12}:[A-Za-z0-9_-]{30,}$")
POLL_SECONDS = 50          # attente côté Telegram à chaque interrogation (long polling)
STALE_SECONDS = 300        # une commande plus ancienne n'est pas exécutée (le Mac dormait sans doute)
START_TIMEOUT = 120        # Jarvis met quelques secondes à charger la voix et la reconnaissance
STOP_TIMEOUT = 20
PAIRING_SECONDS = 300

COMMANDS = [
    ("statut", "Jarvis est-il en ligne ?"),
    ("lancer", "Lancer Jarvis"),
    ("arreter", "Arrêter Jarvis"),
    ("redemarrer", "Redémarrer Jarvis"),
    ("aide", "Ce que fait ce bot"),
]
# Ce que l'on peut écrire au bot, avec ou sans « / » et sans se soucier des accents.
ALIASES = {
    "start": "accueil",
    "statut": "statut", "status": "statut", "etat": "statut",
    "lancer": "lancer", "lance": "lancer", "demarrer": "lancer", "demarre": "lancer", "allume": "lancer",
    "arreter": "arreter", "arrete": "arreter", "stop": "arreter", "eteins": "arreter", "coupe": "arreter",
    "redemarrer": "redemarrer", "redemarre": "redemarrer", "relancer": "redemarrer", "relance": "redemarrer",
    "aide": "aide", "help": "aide",
}
CONTROL = {"lancer": "start", "arreter": "stop", "redemarrer": "restart"}
PROGRESS = {"lancer": "⏳ Je lance Jarvis…", "arreter": "⏳ J'arrête Jarvis…", "redemarrer": "⏳ Je redémarre Jarvis…"}
HELP = (
    "Je lance et j'arrête Jarvis sur votre Mac. Je reste joignable quand Jarvis est arrêté, "
    "tant que le Mac est allumé et éveillé.\n\n"
    "Jarvis démarre tout seul quand vous ouvrez l'app, et se met en veille après "
    f"{config.IDLE_MINUTES or '—'} min sans demande.\n\n"
    "/statut — Jarvis est-il en ligne ?\n"
    "/lancer — le démarrer tout de suite\n"
    "/arreter — le couper complètement : plus de démarrage automatique, même après un redémarrage "
    "du Mac, jusqu'au prochain /lancer\n"
    "/redemarrer — le relancer\n\n"
    "Les boutons sous mes messages font la même chose."
)
PAIRING_HINT = (
    "🔒 Je ne vous connais pas encore. Envoyez-moi le code à 6 chiffres affiché sur le Mac par "
    "./run_jarvis.sh telegram, et je vous obéirai."
)
BOTFATHER_STEPS = """Il faut d'abord créer le bot dans Telegram (une seule fois) :
  1. Ouvre la conversation avec @BotFather et envoie /newbot.
  2. Donne-lui un nom (« Jarvis »), puis un identifiant qui finit par « bot » (ex. jarvis_mahe_bot).
  3. Copie le token qu'il te renvoie (123456789:AAE…). Copié sur l'iPhone, il arrive aussi dans
     le presse-papiers du Mac.
  4. Relance ./run_jarvis.sh telegram : le token est lu dans le presse-papiers."""


# ── Telegram ───────────────────────────────────────────────────────────────

class TelegramError(Exception):
    """Échec d'un appel à Telegram. Le message ne contient jamais le token."""

    def __init__(self, message: str, code: int = 0):
        super().__init__(message)
        self.code = code


class TelegramApi:
    def __init__(self, token: str, session: Optional[requests.Session] = None):
        self.token = token
        self.base = f"https://api.telegram.org/bot{token}/"
        self.session = session or requests.Session()

    def call(self, method: str, http_timeout: float = 15, **params):
        try:
            response = self.session.post(self.base + method, json=params, timeout=http_timeout)
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            # L'adresse appelée contient le token : il ne doit apparaître dans aucun journal.
            detail = str(exc).replace(self.token, "<token>")
            raise TelegramError(f"{method} : Telegram injoignable ({detail})") from None
        if not data.get("ok"):
            raise TelegramError(f"{method} : {data.get('description', 'refusé')}", int(data.get("error_code") or 0))
        return data.get("result")


# ── Le service Jarvis ──────────────────────────────────────────────────────

def format_elapsed(etime: str) -> str:
    """Durée donnée par ps (« 1-02:03:04 », « 02:03:04 », « 03:04 ») → « 1 j 2 h », « 2 h 03 »…"""
    match = re.fullmatch(r"(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+)", etime.strip())
    if not match:
        return ""
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    if days:
        return f"{days} j {hours} h"
    if hours:
        return f"{hours} h {minutes:02d}"
    return f"{minutes} min" if minutes else f"{seconds} s"


class JarvisService:
    """Le service macOS de Jarvis, piloté avec les commandes de ./run_jarvis.sh service …"""

    def command(self, action: str) -> tuple[bool, str]:
        try:
            done = subprocess.run(
                ["/bin/bash", str(LAUNCHER), "service", action], capture_output=True, text=True, timeout=60
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, str(exc)
        return done.returncode == 0, (done.stdout + done.stderr).strip()

    def online(self) -> Optional[dict]:
        """État renvoyé par Jarvis, ou None s'il ne répond pas."""
        try:
            return requests.get(STATUS_URL, timeout=3).json()
        except (requests.RequestException, ValueError):
            return None

    def installed(self) -> bool:
        return SERVICE_PLIST.exists()

    def _launchctl(self, *args: str) -> Optional[str]:
        try:
            done = subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout if done.returncode == 0 else None

    def disabled(self) -> bool:
        """Arrêté par « Arrêter » : macOS ne le relancera pas, même à la demande."""
        listing = self._launchctl("print-disabled", f"gui/{os.getuid()}") or ""
        return f'"{SERVICE_LABEL}" => disabled' in listing

    def pid(self) -> Optional[int]:
        info = self._launchctl("print", f"gui/{os.getuid()}/{SERVICE_LABEL}") or ""
        match = re.search(r"^\s*pid = (\d+)", info, flags=re.MULTILINE)
        return int(match.group(1)) if match else None

    def uptime(self) -> str:
        pid = self.pid()
        if pid is None:
            return ""
        try:
            etime = subprocess.run(["ps", "-o", "etime=", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return ""
        return format_elapsed(etime)


def power_line() -> str:
    """Le Mac est-il branché ? Sur batterie, il peut s'endormir : Jarvis et le bot ne répondent plus."""
    try:
        report = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    percent = re.search(r"(\d+)%", report)
    level = f" ({percent.group(1)} %)" if percent else ""
    if "AC Power" in report:
        return f"🔌 Mac branché{level}."
    if config.KEEP_AWAKE == "toujours":
        return f"🔋 Mac sur batterie{level}."
    return f"🔋 Mac sur batterie{level} : s'il s'endort, Jarvis et moi ne répondrons plus jusqu'à son réveil."


def status_text(service: JarvisService) -> tuple[str, str]:
    """Texte d'état, et l'état lui-même (pour choisir les boutons) :
    running (en ligne), sleeping (en veille, démarre à la demande), stopped (arrêté), starting, missing.

    Interroger Jarvis le réveillerait (toute connexion est une demande) : on demande d'abord à
    macOS s'il tourne, et on ne l'interroge que dans ce cas.
    """
    status = None
    if not service.installed():
        status = service.online()  # lancé à la main, sans le service ?
        state = "running" if status is not None else "missing"
    elif service.disabled():
        state = "stopped"
    elif service.pid() is None:
        state = "sleeping"
    else:
        status = service.online()
        state = "running" if status is not None else "starting"

    if state == "running":
        since = service.uptime()
        voice = status.get("voice") or {}
        model = "prêt" if status.get("model_online") else "hors ligne"
        speech = "prête" if (voice.get("tts") or {}).get("available") else "indisponible"
        ears = "prête" if (voice.get("stt") or {}).get("available") else "indisponible"
        lines = [f"🟢 Jarvis est en ligne{f' depuis {since}' if since else ''}.", f"Modèle {model} · voix {speech} · écoute {ears}."]
    else:
        lines = [{
            "missing": "⚪️ Le service Jarvis n'est pas installé sur le Mac : ./run_jarvis.sh service install",
            "stopped": "🔴 Jarvis est arrêté : il ne démarrera pas tant que vous ne le relancez pas.",
            "starting": "🟡 Jarvis démarre…",
            "sleeping": "💤 Jarvis est en veille : il démarre tout seul dès que vous ouvrez l'app.",
        }[state]]
    power = power_line()
    if power:
        lines.append(power)
    return "\n".join(lines), state


def keyboard(state: str) -> dict:
    def button(label: str, action: str) -> dict:
        return {"text": label, "callback_data": action}

    if state == "running":
        rows = [[button("🔴 Arrêter", "arreter"), button("🔄 Redémarrer", "redemarrer")], [button("📊 Statut", "statut")]]
    elif state == "sleeping":
        rows = [[button("🟢 Lancer", "lancer"), button("🔴 Arrêter", "arreter")], [button("📊 Statut", "statut")]]
    else:
        rows = [[button("🟢 Lancer", "lancer"), button("📊 Statut", "statut")]]
    return {"inline_keyboard": rows}


def parse_command(text: str) -> Optional[str]:
    """« /arreter@JarvisBot », « Arrête » ou « stop » → « arreter » ; rien de connu → None."""
    words = (text or "").strip().split(maxsplit=1)
    if not words:
        return None
    word = words[0].lstrip("/").split("@", 1)[0].strip(".!?,;:")
    folded = unicodedata.normalize("NFKD", word).encode("ascii", "ignore").decode().lower()
    return ALIASES.get(folded)


# ── Le bot ─────────────────────────────────────────────────────────────────

class Bot:
    def __init__(
        self,
        api: TelegramApi,
        service: JarvisService,
        allowed: set[int],
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ):
        self.api = api
        self.service = service
        self.allowed = allowed
        self.sleep = sleep
        self.clock = clock

    def handle(self, update: dict) -> None:
        if "callback_query" in update:
            self._button(update["callback_query"])
            return
        message = update.get("message") or {}
        if not self._authorized(message.get("from"), message.get("chat")):
            return
        chat_id = message["chat"]["id"]
        if self.clock() - message.get("date", 0) > STALE_SECONDS:
            self.send(chat_id, "⏱ Message reçu en retard (le Mac était sans doute en veille) : je ne l'exécute pas. Renvoyez-le si besoin.")
            return
        self.run(parse_command(message.get("text", "")) or "aide", chat_id)

    def _button(self, query: dict) -> None:
        chat = (query.get("message") or {}).get("chat") or {}
        if not self._authorized(query.get("from"), chat):
            self._safe("answerCallbackQuery", callback_query_id=query.get("id"))
            return
        try:
            self.api.call("answerCallbackQuery", callback_query_id=query.get("id"))
        except TelegramError as exc:
            # Telegram refuse de répondre à un bouton touché il y a longtemps : le Mac dormait.
            if "too old" in str(exc).lower():
                self.send(chat["id"], "⏱ Bouton touché pendant que le Mac était injoignable : je ne l'exécute pas. Touchez-le de nouveau.")
                return
            print(f"[TELEGRAM] {exc}", flush=True)
        self.run(query.get("data"), chat["id"])

    def _authorized(self, user: Optional[dict], chat: Optional[dict]) -> bool:
        user = user or {}
        if (chat or {}).get("type") == "private" and user.get("id") in self.allowed:
            return True
        print(f"[TELEGRAM] Message ignoré : compte non autorisé {user.get('id')} (@{user.get('username', '?')})", flush=True)
        return False

    def run(self, action: Optional[str], chat_id: int) -> None:
        print(f"[TELEGRAM] Commande : {action}", flush=True)
        if action in CONTROL:
            self.control(action, chat_id)
            return
        text, state = status_text(self.service)
        intro = HELP if action == "aide" else ""
        self.send(chat_id, f"{intro}\n\n{text}" if intro else text, keyboard(state))

    def control(self, action: str, chat_id: int) -> None:
        sent = self.send(chat_id, PROGRESS[action])
        started = time.monotonic()
        ok, detail = self.service.command(CONTROL[action])
        if not ok:
            outcome = f"⚠️ Échec : {detail[-300:] or 'erreur inconnue'}"
        elif action == "arreter":
            stopped = self._wait(lambda: self.service.online() is None, STOP_TIMEOUT)
            outcome = (
                "🔴 Jarvis est arrêté. Il ne démarrera plus tout seul, même si vous ouvrez l'app ou si le Mac "
                "redémarre, jusqu'à ce que vous le relanciez."
                if stopped else "⚠️ Jarvis répond encore."
            )
        else:
            if action == "redemarrer":
                self._wait(lambda: self.service.online() is None, 10)
            ready = self._wait(lambda: self.service.online() is not None, START_TIMEOUT)
            outcome = (
                f"🟢 Jarvis est prêt ({time.monotonic() - started:.0f} s)."
                if ready else "⚠️ Jarvis ne répond pas : voir ~/Library/Logs/Jarvis.log sur le Mac."
            )
        text, state = status_text(self.service)
        self.edit(chat_id, sent, f"{outcome}\n\n{text}", keyboard(state))

    def _wait(self, condition: Callable[[], bool], seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while not condition():
            if time.monotonic() >= deadline:
                return False
            self.sleep(1)
        return True

    def send(self, chat_id: int, text: str, markup: Optional[dict] = None) -> Optional[int]:
        params = {"chat_id": chat_id, "text": text}
        if markup:
            params["reply_markup"] = markup
        return (self._safe("sendMessage", **params) or {}).get("message_id")

    def edit(self, chat_id: int, message_id: Optional[int], text: str, markup: Optional[dict] = None) -> None:
        params = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if markup:
            params["reply_markup"] = markup
        if message_id is None or self._safe("editMessageText", **params) is None:
            self.send(chat_id, text, markup)

    def _safe(self, method: str, **params):
        try:
            return self.api.call(method, **params)
        except TelegramError as exc:
            print(f"[TELEGRAM] {exc}", flush=True)
            return None


def allowed_users() -> set[int]:
    return {int(item) for item in config.TELEGRAM_ALLOWED_USERS if item.lstrip("-").isdigit()}


def run_bot() -> int:
    token, allowed = config.TELEGRAM_BOT_TOKEN, allowed_users()
    if not token or not allowed:
        print("[TELEGRAM] Bot non configuré : lance ./run_jarvis.sh telegram sur le Mac.", flush=True)
        time.sleep(600)  # le service relancerait le bot aussitôt : inutile de remplir le journal
        return 1

    api = TelegramApi(token)
    bot = Bot(api, JarvisService(), allowed)
    # Le bot doit rester joignable pour relancer Jarvis : il empêche lui aussi la veille du Mac.
    _awake = keep_awake(config.KEEP_AWAKE)
    try:
        me = api.call("getMe")
        api.call("setMyCommands", commands=[{"command": name, "description": text} for name, text in COMMANDS])
        print(f"[TELEGRAM] Bot @{me.get('username')} en ligne, {len(allowed)} compte(s) autorisé(s)", flush=True)
    except TelegramError as exc:
        print(f"[TELEGRAM] {exc}", flush=True)

    offset, delay = None, 1
    while True:
        params = {"timeout": POLL_SECONDS, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            params["offset"] = offset
        try:
            updates = api.call("getUpdates", http_timeout=POLL_SECONDS + 15, **params)
            delay = 1
        except TelegramError as exc:
            print(f"[TELEGRAM] {exc}", flush=True)
            # 401 : token révoqué ; 409 : un autre programme lit déjà les messages du bot.
            time.sleep(300 if exc.code == 401 else 30 if exc.code == 409 else delay)
            delay = min(60, delay * 2)
            continue
        for update in updates or []:
            offset = update["update_id"] + 1
            try:
                bot.handle(update)
            except Exception as exc:  # une commande qui échoue ne doit pas arrêter le bot
                print(f"[TELEGRAM] Erreur sur une commande : {exc}", flush=True)


# ── Installation : token et appairage ──────────────────────────────────────

def token_from_clipboard() -> str:
    try:
        text = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    return text if TOKEN_PATTERN.match(text) else ""


def find_bot() -> Optional[tuple[str, TelegramApi, dict]]:
    """Premier token accepté par Telegram : presse-papiers (un token tout juste copié, par exemple
    après l'avoir régénéré), puis .env, sinon saisie masquée. Renvoie (token, api, bot)."""
    candidates = []
    copied = token_from_clipboard()
    if copied:
        candidates.append(("le presse-papiers", copied))
    if TOKEN_PATTERN.match(config.TELEGRAM_BOT_TOKEN) and config.TELEGRAM_BOT_TOKEN != copied:
        candidates.append((".env", config.TELEGRAM_BOT_TOKEN))
    if not candidates and sys.stdin.isatty():
        typed = getpass.getpass("Token du bot donné par BotFather (la saisie est masquée) : ").strip()
        if TOKEN_PATTERN.match(typed):
            candidates.append(("la saisie", typed))
        else:
            print("[telegram] Ce n'est pas un token de bot (forme attendue : 123456789:AAE…).")

    for source, token in candidates:
        api = TelegramApi(token)
        try:
            me = api.call("getMe")
        except TelegramError as exc:
            print(f"[telegram] Token de {source} refusé par Telegram ({exc}).")
            continue
        print(f"[telegram] Token lu dans {source}.")
        return token, api, me
    return None


def wait_for_pairing(api: TelegramApi, code: str, seconds: float = PAIRING_SECONDS, clock: Callable[[], float] = time.monotonic):
    """Attend le code d'appairage : tapé tel quel, ou envoyé par le lien du QR code (« /start <code> »).

    Renvoie (compte, conversation). Les autres messages reçoivent une explication.
    """
    deadline = clock() + seconds
    offset = None
    # Seuls les messages à venir comptent : un ancien message ne peut pas appairer un compte.
    previous = api.call("getUpdates", timeout=0, offset=-1)
    if previous:
        offset = previous[-1]["update_id"] + 1
    while clock() < deadline:
        params = {"timeout": int(max(1, min(25, deadline - clock())))}
        if offset is not None:
            params["offset"] = offset
        for update in api.call("getUpdates", http_timeout=40, **params) or []:
            offset = update["update_id"] + 1
            message = update.get("message") or {}
            chat = message.get("chat") or {}
            if chat.get("type") != "private":
                continue
            text = (message.get("text") or "").strip()
            if text in {code, f"/start {code}"}:
                api.call("getUpdates", timeout=0, offset=offset)  # traité : le service ne le reverra pas
                return message.get("from") or {}, chat["id"]
            api.call("sendMessage", chat_id=chat["id"], text=PAIRING_HINT)
    return None


def setup() -> int:
    found = find_bot()
    if found is None:
        print(BOTFATHER_STEPS)
        print("  (Bot déjà créé ? Dans @BotFather, /token redonne son token.)")
        return 1
    token, api, me = found
    set_env_values({"TELEGRAM_BOT_TOKEN": token})
    print(f"[telegram] Bot @{me['username']} reconnu.")

    if allowed_users():
        print("[telegram] Ton compte est déjà appairé. Pour en appairer un autre : retire TELEGRAM_ALLOWED_USERS de .env, puis relance.")
        return 0

    code = f"{secrets.randbelow(10**6):06d}"
    link = f"https://t.me/{me['username']}?start={code}"
    print(f"\nDans Telegram, envoie ce code à @{me['username']} : {code}", flush=True)
    print("(ou scanne le QR code affiché à l'écran, puis touche « Démarrer »)", flush=True)
    show_qr(link)
    print("\n[telegram] En attente (5 min)…", flush=True)
    try:
        paired = wait_for_pairing(api, code)
    except TelegramError as exc:
        print(f"[telegram] {exc}")
        return 1
    if not paired:
        print("[telegram] Aucun appairage reçu à temps : relance ./run_jarvis.sh telegram.")
        return 1

    user, chat_id = paired
    set_env_values({"TELEGRAM_ALLOWED_USERS": str(user["id"])})
    try:
        # Le menu « / » de Telegram propose les commandes dès maintenant.
        api.call("setMyCommands", commands=[{"command": name, "description": text} for name, text in COMMANDS])
        api.call("sendMessage", chat_id=chat_id, text=f"✅ Appairé : je n'obéis qu'à vous.\n\n{HELP}")
    except TelegramError as exc:
        print(f"[telegram] {exc}")
    name = f"@{user['username']}" if user.get("username") else user.get("first_name", "ton compte")
    print(f"[telegram] Compte appairé : {name} (id {user['id']}).")
    return 0


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "setup":
        raise SystemExit(setup())
    if action == "run":
        raise SystemExit(run_bot())
    print(__doc__)
    raise SystemExit(2)
