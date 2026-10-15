"""L'interface s'installe comme une app sur le téléphone : manifeste, icônes, service worker."""

import json
import re

import pytest
from fastapi.testclient import TestClient

import main
from routes import security
from services import llm


# Une requête relayée par Tailscale : elle vient du téléphone.
RELAYED = {"X-Forwarded-For": "100.90.121.78", "Tailscale-User-Login": "moi@exemple.com"}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(llm, "warm_up", lambda: None)
    monkeypatch.setattr(llm, "ollama_status", lambda: (True, "ok"))
    monkeypatch.setattr(security, "ACCESS_TOKEN", "secret-123")
    with TestClient(main.app, base_url="http://localhost") as test_client:
        yield test_client


def test_the_app_can_be_installed_without_the_access_code(client):
    page = client.get("/", headers=RELAYED).text
    assert 'rel="manifest"' in page and 'rel="apple-touch-icon"' in page

    response = client.get("/manifest.webmanifest", headers=RELAYED)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/manifest+json")
    manifest = response.json()
    assert manifest["display"] == "standalone" and manifest["start_url"] == "./"
    # Le manifeste est public, comme toute l'interface : il ne contient aucun code d'accès.
    assert "secret-123" not in json.dumps(manifest) and "code=" not in json.dumps(manifest)
    for icon in manifest["icons"]:
        assert client.get(f"/{icon['src']}", headers=RELAYED).status_code == 200, icon["src"]
    assert client.get("/icons/apple-touch-icon.png", headers=RELAYED).headers["content-type"] == "image/png"


def test_the_service_worker_keeps_the_interface_but_never_the_api(client):
    response = client.get("/sw.js", headers=RELAYED)
    assert response.status_code == 200 and "javascript" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-cache"  # une nouvelle version est prise aussitôt
    script = response.text
    assert "url.pathname.startsWith('/api/')" in script

    # Chaque fichier mis en cache à l'installation doit exister, sinon le service worker ne s'installe pas.
    shell = re.findall(r"'\./([^']*)'", script.split("const FONTS")[0])
    assert "hud.js" in shell and "voice.js" in shell
    for path in shell:
        assert client.get(f"/{path}", headers=RELAYED).status_code == 200, path
