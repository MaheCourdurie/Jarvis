"""Les capacités ajoutées : mails avancés, agenda, alarmes, poste, météo, mémoire, routines,
maison, trajets, musique, fichiers, traduction, routage de secours et journal des incompris.

Tout ce qui sortirait du poste (Gmail, cartes, modèle, AppleScript) est simulé.
"""

import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import main
from agents import files, home, music, system, travel
from core import fallback
from services import alarm_store, llm, weather
from test_api import FakeGoogle


class FakeMailbox(FakeGoogle):
    """Le compte Google simulé, avec recherche, lecture, réponse et rangement."""

    def __init__(self):
        super().__init__()
        self.mails = [
            {"id": "m1", "threadId": "t1", "from": {"emailAddress": {"name": "Paul", "address": "paul@exemple.com"}},
             "subject": "Dîner samedi", "bodyPreview": "Tu viens samedi ?", "messageIdHeader": "<m1@x>", "references": ""},
        ]
        self.queries, self.replies, self.archived, self.trashed, self.moved = [], [], [], [], []

    def search_emails(self, query, limit=5):
        self.queries.append(query)
        return self.mails[:limit]

    def get_email(self, message_id):
        return {**self.mails[0], "body": "Salut, tu viens dîner samedi soir ?"}

    def reply_to(self, message, body):
        self.replies.append((message["id"], body))

    def archive_email(self, message_id):
        self.archived.append(message_id)

    def trash_email(self, message_id):
        self.trashed.append(message_id)

    def move_event(self, event_id, start, end):
        self.moved.append((event_id, start, end))
        return {}

    def create_event(self, subject, start, end, recurrence=None):
        self.created.append((subject, start, end, recurrence))
        return {"webLink": ""}


@pytest.fixture()
def http(monkeypatch):
    fake = FakeMailbox()
    monkeypatch.setattr(main.context, "google", fake)
    monkeypatch.setattr(main.context.dashboard, "google", fake)
    main.context.alarms.delete_all_alarms()
    monkeypatch.setattr(llm, "ollama_status", lambda: (True, "ok"))
    monkeypatch.setattr(llm, "warm_up", lambda: None)
    monkeypatch.setattr(llm, "supports_tools", lambda: False)
    # Le modèle répond « none » au routage de secours et recopie le texte pour le reste.
    monkeypatch.setattr(llm, "complete", lambda system, prompt, *args, **kwargs: '{"action": "none"}' if "répartiteur" in system else prompt.split(":")[-1].strip())
    monkeypatch.setattr(llm, "chat_stream", lambda *args, **kwargs: iter(["Bien, Monsieur."]))
    with TestClient(main.app, base_url="http://localhost") as client:
        client.fake = fake
        yield client


def ask(http, message, **extra):
    response = http.post("/api/chat", json={"message": message, "client": "hud", **extra})
    assert response.status_code == 200, response.text
    return response.json()


# ── Messagerie ─────────────────────────────────────────────────────────────

def test_reply_is_shown_then_sent_in_the_thread(http):
    draft = ask(http, "Réponds à Paul que c'est d'accord pour samedi")
    assert draft["action"] == "reply_mail" and draft["pending"]["action"] == "reply_mail"
    assert http.fake.queries == ["from:paul@exemple.com"] and http.fake.replies == []  # Paul est dans le carnet
    done = ask(http, "oui", pending=draft["pending"])
    assert "envoyée" in done["reply"] and http.fake.replies[0][0] == "m1"


def test_read_search_and_tidy_mail(http):
    assert "tu viens dîner samedi soir" in ask(http, "Lis-moi le mail de Paul")["reply"]
    assert "Dîner samedi" in ask(http, "Cherche les mails de la banque")["reply"]
    assert http.fake.queries[-1] == "banque"
    asked = ask(http, "Archive le dernier mail")
    assert http.fake.archived == [] and "archiver" in asked["reply"]
    ask(http, "oui", pending=asked["pending"])
    assert http.fake.archived == ["m1"]


# ── Agenda ─────────────────────────────────────────────────────────────────

def test_event_is_moved_keeping_its_duration(http):
    reply = ask(http, "Décale le dentiste à 17h")
    event_id, start, end = http.fake.moved[0]
    assert reply["action"] == "move_event" and event_id == "evt1"
    assert (start.hour, start.minute) == (17, 0) and end - start == timedelta(hours=1)


def test_recurring_event(http):
    reply = ask(http, "Ajoute une réunion d'équipe tous les lundis à 9h")
    subject, start, _end, rule = http.fake.created[0]
    assert rule == "FREQ=WEEKLY;BYDAY=MO" and start.weekday() == 0 and start.hour == 9
    assert "tous les lundis" in reply["reply"]


# ── Alarmes ────────────────────────────────────────────────────────────────

def test_recurring_alarm_reschedules_itself():
    now = datetime(2026, 10, 16, 7, 0)  # un vendredi
    assert alarm_store.next_occurrence(now, "weekdays", now).weekday() == 0  # lundi suivant
    assert alarm_store.next_occurrence(now, "daily", now) == now + timedelta(days=1)
    assert alarm_store.next_occurrence(now, "weekly:2", now).weekday() == 2


def test_recurring_alarm_and_snooze(http):
    reply = ask(http, "Réveille-moi tous les jours de semaine à 6h45")
    assert "du lundi au vendredi" in reply["reply"]
    assert main.context.alarms.list_alarms()[0]["repeat"] == "weekdays"

    main.context.alarms.delete_all_alarms()
    rung = main.context.alarms.create_alarm(datetime.now(main.context.alarms.timezone) - timedelta(seconds=5), "Réveil")
    main.context.alarms.trigger_due_alarms()
    snoozed = ask(http, "Encore 10 minutes")
    assert snoozed["action"] == "snooze_alarm" and "« Réveil »" in snoozed["reply"]
    assert rung["id"] != main.context.alarms.list_alarms()[0]["id"]


def test_timer_shows_time_left(http):
    ask(http, "Lance un minuteur de 10 minutes")
    reply = ask(http, "Il reste combien de temps sur le minuteur ?")
    assert "reste" in reply["reply"] and "Il reste" in reply["speech"]


# ── Poste ──────────────────────────────────────────────────────────────────

def test_poste_commands_run_the_right_tools(http, monkeypatch):
    calls = []
    monkeypatch.setattr(system, "SYSTEM", "darwin")
    monkeypatch.setattr(system, "_run", lambda command, timeout=10.0: calls.append(command) or (True, "Hardware Port: Wi-Fi\nDevice: en0"))
    ask(http, "Active le mode sombre")
    ask(http, "Coupe le Wi-Fi")
    assert "set dark mode to true" in calls[0][-1]
    assert calls[-1] == ["networksetup", "-setairportpower", "en0", "off"]


def test_poste_is_refused_to_remote_clients(http):
    reply = ask(http, "Verrouille le Mac", client="discord")
    assert "depuis le poste" in reply["reply"]


# ── Informations ───────────────────────────────────────────────────────────

def test_weekend_forecast():
    days = [{"time": (datetime(2026, 10, 15) + timedelta(days=i)).date().isoformat(), "description": "ciel dégagé",
             "min": 10, "max": 15 + i, "rain_probability": 70 if i == 3 else 10} for i in range(7)]
    reply = weather._forecast_reply({"city": "Colomiers", "days": days}, "weekend")
    assert "Samedi" in reply.text and "Dimanche" in reply.text and "pluie probable dimanche" in reply.speech


# ── Mémoire, routines, maison ──────────────────────────────────────────────

def test_memory_is_kept_recalled_and_given_to_the_model(http):
    ask(http, "Souviens-toi que je prends mon café sans sucre")
    assert "café sans sucre" in ask(http, "Qu'est-ce que tu sais sur moi ?")["reply"]
    assert "café sans sucre" in main.savoir.memory.as_context()
    ask(http, "Oublie que je prends mon café sans sucre")
    assert "rien confié" in ask(http, "Qu'est-ce que tu sais sur moi ?")["reply"]


def test_routine_runs_each_step_through_jarvis(http):
    ask(http, "Crée une routine test : quelle heure est-il, puis quelle est la date")
    reply = ask(http, "Lance la routine test")
    assert reply["action"] == "run_routine"
    assert "quelle heure est-il → Il est" in reply["reply"] and "quelle est la date →" in reply["reply"]


def test_shortcut_matching():
    names = ["Allumer salon", "Éteindre salon", "Fermer les volets"]
    assert home.best_match("allume la lumière du salon", names) == "Allumer salon"
    assert home.best_match("éteins le salon", names) == "Éteindre salon"
    assert home.best_match("allume la cuisine", names) is None


# ── Trajets, musique, fichiers, traduction ─────────────────────────────────

def test_travel_time(http, monkeypatch):
    places = {"Paris": (48.86, 2.35, "Paris"), "Toulouse": (43.6, 1.44, "Toulouse")}
    monkeypatch.setattr(travel, "locate", lambda place, near=None: places.get(place, (43.63, 1.33, "Colomiers")))
    monkeypatch.setattr(travel, "route", lambda a, b, mode: (25 * 60, 18_000))
    reply = ask(http, "Combien de temps pour aller à Toulouse ?")
    assert "25 minutes" in reply["reply"] and "18 km" in reply["reply"] and "embouteillages" in reply["reply"]


def test_music_controls_the_player(http, monkeypatch):
    calls = []
    monkeypatch.setattr(music, "SYSTEM", "darwin")
    monkeypatch.setattr(music, "player", lambda: music.SPOTIFY)
    monkeypatch.setattr(music, "_run", lambda command, timeout=10.0: calls.append(command) or (True, ""))
    ask(http, "Chanson suivante")
    ask(http, "Mets du Daft Punk")
    assert calls[0][-1] == 'tell application "Spotify" to next track'
    assert calls[1] == ["open", "spotify:search:Daft%20Punk"]


def test_files_are_found(http, monkeypatch, tmp_path):
    found = tmp_path / "budget 2026.xlsx"
    found.write_text("x")
    monkeypatch.setattr(files, "SYSTEM", "darwin")
    monkeypatch.setattr(files, "_run", lambda command, timeout=10.0: (True, f"{found}\n/Users/x/Library/cache.db"))
    reply = ask(http, "Où est mon fichier budget 2026 ?")
    assert reply["action"] == "find_file" and "budget 2026.xlsx" in reply["reply"] and "Library" not in reply["reply"]


def test_translation(http, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *args, **kwargs: "I'm late")
    reply = ask(http, "Traduis je suis en retard en anglais")
    assert reply["reply"] == "En anglais : « I'm late »"


# ── Routage de secours et journal des incompris ────────────────────────────

def test_unknown_command_is_routed_by_the_model_and_logged(http, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *args, **kwargs: '{"action": "list_alarms"}')
    reply = ask(http, "Montre-moi ce qui va sonner bientôt")
    assert reply["action"] == "list_alarms"
    assert fallback.recent_misses()[-1] == {**fallback.recent_misses()[-1], "phrase": "Montre-moi ce qui va sonner bientôt", "modele": "list_alarms"}
    assert "Montre-moi ce qui va sonner bientôt" in ask(http, "/incompris")["reply"]


def test_model_cannot_pick_an_unsafe_action(http, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *args, **kwargs: '{"action": "delete_alarms_all"}')
    reply = ask(http, "Supprime tout ce qui sonne")
    assert reply["action"] != "delete_alarms_all"


def test_questions_are_not_logged_as_misses(http):
    before = len(fallback.recent_misses(1000))
    ask(http, "Pourquoi le ciel est bleu ?")
    assert len(fallback.recent_misses(1000)) == before
