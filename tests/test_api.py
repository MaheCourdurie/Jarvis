"""Tests de bout en bout de l'API avec un faux compte Google et un faux modèle."""

import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import main
from config import local_now
from services import events, llm
from agents import system as system_actions
from services import weather


class FakeGoogle:
    """Compte Google simulé : enregistre ce que Jarvis envoie et supprime."""

    timezone = main.context.google.timezone
    timezone_name = "Europe/Paris"

    def __init__(self):
        self.configured = True
        self.sent = []
        self.created = []
        self.deleted_ranges = []
        now = datetime.now(self.timezone)
        start = (now + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)
        self.events = [
            {"id": "evt1", "subject": "Dentiste", "location": "", "isAllDay": False,
             "start": start, "end": start + timedelta(hours=1), "webLink": ""},
        ]

    def is_configured(self):
        return self.configured

    def status(self):
        return {"provider": "google", "provider_label": "Google", "configured": self.configured,
                "missing_keys": [] if self.configured else ["GOOGLE_TOKEN_FILE"]}

    def get_unread_emails(self, limit=5):
        return [{"from": {"emailAddress": {"name": "Sophie Martin"}}, "subject": "Devis projet web",
                 "bodyPreview": "Bonjour, pouvez-vous m'envoyer le devis ?"}]

    def get_latest_email(self):
        return self.get_unread_emails()[0]

    def send_mail(self, to_email, subject, body):
        self.sent.append((to_email, subject, body))

    def list_week_events(self):
        return list(self.events)

    def list_events_in_range(self, start, end):
        return [event for event in self.events if event["start"] < end and event["end"] > start]

    def create_event(self, subject, start, end):
        self.created.append((subject, start, end))
        return {"webLink": "https://calendar.google.com/event?eid=new"}

    def delete_event(self, event_id):
        return event_id == "evt1"

    def delete_events_in_range(self, start, end):
        self.deleted_ranges.append((start, end))
        return self.list_events_in_range(start, end)

    def disconnect(self, revoke=True):
        return {"token_deleted": False}


@pytest.fixture()
def google(monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(main.context, "google", fake)
    monkeypatch.setattr(main.context.dashboard, "google", fake)
    main.context.dashboard.invalidate()
    main.context.alarms.delete_all_alarms()
    # Ni réseau ni modèle pendant les tests.
    monkeypatch.setattr(weather, "get_weather", lambda city=None: {
        "city": city or "Paris", "temperature": 18, "apparent": 18, "code": 0, "description": "ciel dégagé",
        "wind_kmh": 10, "humidity": 50, "is_day": True,
        "today": {"description": "ciel dégagé", "min": 12, "max": 21, "rain_probability": 10},
        "tomorrow": {"description": "pluie", "min": 11, "max": 17, "rain_probability": 80},
    })
    monkeypatch.setattr("agents.briefing.get_weather", weather.get_weather)
    monkeypatch.setattr(llm, "ollama_status", lambda: (True, "ok"))
    monkeypatch.setattr(llm, "warm_up", lambda: None)
    monkeypatch.setattr(llm, "supports_tools", lambda: False)
    monkeypatch.setattr(llm, "complete", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("hors ligne")))
    return fake


@pytest.fixture()
def client(google):
    with TestClient(main.app, base_url="http://localhost") as test_client:
        yield test_client


def chat(http, message, **extra):
    response = http.post("/api/chat", json={"message": message, "client": "hud", **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_status(client):
    status = client.get("/api/status").json()
    assert status["persona"] == {"title": "Monsieur", "city": "Paris", "wake_word": "jarvis"}
    assert status["voice"]["tts"]["engine"] == "off"
    assert status["strict"] is False


def test_only_this_machine_can_drive_the_api(client):
    # Un site web quelconque ne doit pas pouvoir faire agir Jarvis.
    preflight = client.options("/api/chat", headers={
        "Origin": "https://site-malveillant.example", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    assert "access-control-allow-origin" not in preflight.headers

    allowed = client.options("/api/chat", headers={
        "Origin": "http://localhost:8000", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:8000"

    # Protection contre le DNS rebinding : l'en-tête Host doit désigner ce poste.
    assert client.get("/api/status", headers={"Host": "attaquant.example"}).status_code == 400


def test_time_weather_and_smalltalk(client):
    assert chat(client, "Jarvis, tu es là ?")["reply"] == "Pour vous, Monsieur, toujours."
    time_reply = chat(client, "Quelle heure est-il ?")
    assert time_reply["action"] == "time" and time_reply["reply"].startswith("Il est ")
    weather_reply = chat(client, "Quel temps fait-il à Lyon demain ?")
    assert "Demain à Lyon" in weather_reply["reply"] and "parapluie" in weather_reply["speech"]


def test_alarm_lifecycle_with_confirmation(client):
    created = chat(client, "Minuteur de 10 minutes")
    assert created["action"] == "set_alarm" and "Minuteur lancé, Monsieur : 10 minutes" in created["reply"]
    chat(client, "Rappelle-moi demain à 9h d'appeler le dentiste")
    assert "2 alarmes actives" in chat(client, "Quelles sont mes alarmes ?")["speech"]

    ask = chat(client, "Supprime toutes mes alarmes")
    assert ask["pending"] == {"action": "delete_alarms_all", "params": {}}
    assert len(main.context.alarms.list_alarms()) == 2  # rien n'est supprimé avant le « oui »

    refused = chat(client, "Non", pending=ask["pending"])
    assert refused["action"] == "cancelled" and len(main.context.alarms.list_alarms()) == 2

    confirmed = chat(client, "Oui", pending=ask["pending"])
    assert "toutes les alarmes sont supprimées" in confirmed["reply"]
    assert main.context.alarms.list_alarms() == []


def test_alarm_wording(client):
    assert "Minuteur lancé, Monsieur : 45 secondes" in chat(client, "Minuteur de 45 secondes")["reply"]
    assert "Minuteur lancé, Monsieur : 1 h 30" in chat(client, "Minuteur de 1h30")["reply"]
    wake = chat(client, "Réveille-moi demain à 7h30")
    assert wake["reply"].startswith("Réveil programmé pour demain à 7 h 30, Monsieur. [id:")
    assert wake["speech"] == "Réveil programmé pour demain à 7 heures 30, Monsieur."
    named = chat(client, 'Mets une alarme demain à 8h pour "Sport"')
    assert "Alarme programmée pour demain à 8 h, Monsieur : « Sport »." in named["reply"]


def test_past_alarm_is_refused(client):
    past = (local_now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
    reply = chat(client, f'/setalarm "{past}" "Trop tard"')
    assert "déjà passée" in reply["reply"] and main.context.alarms.list_alarms() == []


def test_mail_is_shown_before_being_sent(client, google):
    draft = chat(client, "Envoie un mail à Paul pour lui dire que le devis est prêt")
    assert draft["action"] == "send_mail" and draft["pending"]["action"] == "send_mail"
    assert "Dois-je l'envoyer ?" in draft["reply"] and "pour Paul" in draft["reply"]
    assert google.sent == []

    sent = chat(client, "Oui, envoie-le", pending=draft["pending"])
    assert sent["reply"].startswith("Message envoyé à Paul, Monsieur")
    assert len(google.sent) == 1
    to_email, subject, body = google.sent[0]
    # Le message envoyé est exactement celui qui a été présenté.
    assert to_email == "paul@exemple.com" and subject in draft["reply"] and body in draft["reply"]


def test_slash_sendmail_is_immediate_and_filtered(client, google):
    chat(client, '/sendmail "a@b.fr" "Objet" "Bonjour, à demain."')
    assert google.sent == [("a@b.fr", "Objet", "Bonjour, à demain.")]

    blocked = chat(client, '/sendmail "a@b.fr" "Objet" "espèce de connard"')
    assert "inapproprié" in blocked["reply"] and len(google.sent) == 1


def test_calendar_conflict_is_reported(client, google):
    reply = chat(client, "Planifie une réunion avec Sophie demain à 15h")
    assert google.created and google.created[0][0] == "Réunion avec Sophie"
    assert "chevauche « Dentiste »" in reply["reply"]
    assert "demain à 15 heures" in reply["speech"]


def test_bulk_event_deletion_needs_confirmation(client, google):
    ask = chat(client, "Supprime les événements de demain")
    assert "« Dentiste »" in ask["reply"] and ask["pending"]["action"] == "delete_events_range"
    assert google.deleted_ranges == []

    done = chat(client, "Oui", pending=ask["pending"])
    assert "supprimé" in done["reply"] and len(google.deleted_ranges) == 1


def test_google_not_connected(client, google):
    google.configured = False
    reply = chat(client, "Résume mes mails")
    assert "liaison Google n'est pas établie" in reply["reply"] and reply["data"] == {"google_required": True}
    # Aucun brouillon n'est rédigé si l'envoi est impossible.
    assert chat(client, "Envoie un mail à Paul pour lui dire bonjour")["pending"] is None


def test_mail_summary_is_spoken_briefly(client):
    reply = chat(client, "Résume mes mails")
    assert "1. Sophie Martin — Devis projet web" in reply["reply"]
    assert reply["speech"] == (
        "Vous avez 1 message non lu, Monsieur. Le plus récent vient de Sophie Martin, au sujet de : Devis projet web."
    )


def test_remote_clients_cannot_drive_the_computer(client, monkeypatch):
    calls = []
    monkeypatch.setattr(system_actions, "_run", lambda command, timeout=10.0: calls.append(command) or (True, ""))
    monkeypatch.setattr(system_actions, "SYSTEM", "darwin")

    refused = chat(client, "Ouvre Safari", client="discord")
    assert "que depuis le poste lui-même" in refused["reply"] and calls == []
    # Les autres actions restent ouvertes aux clients distants.
    assert chat(client, "Quelle heure est-il ?", client="discord")["action"] == "time"

    chat(client, "Ouvre Safari", client="hud")
    assert calls == [["open", "-a", "Safari"]]


def test_conversation_goes_to_the_model_with_live_context(client, monkeypatch):
    seen = {}

    def fake_stream(history, message, temperature, context="", tools=None):
        seen.update(message=message, context=context, tools=tools)
        yield "Une approche audacieuse, Monsieur."

    monkeypatch.setattr(llm, "chat_stream", fake_stream)
    reply = chat(client, "J'ai le temps de faire une sieste avant mon prochain rendez-vous ?")
    assert reply["source"] == "ollama" and reply["reply"] == "Une approche audacieuse, Monsieur."
    assert seen["context"].startswith("Contexte en direct : nous sommes le ")
    assert "Ville de l'utilisateur : Paris." in seen["context"]
    assert "Agenda restant aujourd'hui" in seen["context"]

    chat(client, "Raconte-moi une blague")
    assert "Agenda" not in seen["context"] and "Météo" not in seen["context"]


def test_model_offline_keeps_modules_available(client, monkeypatch):
    monkeypatch.setattr(llm, "ollama_status", lambda: (False, "introuvable"))
    assert "hors ligne" in chat(client, "Raconte-moi une blague")["reply"]
    assert chat(client, "Quelle heure est-il ?")["action"] == "time"


def test_help_is_not_triggered_by_ordinary_sentences(client, monkeypatch):
    monkeypatch.setattr(llm, "chat_stream", lambda *args, **kwargs: iter(["Volontiers, Monsieur."]))
    assert chat(client, "aide")["action"] == "help"
    assert chat(client, "Que peux-tu faire ?")["reply"].startswith("Je gère votre messagerie")
    assert chat(client, "Aide-moi à comprendre les fractions")["source"] == "ollama"


def test_stream_delivers_sentences_then_final(client, monkeypatch):
    monkeypatch.setattr(llm, "chat_stream", lambda *args, **kwargs: iter(["Bien, Monsieur.", "Je m'en occupe."]))
    response = client.post("/api/chat/stream", json={"message": "Raconte-moi une blague", "client": "hud"})
    events = [json.loads(line) for line in response.text.splitlines() if line]
    assert [event["type"] for event in events] == ["start", "sentence", "sentence", "final"]
    assert events[-1]["reply"] == "Bien, Monsieur. Je m'en occupe." and events[-1]["streamed"] is True

    # Une action reconnue répond d'un seul bloc, sans passer par le modèle.
    direct = client.post("/api/chat/stream", json={"message": "Quelle heure est-il ?", "client": "hud"})
    events = [json.loads(line) for line in direct.text.splitlines() if line]
    assert [event["type"] for event in events] == ["final"] and events[0]["action"] == "time"


def test_briefing_and_dashboard(client):
    briefing = client.get("/api/briefing?kind=full").json()
    assert briefing["reply"].startswith(("Bonjour, Monsieur.", "Bonsoir, Monsieur."))
    assert "18 °C" in briefing["reply"] and "message non lu" in briefing["reply"]

    dashboard = client.get("/api/dashboard").json()
    assert dashboard["google"] is True and dashboard["unread"] == 1
    assert dashboard["weather"]["city"] == "Paris"


def test_alarm_event_reaches_the_hud(client):
    first = client.get("/api/events").json()
    events.publish("alarm", label="Réveil", speech="Monsieur, il est 7 heures 30.")
    update = client.get(f"/api/events?after={first['last_id']}").json()
    assert [event["speech"] for event in update["events"]] == ["Monsieur, il est 7 heures 30."]
    assert events.hud_is_listening()


def test_voice_endpoints_report_missing_engines(client):
    assert client.post("/api/tts", json={"text": "Bonjour"}).status_code == 503
    assert client.post("/api/stt", content=b"RIFF").status_code == 503
    assert client.post("/api/stt", content=b"").status_code == 400


def test_hud_is_served(client):
    page = client.get("/")
    assert page.status_code == 200 and "J.A.R.V.I.S." in page.text
