"""Contrôleur « création » : agents code et design, atelier, contrôle qualité et retouches."""

import json

import pytest
from fastapi.testclient import TestClient

import main
from agents import atelier, code, design
from services import events, llm

SCRIPT_OK = '''TITRE: Bonjour le monde
RÉSUMÉ: Affiche une salutation ; lancez-le avec python3 bonjour-le-monde.py.
```python
def main():
    print("Bonjour")


if __name__ == "__main__":
    main()
```'''

SCRIPT_BROKEN = '''TITRE: Bonjour le monde
RÉSUMÉ: Affiche une salutation.
```python
def main(
    print("Bonjour")
```'''

PAGE_OK = '''TITRE: Boulangerie Dorée
RÉSUMÉ: Une page chaleureuse aux tons de blé.
```html
<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Boulangerie</title>
<style>:root{--ble:#E9C46A}body{background:var(--ble)}</style></head>
<body><h1>Pains au levain</h1><footer>Colomiers</footer></body></html>
```'''

LOGO_OK = '''TITRE: Club Tennis
RÉSUMÉ: Une balle stylisée.
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><circle cx="256" cy="256" r="200" fill="#C6E03B"/></svg>
```'''

PALETTE_OK = json.dumps({
    "nom": "Aube sereine", "ambiance": "Douce et apaisante.",
    "couleurs": [
        {"nom": "Brume", "hex": "#F4F1EC", "role": "fond"},
        {"nom": "Encre", "hex": "#1F2933", "role": "texte"},
        {"nom": "Sauge", "hex": "#7A9E7E", "role": "principale"},
        {"nom": "Corail", "hex": "#E07A5F", "role": "accent"},
        {"nom": "Lin", "hex": "#D8CFC4", "role": "neutre"},
    ],
    "conseil": "Réservez le corail aux boutons.",
}, ensure_ascii=False)


@pytest.fixture()
def studio(monkeypatch, tmp_path):
    """Un atelier dans un dossier temporaire, qui travaille sur place et n'ouvre rien."""
    controller = next(c for c in main.jarvis.controllers if c.name == "création")
    workshop = controller.workshop
    monkeypatch.setattr(workshop, "root", tmp_path)
    monkeypatch.setattr(workshop, "last", None)
    monkeypatch.setattr(workshop, "launch", lambda job: job())
    opened, announced, prompts, answers = [], [], [], []
    monkeypatch.setattr(atelier, "open_creation", lambda creation: opened.append(creation) or True)
    monkeypatch.setattr(atelier, "announce", lambda text, speech, label, **payload: announced.append({"text": text, "speech": speech, **payload}))
    monkeypatch.setattr(llm, "keep_warm", lambda: True)
    monkeypatch.setattr(llm, "warm_up", lambda: None)
    monkeypatch.setattr(llm, "ollama_status", lambda: (True, "ok"))

    def fake_complete(system, prompt, temperature, max_tokens, timeout=45, json_mode=False, num_ctx=None, images=None, model=None):
        prompts.append({"system": system, "prompt": prompt, "json": json_mode, "num_ctx": num_ctx})
        return answers.pop(0)

    monkeypatch.setattr(llm, "complete", fake_complete)
    return {"workshop": workshop, "opened": opened, "announced": announced, "prompts": prompts, "answers": answers}


def ask(message, client="hud"):
    with TestClient(main.app, base_url="http://localhost") as http:
        response = http.post("/api/chat", json={"message": message, "client": client})
    assert response.status_code == 200, response.text
    return response.json()


def test_script_is_written_checked_saved_and_opened(studio):
    studio["answers"].append(SCRIPT_OK)
    reply = ask("Crée-moi un script Python qui dit bonjour")
    assert reply["action"] == "write_code" and "Je m'occupe" in reply["reply"]

    creation = studio["opened"][0]
    assert creation.path.name == "bonjour-le-monde.py" and creation.path.parent.name == "code"
    assert 'print("Bonjour")' in creation.path.read_text()
    assert studio["prompts"][0]["num_ctx"] == atelier.CREATION_CTX
    assert "Langage imposé : python" in studio["prompts"][0]["prompt"]
    assert "est prêt" in studio["announced"][0]["speech"]


def test_quality_control_sends_the_error_back_to_the_model(studio):
    studio["answers"].extend([SCRIPT_BROKEN, SCRIPT_OK])
    ask("Écris un programme qui dit bonjour")
    assert len(studio["prompts"]) == 2
    assert "erreur de syntaxe Python" in studio["prompts"][1]["prompt"]
    assert studio["opened"][0].path.read_text().startswith("def main():")


def test_failure_is_announced_not_saved(studio):
    studio["answers"].extend([SCRIPT_BROKEN, SCRIPT_BROKEN])
    ask("Écris un programme qui dit bonjour")
    assert studio["opened"] == [] and "n'a pas abouti" in studio["announced"][0]["speech"]
    assert not list(studio["workshop"].root.rglob("*.py"))


def test_revision_goes_back_to_the_agent_that_made_it(studio):
    studio["answers"].extend([PAGE_OK, PAGE_OK.replace("Pains au levain", "Contactez-nous")])
    ask("Fais-moi un site pour une boulangerie à Colomiers")
    reply = ask("Ajoute un formulaire de contact à la page")
    assert reply["action"] == "revise_creation" and "trois à quatre minutes" in reply["reply"]

    revision_prompt = studio["prompts"][1]["prompt"]
    assert "Pains au levain" in revision_prompt and "formulaire de contact" in revision_prompt
    first, second = (c.path for c in studio["opened"])
    assert first.name == "boulangerie-doree.html" and second.name == "boulangerie-doree-2.html"
    assert "Contactez-nous" in second.read_text() and "Pains au levain" in first.read_text()


def test_nothing_to_revise_yet(studio):
    assert "rien créé" in ask("Corrige-le")["reply"]


def test_logo_comes_with_a_preview(studio):
    studio["answers"].append(LOGO_OK)
    assert "Je m'occupe du dessin du logo" in ask("Dessine-moi un logo pour mon club de tennis")["reply"]
    creation = studio["opened"][0]
    assert creation.path.suffix == ".svg" and creation.extra["preview"].read_text().count("<svg") == 4


def test_palette_is_rendered_with_checked_contrasts(studio):
    studio["answers"].append(PALETTE_OK)
    ask("Propose-moi une palette de couleurs pour une appli de méditation")
    assert studio["prompts"][0]["json"] is True
    page = studio["opened"][0].path.read_text()
    assert "#7A9E7E" in page and "Contrastes" in page and "texte courant" in page
    assert "Sauge" in studio["announced"][0]["speech"]


def test_remote_request_is_saved_but_not_opened(studio):
    studio["answers"].append(SCRIPT_OK)
    reply = ask("Crée-moi un script Python qui dit bonjour", client="discord")
    assert "enregistrerai sur le Mac" in reply["reply"]
    assert studio["opened"] == [] and "enregistré" in studio["announced"][0]["text"]


def test_creations_are_listed(studio):
    studio["answers"].append(SCRIPT_OK)
    ask("Écris un script qui dit bonjour")
    listing = ask("Montre-moi mes créations")
    assert "code/bonjour-le-monde.py" in listing["reply"]


def test_quality_checks():
    assert code.check_code(atelier.parse_draft(SCRIPT_OK)) is None
    assert "TODO" in code.check_code(atelier.Draft("t", "", "python", "def f():\n    # TODO\n    pass\n"))
    assert design.check_page(atelier.parse_draft(PAGE_OK)) is None
    assert "lorem" in design.check_page(atelier.parse_draft(PAGE_OK.replace("Pains au levain", "Lorem ipsum")))
    assert design.check_logo(atelier.parse_draft(LOGO_OK)) is None
    assert "mal formé" in design.check_logo(atelier.Draft("t", "", "svg", "<svg><circle></svg>"))
    cut = atelier.parse_draft("TITRE: x\n```python\nprint(1)")
    assert cut.closed is False


def test_contrast_ratio_matches_wcag():
    assert design.contrast_ratio("#FFFFFF", "#000000") == 21.0
    assert design.contrast_ratio("#777777", "#FFFFFF") == 4.5


def test_creation_event_reaches_the_hud():
    first = events.last_id()
    atelier.events.publish("creation", label="x", text="Prêt", speech="Votre page est prête, Monsieur.")
    assert [e["type"] for e in events.events_after(first)] == ["creation"]


def test_logo_text_must_read_on_light_and_dark():
    def logo(text):
        return atelier.Draft("t", "", "svg", f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><circle r="200"/>{text}</svg>')

    assert "trop petit" in design.check_logo(logo('<text font-size="16" fill="#C6E03B">Club</text>'))
    assert "disparaît" in design.check_logo(logo('<text font-size="64">Club</text>'))
    assert "disparaît" in design.check_logo(logo('<text style="font-size:64px;fill:#111111">Club</text>'))
    assert design.check_logo(logo('<text font-size="64" fill="#2A7AE2">Club</text>')) is None


def test_conversation_warns_when_the_model_is_busy_creating(studio, monkeypatch):
    studio["workshop"].busy["la conception de la page"] = 0.0
    monkeypatch.setattr(llm, "supports_tools", lambda: False)
    monkeypatch.setattr(llm, "chat_stream", lambda *args, **kwargs: iter(["Madrid, Monsieur."]))
    try:
        reply = ask("Quelle est la capitale de l'Espagne ?")
    finally:
        studio["workshop"].busy.clear()
    assert reply["reply"].startswith("Je termine d'abord la conception de la page")
    assert reply["reply"].endswith("Madrid, Monsieur.")


@pytest.mark.skipif(not __import__("shutil").which("sandbox-exec"), reason="bac à sable macOS absent")
def test_trial_run_catches_crashes_but_not_normal_sandbox_limits():
    assert "KeyError" in code.trial_run('print({}["absent"])')
    assert code.trial_run('print("ok")') is None
    assert code.trial_run('input("Nom ? ")') is None  # attend le clavier : normal
    assert code.trial_run('import urllib.request\nurllib.request.urlopen("https://example.com")') is None  # pas de réseau


def test_visual_review_fixes_the_logo(studio, monkeypatch):
    monkeypatch.setattr(design, "DESIGN_SELF_REVIEW", True)
    monkeypatch.setattr(design, "snapshot", lambda path, size=1000: "aW1hZ2U=")
    monkeypatch.setattr(design, "export_png", lambda path: None)
    fixed = LOGO_OK.replace("#C6E03B", "#1F6FEB")
    studio["answers"].extend([LOGO_OK, '{"ok": false, "defauts": ["symbole trop pâle sur fond clair"]}', fixed])
    ask("Dessine-moi un logo pour mon club de tennis")
    review, correction = studio["prompts"][1], studio["prompts"][2]
    assert review["json"] is True and "symbole trop pâle" in correction["prompt"]
    creation = studio["opened"][0]
    assert "#1F6FEB" in creation.path.read_text() and "Relu et corrigé" in creation.summary
