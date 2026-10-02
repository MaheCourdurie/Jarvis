import system_actions as sa


class FakeRunner:
    """Remplace l'exécution des commandes système : rien n'est réellement lancé."""

    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def __call__(self, command, timeout=10.0):
        self.calls.append(command)
        for prefix, response in self.responses.items():
            if " ".join(command).startswith(prefix):
                return response
        return True, ""


def use_macos(monkeypatch, responses=None):
    runner = FakeRunner(responses)
    monkeypatch.setattr(sa, "SYSTEM", "darwin")
    monkeypatch.setattr(sa, "_run", runner)
    return runner


def test_resolve_app_name():
    assert sa.resolve_app_name("Safari") == "Safari"
    assert sa.resolve_app_name("l'application Calculette s'il te plaît") == "Calculator"
    assert sa.resolve_app_name("mes mails") == "Mail"
    assert sa.resolve_app_name("le navigateur") == "Safari"
    assert sa.resolve_app_name("VS Code") == "Visual Studio Code"
    # Les articles ne sont retirés qu'en tant que mots entiers.
    assert sa.resolve_app_name("Launchpad") == "Launchpad"
    assert sa.resolve_app_name("Messages") == "Messages"
    # Un nom contenant des caractères dangereux est refusé.
    assert sa.resolve_app_name('Safari"; rm -rf /') is None
    assert sa.resolve_app_name("$(reboot)") is None


def test_open_app_never_uses_a_shell(monkeypatch):
    runner = use_macos(monkeypatch)
    reply = sa.handle_open_app({"name": "la calculatrice"})
    assert runner.calls == [["open", "-a", "Calculator"]]
    # Jarvis reprend le mot de l'utilisateur plutôt que le nom technique de l'application.
    assert reply.text.endswith("J'ouvre Calculatrice.")


def test_open_unknown_app(monkeypatch):
    use_macos(monkeypatch, {"open -a": (False, "Unable to find application named 'Zorglub'")})
    assert "aucune application nommée « Zorglub »" in sa.handle_open_app({"name": "Zorglub"}).text


def test_quit_app(monkeypatch):
    runner = use_macos(monkeypatch, {"osascript": (True, "quit")})
    assert "J'ai fermé Safari" in sa.handle_quit_app({"name": "Safari"}).text
    assert runner.calls[0][0] == "osascript"

    use_macos(monkeypatch, {"osascript": (True, "absent")})
    assert "n'est pas en cours d'exécution" in sa.handle_quit_app({"name": "Safari"}).text


def test_volume(monkeypatch):
    settings = (True, "output volume:40, input volume:50, alert volume:100, output muted:false")
    runner = use_macos(monkeypatch, {"osascript -e get volume settings": settings})

    assert "40 %" in sa.handle_volume({"mode": "get"}).text
    sa.handle_volume({"mode": "up"})
    assert runner.calls[-1] == ["osascript", "-e", "set volume output volume 55"]
    sa.handle_volume({"mode": "set", "level": 250})
    assert runner.calls[-1] == ["osascript", "-e", "set volume output volume 100"]
    sa.handle_volume({"mode": "mute"})
    assert runner.calls[-1] == ["osascript", "-e", "set volume with output muted"]


def test_urls_are_validated(monkeypatch):
    opened = []
    monkeypatch.setattr(sa.webbrowser, "open", lambda url: opened.append(url) or True)

    assert sa.normalize_url("github.com") == "https://github.com"
    assert sa.normalize_url("javascript:alert(1)") is None
    assert sa.normalize_url("file:///etc/passwd") is None

    sa.handle_open_url({"url": "github.com/anthropics"})
    sa.handle_web_search({"query": "arc reactor & co", "engine": "youtube"})
    assert opened == [
        "https://github.com/anthropics",
        "https://www.youtube.com/results?search_query=arc+reactor+%26+co",
    ]
    assert "pas valide" in sa.handle_open_url({"url": "pas une adresse"}).text


def test_sleep_display(monkeypatch):
    runner = use_macos(monkeypatch)
    sa.handle_sleep_display()
    assert runner.calls == [["pmset", "displaysleepnow"]]


def test_jarvis_keeps_the_mac_awake_for_the_phone(monkeypatch):
    started = []
    monkeypatch.setattr(sa, "SYSTEM", "darwin")
    monkeypatch.setattr(sa.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(sa.subprocess, "Popen", lambda command, **kwargs: started.append(command) or "caffeinate")

    pid = str(sa.os.getpid())
    assert sa.keep_awake("secteur") == "caffeinate"
    assert sa.keep_awake("toujours") == "caffeinate"
    # Branché seulement (-s) ou sur batterie aussi (-i) ; la consigne tombe quand Jarvis s'arrête (-w).
    assert started == [["caffeinate", "-s", "-w", pid], ["caffeinate", "-i", "-s", "-w", pid]]

    assert sa.keep_awake("0") is None
    monkeypatch.setattr(sa, "SYSTEM", "linux")
    assert sa.keep_awake("secteur") is None and len(started) == 2


def test_system_report_and_alerts(monkeypatch):
    metrics = {
        "hostname": "stark-mac",
        "os": "macOS 27.0",
        "cpu_percent": 12,
        "cpu_count": 10,
        "memory": {"percent": 58, "used_gb": 13.9, "total_gb": 24.0},
        "disk": {"percent": 35, "free_gb": 614, "total_gb": 995},
        "battery": {"percent": 84, "plugged": True, "minutes_left": None},
        "uptime_seconds": 3 * 86400 + 4 * 3600,
    }
    monkeypatch.setattr(sa, "read_system_metrics", lambda: metrics)
    reply = sa.handle_system_status()
    assert reply.text.startswith("Tous les systèmes sont opérationnels, Monsieur.")
    assert "13,9 / 24 Go" in reply.text and "3 j 4 h" in reply.text
    assert "Batterie à 84 pour cent, sur secteur." in reply.spoken

    low = dict(metrics, battery={"percent": 4, "plugged": False, "minutes_left": 39})
    monkeypatch.setattr(sa, "read_system_metrics", lambda: low)
    reply = sa.handle_system_status()
    assert "Un point mérite votre attention" in reply.text
    assert reply.spoken.count("batterie") == 1  # l'alerte ne répète pas le niveau
    assert "0 h 39" in sa.handle_system_status({"focus": "battery"}).text
