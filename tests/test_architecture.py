"""Jarvis dirige ses contrôleurs, qui répartissent le travail entre leurs agents.

Chaque action comprise relève d'un seul contrôleur et d'un seul agent.
"""

import re
from pathlib import Path

import pytest

import main
from agents.mail import MailAgent
from core.controller import Controller
from core.jarvis import Jarvis

# Ce que Jarvis traite lui-même, sans agent.
JARVIS_OWN = {"smalltalk", "help", "command_error", "web_answer", "misses"}


def test_every_detected_action_has_a_controller_and_an_agent():
    source = "\n".join(path.read_text() for path in (Path(main.__file__).parent / "core" / "intents").glob("*.py"))
    detected = set(re.findall(r'"action":\s*"(\w+)"', source))
    assert detected, "aucune action trouvée dans le routeur"
    assert detected - set(main.jarvis.dispatch) - JARVIS_OWN == set()
    for action, controller in main.jarvis.dispatch.items():
        assert main.jarvis.routes[action] in controller.agents


def test_the_teams():
    teams = {c.name: [a.name for a in c.agents] for c in main.jarvis.controllers}
    assert teams == {
        "organisation": ["messagerie", "agenda", "alarmes", "notes", "trajets"],
        "ordinateur": ["poste", "informations", "musique", "fichiers"],
        "savoir": ["web", "conversation", "mémoire", "traduction", "vision"],
        "création": ["code", "design", "documents", "atelier"],
        "routines": ["routines"],
        "maison": ["maison"],
    }
    assert main.jarvis.conversation_path == "savoir › conversation"


def test_an_action_cannot_belong_to_two_agents_or_two_controllers():
    with pytest.raises(ValueError, match="revendiquée"):
        Controller([MailAgent(main.context), MailAgent(main.context)])

    first, second = Controller([MailAgent(main.context)]), Controller([MailAgent(main.context)])
    with pytest.raises(ValueError, match="revendiquée"):
        Jarvis(main.context, [first, second], main.jarvis.conversation)


def test_rules_are_declared_by_the_agents():
    routes = main.jarvis.routes
    assert routes["send_mail"].needs_google and "send_mail" in routes["send_mail"].confirmable
    assert "delete_alarms_all" in routes["delete_alarms_all"].confirmable
    assert "volume" in routes["volume"].local_only and "web_search" in routes["web_search"].local_only
    assert not routes["time"].local_only


def test_status_shows_controllers_and_their_agents(monkeypatch):
    from fastapi.testclient import TestClient
    from services import llm

    monkeypatch.setattr(llm, "warm_up", lambda: None)
    monkeypatch.setattr(llm, "ollama_status", lambda: (True, "ok"))
    with TestClient(main.app, base_url="http://localhost") as client:
        status = client.get("/api/status").json()
    assert "set_alarm" in status["controllers"]["organisation"]["alarmes"]
    assert status["controllers"]["savoir"]["conversation"] == []
