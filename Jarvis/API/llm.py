"""Client Ollama : état du modèle, conversation et garde-fous de la persona."""

from __future__ import annotations

import json
import re
import threading
from typing import Any, Iterator

import requests

from config import (
    LLM_HISTORY_MESSAGES,
    LLM_MAX_TOKENS,
    OLLAMA_KEEP_ALIVE,
    OLLAMA_MODEL,
    OLLAMA_URL,
    SYSTEM_PROMPT_FILE,
)
from persona import TITLE


DEFAULT_PROMPT = "Tu es J.A.R.V.I.S., l'assistant personnel de {titre}. Tu le vouvoies et tu réponds brièvement."
MAX_HISTORY_CHARS = 1500

# Verbes qui signalent une demande d'action (que seul un module peut exécuter).
_ACTION_REQUEST = re.compile(
    r"\b(?:envoie|envoyer|envoi|[ée]cris|r[ée]dige|r[ée]ponds|supprime|efface|annule|cr[ée]e|ajoute|"
    r"programme|planifie|r[ée]serve|appelle|commande|ach[èe]te|ouvre|lance|ferme|mets|r[èe]gle|active|"
    r"d[ée]sactive|[ée]teins|allume|transf[èe]re|archive|paie|paye)\b",
    flags=re.IGNORECASE,
)
# Le modèle prétend avoir agi alors qu'aucun module n'a rien exécuté.
_FALSE_CLAIM = re.compile(
    r"\b(?:j'ai|je viens d['e])\s*(?:bien |d[ée]j[àa] |donc )?(?:envoy|cr[ée][ée]|ajout|programm|planifi|supprim|"
    r"effac|annul|ouvert|lanc|ferm|r[ée]gl|mis\b|appel|r[ée]serv|command|achet|activ|d[ée]sactiv|[ée]teint|"
    r"allum|transf|archiv|pay)",
    flags=re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"([.!?…]+[\"»)]*)(\s+)(?=(\S))")


def load_system_prompt() -> str:
    """Charge le prompt système partagé et y inscrit la formule d'appel."""
    text = ""
    if SYSTEM_PROMPT_FILE.exists():
        text = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()
    return (text or DEFAULT_PROMPT).replace("{titre}", TITLE)


SYSTEM_PROMPT = load_system_prompt()


def unexecuted_action_reply() -> str:
    """Réponse de sûreté quand le modèle prétend avoir exécuté une action."""
    return f"Je crains de ne pas avoir pu exécuter cette demande, {TITLE}. Pourriez-vous la reformuler ?"


def ollama_status() -> tuple[bool, str]:
    """Vérifie si Ollama répond et si le modèle configuré est disponible."""
    try:
        res = requests.get(f"{OLLAMA_URL}/api/tags", timeout=4)
        res.raise_for_status()
        names = [item.get("name", "") for item in res.json().get("models", [])]
    except Exception as exc:
        return False, f"Ollama injoignable: {exc}"

    wanted = OLLAMA_MODEL if ":" in OLLAMA_MODEL else f"{OLLAMA_MODEL}:latest"
    if wanted in names or OLLAMA_MODEL in names:
        return True, "ok"
    return False, f'modèle "{OLLAMA_MODEL}" introuvable dans Ollama'


def _message_field(item: Any, key: str) -> str:
    value = getattr(item, key, None)
    if value is None and isinstance(item, dict):
        value = item.get(key)
    return str(value or "")


def build_messages(history: list[Any], message: str, context: str = "") -> list[dict]:
    """Assemble le prompt système, le contexte en direct et l'historique récent."""
    system = SYSTEM_PROMPT
    if context:
        system += "\n\n" + context

    # Le client envoie souvent l'historique avec le message courant en dernière position.
    past = list(history)
    if past and _message_field(past[-1], "role") == "user" and _message_field(past[-1], "content").strip() == message.strip():
        past.pop()

    messages = [{"role": "system", "content": system}]
    recent = past[-LLM_HISTORY_MESSAGES:] if LLM_HISTORY_MESSAGES else []
    for item in recent:
        role = _message_field(item, "role")
        content = _message_field(item, "content").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:MAX_HISTORY_CHARS]})

    messages.append({"role": "user", "content": message})
    return messages


def _payload(messages: list[dict], temperature: float, stream: bool) -> dict:
    return {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "options": {"temperature": temperature, "num_predict": LLM_MAX_TOKENS},
        "keep_alive": OLLAMA_KEEP_ALIVE,
        # Les modèles « à réflexion » répondraient trop lentement pour un échange vocal.
        "think": False,
        "stream": stream,
    }


def clean_reply(text: str) -> str:
    """Retire les artefacts de mise en forme que la voix ne sait pas lire."""
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^(?:J\.A\.R\.V\.I\.S\.?|Jarvis)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\*\*?|__|`+|^#+\s*", "", cleaned, flags=re.MULTILINE)
    return cleaned.strip()


def claims_unexecuted_action(user_message: str, reply: str) -> bool:
    """Détecte une réponse qui affirme avoir exécuté une action demandée."""
    return bool(_ACTION_REQUEST.search(user_message or "") and _FALSE_CLAIM.search(reply or ""))


def chat(history: list[Any], message: str, temperature: float, context: str = "") -> str:
    """Interroge le modèle et renvoie la réponse complète."""
    res = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json=_payload(build_messages(history, message, context), temperature, stream=False),
        timeout=120,
    )
    res.raise_for_status()
    reply = clean_reply(res.json().get("message", {}).get("content") or "")
    if not reply:
        return f"Je n'ai pas de réponse pour le moment, {TITLE}."
    if claims_unexecuted_action(message, reply):
        return unexecuted_action_reply()
    return reply


def complete(system: str, prompt: str, temperature: float, max_tokens: int, timeout: float = 45) -> str:
    """Génération ponctuelle hors conversation (rédaction d'un objet ou d'un corps de mail)."""
    payload = _payload(
        [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        temperature,
        stream=False,
    )
    payload["options"]["num_predict"] = max_tokens
    res = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
    res.raise_for_status()
    return (res.json().get("message", {}).get("content") or "").strip()


def split_sentences(buffer: str) -> tuple[list[str], str]:
    """Découpe un texte en phrases complètes ; renvoie (phrases, reste en cours d'écriture)."""
    sentences = []
    start = 0
    for match in _SENTENCE_END.finditer(buffer):
        previous_word = re.search(r"(\S+)$", buffer[start:match.start(1)])
        # « M. », « J. » ou « 3. » ne terminent pas une phrase.
        if previous_word is None or len(previous_word.group(1)) <= 1:
            continue
        # Une minuscule après le point signale une abréviation (« J.A.R.V.I.S. est… »).
        if "\n" not in match.group(2) and match.group(3).islower():
            continue
        sentence = buffer[start:match.end(1)].strip()
        if sentence:
            sentences.append(sentence)
        start = match.end()
    return sentences, buffer[start:]


def chat_stream(history: list[Any], message: str, temperature: float, context: str = "") -> Iterator[str]:
    """Interroge le modèle et produit la réponse phrase par phrase, dès qu'elle est prête."""
    guard = bool(_ACTION_REQUEST.search(message or ""))
    buffer = ""
    produced = False

    with requests.post(
        f"{OLLAMA_URL}/api/chat",
        json=_payload(build_messages(history, message, context), temperature, stream=True),
        stream=True,
        timeout=(10, 120),
    ) as res:
        res.raise_for_status()
        for line in res.iter_lines():
            if not line:
                continue
            chunk = json.loads(line)
            if chunk.get("error"):
                raise RuntimeError(str(chunk["error"]))

            buffer += chunk.get("message", {}).get("content") or ""
            done = bool(chunk.get("done"))
            sentences, buffer = split_sentences(buffer)
            if done and buffer.strip():
                sentences.append(buffer.strip())
                buffer = ""

            for sentence in sentences:
                sentence = clean_reply(sentence)
                if not sentence:
                    continue
                if guard and _FALSE_CLAIM.search(sentence):
                    yield unexecuted_action_reply()
                    return
                produced = True
                yield sentence

            if done:
                break

    if not produced:
        yield f"Je n'ai pas de réponse pour le moment, {TITLE}."


def warm_up() -> None:
    """Charge le modèle en mémoire en tâche de fond pour que la première réponse soit rapide."""

    def _load() -> None:
        online, _reason = ollama_status()
        if not online:
            return
        try:
            payload = _payload([{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "Bonjour"}], 0.1, False)
            payload["options"]["num_predict"] = 1
            requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=180)
            print(f"[LLM] Modèle {OLLAMA_MODEL} chargé", flush=True)
        except Exception as exc:
            print(f"[LLM] Préchargement impossible: {exc}", flush=True)

    threading.Thread(target=_load, daemon=True, name="jarvis-llm-warmup").start()
