"""Les agents renforcés : tri des mails, météo heure par heure, rappel des rendez-vous avec le
trajet, tests et corrections de code, état d'Ollama en cache, heures dans le bon fuseau.

Tout ce qui sortirait du poste (Gmail, cartes, météo, modèle) est simulé.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import main
from agents import atelier, code, files, heads_up
from core.intents import detect_action
from services import llm, weather
from test_api import FakeGoogle
from test_creation import SCRIPT_OK, studio  # noqa: F401  (fixture partagée)

PARIS = ZoneInfo("Europe/Paris")


def ask(message, client="hud"):
    with TestClient(main.app, base_url="http://localhost") as http:
        response = http.post("/api/chat", json={"message": message, "client": client})
    assert response.status_code == 200, response.text
    return response.json()


# ── Messagerie : le modèle trie la boîte ───────────────────────────────────

class BusyInbox(FakeGoogle):
    def get_unread_emails(self, limit=5):
        return [
            {"from": {"emailAddress": {"name": "EDF"}}, "subject": "Votre facture", "bodyPreview": "Montant : 54 €"},
            {"from": {"emailAddress": {"name": "Paul"}}, "subject": "Dîner samedi ?", "bodyPreview": "Tu viens ?"},
            {"from": {"emailAddress": {"name": "Fnac"}}, "subject": "Promos", "bodyPreview": "-20 %"},
        ][:limit]


@pytest.fixture()
def inbox(monkeypatch):
    fake = BusyInbox()
    monkeypatch.setattr(main.context, "google", fake)
    monkeypatch.setattr(main.context.dashboard, "google", fake)
    monkeypatch.setattr(llm, "warm_up", lambda: None)
    monkeypatch.setattr(llm, "ollama_status", lambda: (True, "ok"))
    return fake


def test_inbox_is_sorted_by_the_model(inbox, monkeypatch):
    seen = []
    monkeypatch.setattr(
        llm, "complete",
        lambda system, prompt, *a, **k: seen.append(prompt) or "Paul attend une réponse pour samedi ; le reste : une facture et une publicité.",
    )
    reply = ask("Lis-moi mes mails")
    assert reply["action"] == "mail_resume"
    assert reply["speech"].startswith("3 messages non lus, Monsieur. Paul attend une réponse")
    assert reply["reply"].startswith("En bref : Paul attend") and "EDF — Votre facture" in reply["reply"]
    assert "Paul | Dîner samedi ? | Tu viens ?" in seen[0]


def test_inbox_without_model_is_still_listed(inbox, monkeypatch):
    monkeypatch.setattr(llm, "ollama_status", lambda: (False, "hors ligne"))
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("le modèle ne doit pas être appelé"))
    reply = ask("Lis-moi mes mails")
    assert "Vous avez 3 messages non lus" in reply["reply"] and "En bref" not in reply["reply"]


# ── Météo heure par heure ──────────────────────────────────────────────────

def _hourly_payload(rain_from: int):
    times = [f"2026-10-15T{hour:02d}:00" for hour in range(24)] + [f"2026-10-16T{hour:02d}:00" for hour in range(6)]
    return {
        "time": times,
        "temperature_2m": [10 + (index % 24) // 3 for index in range(len(times))],
        "precipitation_probability": [80 if index >= rain_from else 5 for index in range(len(times))],
        "weather_code": [61 if index >= rain_from else 1 for index in range(len(times))],
    }


def test_hours_start_at_the_current_hour():
    hours = weather._hours(_hourly_payload(rain_from=20), "2026-10-15T14:15", count=5)
    assert [item["time"][-5:] for item in hours] == ["14:00", "15:00", "16:00", "17:00", "18:00"]
    assert hours[0] == {"time": "2026-10-15T14:00", "temperature": 14, "rain_probability": 5, "description": "ciel plutôt dégagé"}


def test_evening_forecast_says_when_the_rain_comes(monkeypatch):
    hours = weather._hours(_hourly_payload(rain_from=20), "2026-10-15T14:00")
    monkeypatch.setattr(weather, "get_weather", lambda city=None: {"city": "Colomiers", "hours": hours})
    reply = weather.handle_weather({"day": "hours", "period": "soir"})
    assert reply.text.startswith("Ce soir à Colomiers, Monsieur :") and "- 18 h :" in reply.text and "- 23 h :" in reply.text
    assert "- 17 h" not in reply.text
    assert "De la pluie probable à partir de 20 heures" in reply.spoken and "parapluie" in reply.spoken


def test_next_hours_without_rain(monkeypatch):
    hours = weather._hours(_hourly_payload(rain_from=99), "2026-10-15T08:00")
    monkeypatch.setattr(weather, "get_weather", lambda city=None: {"city": "Paris", "hours": hours})
    reply = weather.handle_weather({"day": "hours"})
    assert len(reply.text.splitlines()) == 13 and "Pas de pluie en vue" in reply.spoken


@pytest.mark.parametrize("phrase,period", [
    ("Quel temps fera-t-il ce soir ?", "soir"),
    ("Est-ce qu'il va pleuvoir cet après-midi ?", "apres-midi"),
    ("À quelle heure va-t-il pleuvoir ?", None),
    ("Météo heure par heure", None),
])
def test_hourly_weather_is_understood(phrase, period):
    params = detect_action(phrase)["params"]
    assert params["day"] == "hours" and params.get("period") == period and params["city"] is None


def test_tomorrow_evening_stays_a_daily_forecast():
    assert detect_action("Quel temps demain soir ?")["params"]["day"] == "tomorrow"


# ── Rendez-vous : prévenir au moment de partir ─────────────────────────────

class Agenda:
    def __init__(self, events):
        self.events = events

    def is_configured(self):
        return True

    def list_events_in_range(self, start, end):
        return [event for event in self.events if start <= event["start"] < end]


def _event(title, start, location=""):
    return {"id": title, "subject": title, "start": start, "end": start + timedelta(hours=1), "location": location}


def test_meeting_with_a_trip_is_announced_when_it_is_time_to_leave():
    now = datetime(2026, 10, 15, 14, 0, tzinfo=PARIS)
    agenda = Agenda([_event("Dentiste", now + timedelta(minutes=40), "Cabinet dentaire, Colomiers")])
    trips = []
    watcher = heads_up.MeetingWatcher(lambda: agenda, travel_seconds=lambda place: trips.append(place) or 25 * 60, lead_minutes=10)

    assert watcher.due(now) == []  # départ dans 5 minutes : pas encore
    (text, speech), = watcher.due(now + timedelta(minutes=5))
    assert "comptez 25 minutes de trajet" in text and "Cabinet dentaire" in text
    assert speech == "Monsieur, Dentiste est à 14 heures 40. Comptez 25 minutes de trajet : il serait temps de partir."
    assert watcher.due(now + timedelta(minutes=6)) == []  # une seule annonce
    assert trips == ["Cabinet dentaire, Colomiers"]  # trajet calculé une fois


def test_meeting_without_place_is_announced_a_few_minutes_before():
    now = datetime(2026, 10, 15, 9, 0, tzinfo=PARIS)
    agenda = Agenda([_event("Réunion : budget", now + timedelta(minutes=30), "Google Meet")])
    watcher = heads_up.MeetingWatcher(lambda: agenda, travel_seconds=lambda place: pytest.fail("pas de trajet en visio"), lead_minutes=10)
    assert watcher.due(now) == []
    (_text, speech), = watcher.due(now + timedelta(minutes=21))
    assert speech == "Monsieur, Réunion : budget commence dans 9 minutes."
    assert watcher.soon(now) is True


def test_meeting_reminders_can_be_turned_off():
    now = datetime(2026, 10, 15, 9, 0, tzinfo=PARIS)
    agenda = Agenda([_event("Appel", now + timedelta(minutes=5))])
    watcher = heads_up.MeetingWatcher(lambda: agenda, lead_minutes=0)
    assert watcher.due(now) == [] and watcher.soon(now) is False


def test_unreachable_place_falls_back_to_a_simple_reminder():
    now = datetime(2026, 10, 15, 9, 0, tzinfo=PARIS)

    def no_route(place):
        raise RuntimeError("service d'itinéraires injoignable")

    agenda = Agenda([_event("Garage", now + timedelta(minutes=8), "Garage du Centre")])
    watcher = heads_up.MeetingWatcher(lambda: agenda, travel_seconds=no_route, lead_minutes=10)
    (_text, speech), = watcher.due(now)
    assert speech == "Monsieur, Garage commence dans 8 minutes."


# ── Code : tests, correction et explication ────────────────────────────────

TESTS_OK = '''TITRE: Tests de Bonjour le monde
RÉSUMÉ: Vérifie que main affiche Bonjour ; lancez python3 test_bonjour_le_monde.py.
```python
import io
import unittest
from contextlib import redirect_stdout


class BonjourTest(unittest.TestCase):
    def test_main(self):
        out = io.StringIO()
        with redirect_stdout(out):
            programme.main()
        self.assertEqual(out.getvalue(), "Bonjour\\n")

    def test_main_returns_nothing(self):
        with redirect_stdout(io.StringIO()):
            self.assertIsNone(programme.main())


if __name__ == "__main__":
    unittest.main()
```'''

TESTS_IMPORTING = TESTS_OK.replace("import io\n", "import io\nimport programme\n")


def test_tests_are_written_for_the_last_program_and_actually_run(studio):  # noqa: F811
    studio["answers"].extend([SCRIPT_OK, TESTS_IMPORTING, TESTS_OK])
    ask("Crée-moi un script Python qui dit bonjour")
    reply = ask("Écris les tests du script")
    assert reply["action"] == "code_tests" and "Je m'occupe des tests" in reply["reply"]

    # Le premier essai importait « programme » : refusé par le contrôle qualité.
    assert "n'importe pas `programme`" in studio["prompts"][2]["prompt"]
    tests = studio["opened"][1].path
    assert tests.name == "test_bonjour_le_monde.py" and tests.parent == studio["opened"][0].path.parent

    # Les tests livrés tournent vraiment à côté du programme.
    import subprocess
    import sys
    run = subprocess.run([sys.executable, "-B", tests.name], cwd=tests.parent, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert "Ran 2 tests" in run.stderr


def test_tests_are_only_compiled_without_a_sandbox():
    failing = TESTS_OK.split("```python\n")[1].split("```")[0].replace('"Bonjour\\n"', '"Salut\\n"')
    program = SCRIPT_OK.split("```python\n")[1].split("```")[0]
    header = code.TESTS_HEADER.format(title="Bonjour", tests_name="test_b.py", program_name="b.py")
    # Sans bac à sable (hors macOS), seule la syntaxe est vérifiée.
    assert code.run_tests("b.py", program, "test_b.py", header + failing) is None
    assert "erreur de syntaxe" in code.run_tests("b.py", program, "test_b.py", "def (")


def test_tests_need_a_python_program(studio):  # noqa: F811
    assert "pas de programme récent" in ask("Écris les tests du script")["reply"]


def test_an_existing_file_is_fixed_without_touching_the_original(studio, tmp_path, monkeypatch):  # noqa: F811
    original = tmp_path / "projet" / "convertisseur.py"
    original.parent.mkdir()
    original.write_text("def euros(dollars):\n    return dollars * 0,92\n", encoding="utf-8")
    monkeypatch.setattr(files, "find", lambda query, limit=8: [original] if query == "convertisseur.py" else [])
    studio["answers"].append(
        "TITRE: convertisseur.py\nRÉSUMÉ: La virgule faisait renvoyer un tuple : remplacée par un point.\n"
        "```python\ndef euros(dollars):\n    return dollars * 0.92\n```"
    )
    reply = ask("Corrige le fichier convertisseur.py")
    assert reply["action"] == "fix_code" and "correction de convertisseur.py" in reply["reply"]

    fixed = studio["opened"][0]
    assert fixed.path.name == "convertisseur-corrige.py" and "0.92" in fixed.path.read_text()
    assert original.read_text().endswith("0,92\n")  # l'original est intact
    assert "2 lignes modifiées" in fixed.summary and str(original) in fixed.summary
    assert "0,92" in studio["prompts"][0]["prompt"]


def test_a_missing_file_is_reported(studio, monkeypatch):  # noqa: F811
    monkeypatch.setattr(files, "find", lambda query, limit=8: [])
    assert "Je ne trouve aucun fichier nommé « inconnu.py »" in ask("Corrige le fichier inconnu.py")["reply"]


def test_a_file_is_explained(studio, tmp_path, monkeypatch):  # noqa: F811
    script = tmp_path / "main.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setattr(files, "find", lambda query, limit=8: [script])
    studio["answers"].append("Ce fichier affiche ok. Lancez-le avec python3 main.py.")
    reply = ask("Explique-moi le fichier main.py")
    assert reply["action"] == "explain_code" and reply["speech"] == "Ce fichier affiche ok. Lancez-le avec python3 main.py."
    assert "print('ok')" in studio["prompts"][0]["prompt"]


@pytest.mark.parametrize("phrase,action", [
    ("Génère des tests unitaires pour ce programme", "code_tests"),
    ("Corrige le fichier ~/Developer/app/main.js", "fix_code"),
    ("Que fait le script tri_photos.py ?", "explain_code"),
    ("Explique-moi ce script", "explain_code"),
    ("Corrige le script", "revise_creation"),
    ("Fais des tests de grossesse", None),
    ("Explique-moi la relativité", None),
])
def test_code_tools_are_understood(phrase, action):
    assert (detect_action(phrase) or {}).get("action") == action


# ── Vitesse : l'état d'Ollama n'est pas redemandé à chaque phrase ──────────

def test_ollama_status_is_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "_read_ollama_status", lambda: calls.append(1) or (True, "ok"))
    llm.forget_ollama_status()
    assert llm.ollama_status() == (True, "ok") and llm.ollama_status() == (True, "ok")
    assert len(calls) == 1
    llm.forget_ollama_status()
    llm.ollama_status()
    assert len(calls) == 2
    llm.forget_ollama_status()


def test_creation_model_does_not_block_the_conversation(monkeypatch):
    from controllers import creation

    controller = next(c for c in main.jarvis.controllers if c.name == "création")
    monkeypatch.setitem(controller.workshop.busy, "l'écriture du programme", 0.0)
    assert controller.occupied_with() == ["l'écriture du programme"]
    monkeypatch.setattr(creation, "CREATION_MODEL", "gemma4:26b")
    assert controller.occupied_with() == []


def test_creations_use_the_creation_model(monkeypatch):
    used = []
    monkeypatch.setattr(atelier, "CREATION_MODEL", "gemma4:26b")
    monkeypatch.setattr(llm, "complete", lambda *a, **k: used.append(k.get("model")) or "ok")
    atelier.generate("système", "demande", 0.2)
    assert used == ["gemma4:26b"]


# ── Heures dites : dans le fuseau de l'utilisateur ─────────────────────────

def test_spoken_times_use_the_user_timezone(monkeypatch):
    import config

    monkeypatch.setattr(config, "USER_TIMEZONE", ZoneInfo("Pacific/Kiritimati"))  # UTC+14
    kiritimati = datetime.now(ZoneInfo("Pacific/Kiritimati")).replace(tzinfo=None)
    assert abs((config.local_now() - kiritimati).total_seconds()) < 5


# ── Design : plusieurs propositions, icônes ; documents en PDF ─────────────

from test_creation import LOGO_OK, PALETTE_OK  # noqa: E402


def test_several_logos_are_proposed_then_one_is_chosen(studio):  # noqa: F811
    second = LOGO_OK.replace("Club Tennis", "Monogramme CT").replace("#C6E03B", "#1D7A5F")
    studio["answers"].extend([LOGO_OK, second, LOGO_OK.replace("Club Tennis", "Badge")])
    reply = ask("Propose-moi trois logos pour mon club de tennis")
    assert reply["action"] == "design_logo" and "des 3 propositions de logo" in reply["reply"]

    # Chaque proposition a reçu sa direction, sans relecture visuelle ni icônes.
    directions = [prompt["prompt"] for prompt in studio["prompts"]]
    assert "géométrique" in directions[0] and "monogramme" in directions[1] and "emblème" in directions[2]
    board = studio["opened"][0]
    assert board.kind == "propositions" and len(board.extra["choices"]) == 3
    assert "1. Club Tennis" in board.path.read_text() and "3. Badge" in board.path.read_text()
    assert "la deuxième" in studio["announced"][0]["speech"]

    assert "Laquelle dois-je retoucher" in ask("Change les couleurs du logo")["reply"]

    chosen = ask("Je prends la deuxième")
    assert chosen["action"] == "choose_creation" and "Monogramme CT" in chosen["reply"]
    assert studio["workshop"].last.title == "Monogramme CT"
    icons = studio["workshop"].last.extra["icons"]
    assert (icons / "favicon.svg").exists() and (icons / "site.webmanifest").exists()


def test_choosing_without_proposals(studio):  # noqa: F811
    assert "pas de propositions en attente" in ask("La deuxième")["reply"]


def test_palette_proposals(studio):  # noqa: F811
    studio["answers"].extend([PALETTE_OK, PALETTE_OK])
    ask("Crée deux palettes pour un spa")
    board = studio["opened"][0]
    assert len(board.extra["choices"]) == 2 and "swatches" in board.path.read_text()


def test_a_single_logo_comes_with_its_icons(studio):  # noqa: F811
    studio["answers"].append(LOGO_OK)
    ask("Fais un logo pour mon club de tennis")
    logo = studio["opened"][0]
    assert "Favicon et icônes d'app" in logo.summary
    snippet = (logo.extra["icons"] / "a-coller-dans-la-page.html").read_text()
    assert 'rel="icon" href="favicon.svg"' in snippet


def test_icons_need_a_logo(studio):  # noqa: F811
    assert "Il me faut d'abord un logo" in ask("Fais un favicon avec le logo")["reply"]


DOCUMENT_OK = '''TITRE: Lettre de résiliation
RÉSUMÉ: Une lettre formelle de résiliation.
```html
<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Résiliation</title></head><body>
<h1>Résiliation de mon abonnement</h1>
<p>''' + " ".join(["Madame, Monsieur, je vous informe de ma décision de résilier mon abonnement."] * 8) + '''</p>
<p>[Votre nom]</p></body></html>
```'''

CHROMIUM = "/opt/pw-browsers/chromium"


def test_document_is_delivered_as_pdf_when_asked(studio, monkeypatch):  # noqa: F811
    import os
    from pathlib import Path

    if not Path(CHROMIUM).exists():
        pytest.skip("pas de navigateur pour l'export PDF")
    monkeypatch.setenv("JARVIS_CHROME", CHROMIUM)
    studio["answers"].append(DOCUMENT_OK)
    reply = ask("Rédige une lettre de résiliation de ma salle de sport en PDF")
    assert reply["action"] == "write_document"
    document = studio["opened"][0]
    assert document.path.suffix == ".pdf" and document.path.read_bytes().startswith(b"%PDF")
    assert os.path.exists(document.extra["html"])


def test_pdf_export_without_browser(studio, monkeypatch):  # noqa: F811
    monkeypatch.setenv("JARVIS_CHROME", "/nulle/part/chrome")
    studio["answers"].append(DOCUMENT_OK)
    ask("Rédige une lettre de résiliation de ma salle de sport")
    reply = ask("Exporte-le en PDF")
    assert reply["action"] == "export_pdf" and "Il me faut Chrome, Edge ou Brave" in reply["reply"]


def test_pdf_export_needs_a_page_or_a_document(studio):  # noqa: F811
    assert "pas de page ni de document récent" in ask("Mets-le en PDF")["reply"]


# ── Les créations, consultables depuis le téléphone ───────────────────────

def test_creations_are_served_to_other_devices(studio, monkeypatch):  # noqa: F811
    from routes import creations

    studio["answers"].append(SCRIPT_OK)
    ask("Crée-moi un script Python qui dit bonjour")
    url = studio["announced"][0]["url"]
    assert url == "/api/creations/code/bonjour-le-monde.py"

    with TestClient(main.app, base_url="http://localhost") as http:
        listing = http.get("/api/creations").json()["creations"]
        assert listing[0]["url"] == url
        served = http.get(url)
        assert served.status_code == 200 and 'print("Bonjour")' in served.text
        assert served.headers["content-type"].startswith("text/plain")
        assert http.get("/api/creations/../../config.py").status_code == 404
        assert http.get("/api/creations/code/%2E%2E/%2E%2E/secret").status_code == 404
        # Depuis un autre appareil (relayé par Tailscale), le code d'accès reste exigé.
        relayed = {"X-Forwarded-For": "100.90.121.78", "Tailscale-User-Login": "moi@exemple.com"}
        assert http.get(url, headers=relayed).status_code in {401, 403}
    assert creations.creation_url(studio["workshop"].root.parent / "ailleurs.txt", studio["workshop"].root) is None


@pytest.mark.parametrize("phrase,action,params", [
    ("Donne-moi des propositions de logo pour mon club", "design_logo", {"count": 3}),
    ("Crée deux palettes pour un spa", "design_palette", {"count": 2}),
    ("La deuxième", "choose_creation", {"index": 2}),
    ("Proposition numéro 3", "choose_creation", {"index": 3}),
    ("Rédige une lettre de motivation en PDF", "write_document", {"format": "pdf"}),
    ("Mets la lettre en PDF", "export_pdf", None),
    ("Fais-en des icônes", "make_icons", None),
    ("Fais un favicon avec le logo", "make_icons", None),
])
def test_design_phrases_are_understood(phrase, action, params):
    detected = detect_action(phrase)
    assert detected["action"] == action
    for key, value in (params or {}).items():
        assert detected["params"][key] == value


def test_ordinals_alone_are_not_mistaken():
    assert detect_action("La deuxième guerre mondiale") is None
