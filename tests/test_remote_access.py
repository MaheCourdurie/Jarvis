"""Accès depuis un autre appareil : code d'accès, réglages écrits par ./run_jarvis.sh phone."""

import pytest
from fastapi.testclient import TestClient

import main
import phone_setup


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(main.llm, "warm_up", lambda: None)
    monkeypatch.setattr(main.llm, "ollama_status", lambda: (True, "ok"))
    with TestClient(main.app, base_url="http://localhost") as test_client:
        yield test_client


# Une requête relayée par Tailscale porte ces en-têtes : elle vient d'un autre appareil.
RELAYED = {"X-Forwarded-For": "100.90.121.78", "Tailscale-User-Login": "moi@exemple.com"}


def test_this_mac_needs_no_code(client, monkeypatch):
    monkeypatch.setattr(main, "ACCESS_TOKEN", "secret-123")
    assert client.get("/api/status").status_code == 200


def test_other_devices_need_the_code(client, monkeypatch):
    monkeypatch.setattr(main, "ACCESS_TOKEN", "secret-123")
    assert client.get("/api/status", headers=RELAYED).status_code == 401
    assert client.get("/api/status", headers={**RELAYED, "X-Jarvis-Token": "mauvais"}).status_code == 401
    assert client.get("/api/status", headers={**RELAYED, "X-Jarvis-Token": "secret-123"}).status_code == 200
    # Le code protège aussi la conversation, la voix et les actions.
    assert client.post("/api/chat", json={"message": "Quelle heure est-il ?"}, headers=RELAYED).status_code == 401


def test_remote_access_is_off_without_a_code(client, monkeypatch):
    monkeypatch.setattr(main, "ACCESS_TOKEN", "")
    response = client.get("/api/status", headers=RELAYED)
    assert response.status_code == 403 and "run_jarvis.sh phone" in response.json()["detail"]


def test_the_hud_itself_loads_without_a_code(client, monkeypatch):
    # Le HUD ne contient rien de personnel : c'est lui qui demande le code avant d'appeler l'API.
    monkeypatch.setattr(main, "ACCESS_TOKEN", "secret-123")
    page = client.get("/", headers=RELAYED)
    assert page.status_code == 200 and "Code d'accès" in page.text


def test_remote_detection():
    assert main.is_remote_request({"host": "localhost:8001"}) is False
    assert main.is_remote_request({"host": "127.0.0.1:8001"}) is False
    assert main.is_remote_request({"host": "mon-mac.tail1234.ts.net"}) is True
    assert main.is_remote_request({"host": "127.0.0.1:8001", "x-forwarded-for": "100.1.2.3"}) is True


def test_phone_settings_are_written_once(tmp_path):
    env = tmp_path / ".env"
    env.write_text("JARVIS_CITY=Colomiers\nJARVIS_ALLOWED_ORIGINS=http://192.168.1.20:8001\n", encoding="utf-8")

    token = phone_setup.ensure_phone_settings("mon-mac.tail1234.ts.net.", env)
    content = env.read_text(encoding="utf-8")
    assert len(token) >= 12
    assert f"JARVIS_ACCESS_TOKEN={token}" in content
    assert "JARVIS_ALLOWED_ORIGINS=http://192.168.1.20:8001,https://mon-mac.tail1234.ts.net" in content
    assert "JARVIS_CITY=Colomiers" in content

    # Relancer la commande garde le même code et n'ajoute rien en double.
    assert phone_setup.ensure_phone_settings("mon-mac.tail1234.ts.net", env) == token
    again = env.read_text(encoding="utf-8")
    assert again.count("JARVIS_ACCESS_TOKEN=") == 1 and again.count("ts.net") == 1


def test_phone_settings_create_the_env_file(tmp_path):
    env = tmp_path / ".env"
    token = phone_setup.ensure_phone_settings("mon-mac.tail1234.ts.net", env)
    assert env.read_text(encoding="utf-8").endswith(f"JARVIS_ACCESS_TOKEN={token}\nJARVIS_ALLOWED_ORIGINS=https://mon-mac.tail1234.ts.net\n")
