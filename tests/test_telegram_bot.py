"""Bot Telegram : il n'obéit qu'au compte appairé, lance et arrête Jarvis, et ne divulgue jamais son token."""

import sys
import time
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Telegram"))

import phone_setup  # noqa: E402
import telegram_bot as tg  # noqa: E402


OWNER = 42


class FakeApi:
    """Telegram simulé : garde la trace des appels."""

    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail or {}
        self.next_id = 100

    def call(self, method, http_timeout=15, **params):
        self.calls.append((method, params))
        if method in self.fail:
            raise self.fail[method]
        if method in {"sendMessage", "editMessageText"}:
            self.next_id += 1
            return {"message_id": self.next_id}
        return True

    def texts(self):
        return [params["text"] for method, params in self.calls if method in {"sendMessage", "editMessageText"}]

    def buttons(self):
        last = [params for method, params in self.calls if method in {"sendMessage", "editMessageText"}][-1]
        return [button["text"] for row in last["reply_markup"]["inline_keyboard"] for button in row]


class FakeService:
    """Service Jarvis simulé : après un redémarrage, il ne répond pas pendant un instant."""

    def __init__(self, running=True):
        self.running = running
        self.is_disabled = False
        self.commands = []
        self.silent_checks = 0

    def command(self, action):
        self.commands.append(action)
        self.running = action in {"start", "restart"}
        self.is_disabled = action == "stop"
        if action == "restart":
            self.silent_checks = 1
        return True, ""

    def disabled(self):
        return self.is_disabled

    def online(self):
        self.pings = getattr(self, "pings", 0) + 1
        if self.silent_checks:
            self.silent_checks -= 1
            return None
        if not self.running:
            return None
        return {"model_online": True, "voice": {"tts": {"available": True}, "stt": {"available": True}}}

    def installed(self):
        return True

    def pid(self):
        return 4242 if self.running else None

    def uptime(self):
        return "2 h 03" if self.running else ""


def message(text, user_id=OWNER, chat_type="private", age=0):
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": int(time.time()) - age,
            "text": text,
            "chat": {"id": user_id, "type": chat_type},
            "from": {"id": user_id, "username": "moi"},
        },
    }


def button(action, user_id=OWNER):
    return {
        "update_id": 2,
        "callback_query": {
            "id": "q1",
            "data": action,
            "from": {"id": user_id},
            "message": {"message_id": 7, "chat": {"id": user_id, "type": "private"}},
        },
    }


@pytest.fixture()
def parts(monkeypatch):
    monkeypatch.setattr(tg, "power_line", lambda: "🔌 Mac branché (90 %).")
    api, service = FakeApi(), FakeService()
    return api, service, tg.Bot(api, service, {OWNER}, sleep=lambda seconds: None)


def test_strangers_are_ignored(parts):
    api, service, bot = parts
    bot.handle(message("/arreter", user_id=666))
    bot.handle(button("arreter", user_id=666))
    # Même le propriétaire n'est pas obéi depuis un groupe.
    bot.handle(message("/arreter", chat_type="group"))
    assert service.commands == [] and api.texts() == []


def test_owner_stops_then_starts_jarvis(parts):
    api, service, bot = parts
    bot.handle(message("/arreter"))
    assert service.commands == ["stop"]
    assert api.texts()[0] == "⏳ J'arrête Jarvis…"
    assert "Jarvis est arrêté. Il ne démarrera plus tout seul" in api.texts()[-1] and "Mac branché" in api.texts()[-1]
    assert api.buttons() == ["🟢 Lancer", "📊 Statut"]

    bot.handle(button("lancer"))
    assert ("answerCallbackQuery", {"callback_query_id": "q1"}) in api.calls
    assert service.commands == ["stop", "start"]
    assert "Jarvis est prêt" in api.texts()[-1] and "en ligne depuis 2 h 03" in api.texts()[-1]
    assert api.buttons() == ["🔴 Arrêter", "🔄 Redémarrer", "📊 Statut"]


def test_jarvis_asleep_waits_for_a_request(parts):
    # En veille : il n'est pas arrêté, il redémarrera tout seul à la prochaine demande.
    api, service, bot = parts
    service.running = False
    bot.handle(message("/statut"))
    assert api.texts()[-1].startswith("💤 Jarvis est en veille : il démarre tout seul dès que vous ouvrez l'app.")
    assert api.buttons() == ["🟢 Lancer", "🔴 Arrêter", "📊 Statut"]
    # Le bot ne l'a pas interrogé : toute connexion le réveillerait.
    assert getattr(service, "pings", 0) == 0


def test_restart_waits_for_jarvis_to_come_back(parts):
    api, service, bot = parts
    bot.handle(message("redémarre"))
    assert service.commands == ["restart"] and "Jarvis est prêt" in api.texts()[-1]


def test_status_and_help(parts):
    api, service, bot = parts
    bot.handle(message("/statut"))
    assert api.texts()[-1].startswith("🟢 Jarvis est en ligne depuis 2 h 03.")
    bot.handle(message("/start"))  # premier message envoyé par Telegram : l'état, avec les boutons
    assert api.texts()[-1].startswith("🟢 Jarvis est en ligne")
    bot.handle(message("bonjour"))
    assert api.texts()[-1].startswith("Je lance et j'arrête Jarvis")
    assert service.commands == []


def test_late_commands_are_not_run(parts):
    # Envoyée pendant que le Mac dormait, une commande ne doit pas s'exécuter des heures plus tard.
    api, service, bot = parts
    bot.handle(message("/arreter", age=3600))
    assert service.commands == [] and "en retard" in api.texts()[-1]


def test_old_button_is_not_run(monkeypatch):
    monkeypatch.setattr(tg, "power_line", lambda: "")
    too_old = tg.TelegramError("answerCallbackQuery : Bad Request: query is too old and response timeout expired", 400)
    api, service = FakeApi(fail={"answerCallbackQuery": too_old}), FakeService()
    tg.Bot(api, service, {OWNER}, sleep=lambda seconds: None).handle(button("arreter"))
    assert service.commands == [] and "Bouton touché pendant que le Mac était injoignable" in api.texts()[-1]


def test_commands_are_understood():
    assert tg.parse_command("/arreter@JarvisMaheBot") == "arreter"
    assert tg.parse_command("Arrête Jarvis") == "arreter"
    assert tg.parse_command("stop") == "arreter"
    assert tg.parse_command("/lancer") == "lancer"
    assert tg.parse_command("Démarre") == "lancer"
    assert tg.parse_command("/start Xy-9") == "accueil"
    assert tg.parse_command("bonjour") is None and tg.parse_command("") is None


class PairingApi:
    """Telegram simulé pour l'appairage : des messages arrivent par paquets."""

    def __init__(self, batches):
        self.batches = list(batches)
        self.calls = []

    def call(self, method, http_timeout=15, **params):
        self.calls.append((method, params))
        if method == "sendMessage":
            return {"message_id": 1}
        if params.get("offset") == -1:  # dernier message déjà reçu avant l'appairage
            return [{"update_id": 10, "message": {"text": "123456", "chat": {"type": "private", "id": 9}, "from": {"id": 9}}}]
        return self.batches.pop(0) if self.batches else []


def pairing_update(update_id, text, user_id, chat_type="private"):
    return {"update_id": update_id, "message": {"text": text, "chat": {"type": chat_type, "id": user_id}, "from": {"id": user_id, "username": f"u{user_id}"}}}


def test_pairing_needs_the_one_time_code():
    api = PairingApi([
        [pairing_update(11, "/aide", 5), pairing_update(12, "654321", 5)],
        [pairing_update(13, "123456", 6, chat_type="group"), pairing_update(14, "123456", OWNER)],
    ])
    ticks = iter(range(100))
    user, chat_id = tg.wait_for_pairing(api, "123456", seconds=50, clock=lambda: next(ticks))

    # L'ancien message (update 10) est ignoré, comme le mauvais code et le groupe.
    assert user["id"] == OWNER and chat_id == OWNER
    assert api.calls[1][1]["offset"] == 11
    assert api.calls[-1] == ("getUpdates", {"timeout": 0, "offset": 15})  # le service ne le reverra pas
    # Celui qui écrit sans le bon code apprend quoi faire ; le groupe, lui, n'a pas de réponse.
    hints = [params["chat_id"] for method, params in api.calls if method == "sendMessage"]
    assert hints == [5, 5]


def test_pairing_through_the_qr_code_link():
    api = PairingApi([[pairing_update(11, "/start 123456", OWNER)]])
    ticks = iter(range(100))
    assert tg.wait_for_pairing(api, "123456", seconds=50, clock=lambda: next(ticks))[0]["id"] == OWNER


def test_pairing_gives_up_after_the_delay():
    ticks = iter(range(100))
    assert tg.wait_for_pairing(PairingApi([]), "CODE", seconds=3, clock=lambda: next(ticks)) is None


def test_the_token_never_appears_in_errors():
    token = "123456789:" + "A" * 35

    class Unreachable:
        def post(self, url, json, timeout):
            raise requests.ConnectionError(f"Max retries exceeded with url: {url}")

    with pytest.raises(tg.TelegramError) as error:
        tg.TelegramApi(token, session=Unreachable()).call("getMe")
    assert token not in str(error.value) and "<token>" in str(error.value)


def test_a_freshly_copied_token_wins_and_a_revoked_one_is_skipped(monkeypatch):
    revoked, fresh = "111111:" + "R" * 35, "222222:" + "F" * 35

    class Api:
        def __init__(self, token):
            self.token = token

        def call(self, method, **params):
            if self.token == revoked:
                raise tg.TelegramError("getMe : Unauthorized", 401)
            return {"username": "Jarvis_Bot"}

    monkeypatch.setattr(tg, "TelegramApi", Api)
    monkeypatch.setattr(tg.config, "TELEGRAM_BOT_TOKEN", revoked)
    monkeypatch.setattr(tg, "token_from_clipboard", lambda: fresh)
    assert tg.find_bot()[0] == fresh  # le token régénéré, copié, remplace celui de .env

    monkeypatch.setattr(tg, "token_from_clipboard", lambda: revoked)
    monkeypatch.setattr(tg.config, "TELEGRAM_BOT_TOKEN", fresh)
    assert tg.find_bot()[0] == fresh  # un token refusé est ignoré au profit du suivant


def test_token_format():
    assert tg.TOKEN_PATTERN.match("123456789:AAEhBP0av28aUgQvdg9TJ8yPgKXyzXyzXyz")
    assert not tg.TOKEN_PATTERN.match("Bonjour, voici mon texte")


def test_settings_are_written_to_env(tmp_path):
    env = tmp_path / ".env"
    env.write_text("JARVIS_CITY=Colomiers\nTELEGRAM_ALLOWED_USERS=1\n", encoding="utf-8")
    phone_setup.set_env_values({"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_ALLOWED_USERS": "42"}, env)
    assert env.read_text(encoding="utf-8") == "JARVIS_CITY=Colomiers\nTELEGRAM_ALLOWED_USERS=42\nTELEGRAM_BOT_TOKEN=123:abc\n"
