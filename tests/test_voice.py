import io
import json
import wave

import pytest

import llm
import voice


@pytest.mark.parametrize(
    "heard, wake, command",
    [
        ("Jarvis, quelle heure est-il ?", True, "quelle heure est-il?"),
        ("Quelle heure est-il, Jarvis ?", True, "Quelle heure est-il?"),
        ("Jarvis ?", True, ""),
        ("Hey Jarvis", True, ""),
        ("Dis Jarvis, ouvre Safari.", True, "ouvre Safari"),
        ("Bonjour Jarvis", True, "Bonjour"),
        ("Merci Jarvis.", True, "Merci"),
        # Graphies approchantes produites par la reconnaissance vocale.
        ("Djarvis, mets une alarme à 7h30", True, "mets une alarme à 7h30"),
        ("Gervais, tu es là ?", True, "tu es là?"),
        ("J.A.R.V.I.S. lance le diagnostic", True, "lance le diagnostic"),
        ("Jarvie, quelle heure est-il ?", True, "quelle heure est-il?"),
        ("J'arvie, mets une alarme", True, "mets une alarme"),
        # Sans le prénom, la phrase n'est pas adressée à Jarvis.
        ("Il fait beau aujourd'hui.", False, "Il fait beau aujourd'hui."),
        ("Le service est fermé", False, "Le service est fermé"),
        ("Je varie les plaisirs", False, "Je varie les plaisirs"),
    ],
)
def test_wake_word(heard, wake, command):
    assert voice.extract_command(heard) == (wake, command)


def test_text_is_prepared_for_speech():
    assert voice.prepare_tts_text("Il est 7 h 30, Monsieur.") == "Il est 7 heures 30, Monsieur."
    assert voice.prepare_tts_text("Lundi 09:00 à 21:00, jeudi 08:30 à 21h.") == "Lundi 9 heures à 21 heures, jeudi 8 heures 30 à 21 heures."
    assert voice.prepare_tts_text("J.A.R.V.I.S. à 12 h, 18 °C") == "Jarvis à 12 heures, 18 degrés."
    assert voice.prepare_tts_text("Mémoire : 58 %") == "Mémoire : 58 pour cent."
    assert voice.prepare_tts_text("- **Point** [id: abc]\nVoir https://x.y/z") == "Point. Voir."
    assert len(voice.prepare_tts_text("mot " * 1000)) <= voice.MAX_TTS_CHARS


def test_recognition_vocabulary_lists_proper_nouns(monkeypatch):
    monkeypatch.setattr(voice, "CITY", "Colomiers")
    monkeypatch.setattr(voice, "STT_VOCABULARY", ["Blagnac", "colomiers", "Toulouse"])
    # Prénom d'activation, ville, vocabulaire personnel, puis contacts du carnet ; sans doublon.
    assert voice.stt_vocabulary() == ["Jarvis", "Colomiers", "Blagnac", "Toulouse", "Paul", "Sophie Martin"]


def test_whisper_hallucinations_are_dropped():
    assert voice._looks_like_hallucination("Sous-titres réalisés par la communauté d'Amara.org")
    assert voice._looks_like_hallucination("Merci d'avoir regardé cette vidéo !")
    assert not voice._looks_like_hallucination("Jarvis, quelle heure est-il ?")


def test_wav_decoding_resamples_to_16k():
    np = pytest.importorskip("numpy")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(48000)
        wav_file.writeframes((np.ones(48000 * 2, dtype=np.int16) * 1000).tobytes())

    samples = voice.WhisperEngine._decode_wav(buffer.getvalue())
    assert len(samples) == 16000
    assert abs(float(samples.mean()) - 1000 / 32768) < 1e-4

    with pytest.raises(voice.VoiceError):
        voice.WhisperEngine._decode_wav(b"pas un fichier audio")


def test_engines_can_be_disabled():
    # conftest règle les moteurs sur "off" : rien n'est chargé, l'API le signale.
    assert voice.tts_status() == {"engine": "off", "voice": "", "available": False}
    assert voice.stt_status()["available"] is False
    with pytest.raises(voice.VoiceError):
        voice.synthesize("Bonjour")


# ── Client du modèle de langage ────────────────────────────────────────────

def test_sentences_are_split_for_streaming():
    sentences, rest = llm.split_sentences("Bonjour, Monsieur. Il est midi. Que puis-je")
    assert sentences == ["Bonjour, Monsieur.", "Il est midi."]
    assert rest == "Que puis-je"

    # La dernière phrase attend la suite : le point peut appartenir à une abréviation.
    assert llm.split_sentences("Il est midi.") == ([], "Il est midi.")
    assert llm.split_sentences("Je suis J.A.R.V.I.S. et je veille. Bien") == (["Je suis J.A.R.V.I.S. et je veille."], "Bien")
    assert llm.split_sentences("M. Martin arrive. Il") == (["M. Martin arrive."], "Il")


def test_model_cannot_claim_an_action_it_did_not_run():
    assert llm.claims_unexecuted_action("Envoie un mail à Paul", "Monsieur, j'ai envoyé un mail à Paul.")
    assert llm.claims_unexecuted_action("Réserve une table", "Je viens de réserver une table.")
    assert not llm.claims_unexecuted_action("Envoie un mail à Paul", "Il me faut l'adresse de Paul, Monsieur.")
    # Sans demande d'action, le modèle peut parler au passé.
    assert not llm.claims_unexecuted_action("Qu'as-tu fait hier ?", "J'ai ajouté un trait d'esprit.")


def test_history_is_trimmed_and_current_message_not_duplicated():
    history = [{"role": "user", "content": f"message {i}"} for i in range(40)]
    history.append({"role": "user", "content": "Bonjour"})
    messages = llm.build_messages(history, "Bonjour", context="Contexte en direct : test.")

    assert messages[0]["role"] == "system" and "Monsieur" in messages[0]["content"]
    assert "{titre}" not in messages[0]["content"]
    assert messages[0]["content"].endswith("Contexte en direct : test.")
    assert [m["content"] for m in messages].count("Bonjour") == 1
    assert len(messages) == 1 + llm.LLM_HISTORY_MESSAGES + 1


def test_reply_is_cleaned():
    assert llm.clean_reply("J.A.R.V.I.S. : **Bien**, Monsieur.") == "Bien, Monsieur."


# ── Réactivité ─────────────────────────────────────────────────────────────

class _FakeStream:
    """Réponse d'Ollama en flux : une ligne JSON par morceau de texte."""

    def __init__(self, chunks):
        self.lines = [json.dumps(chunk).encode() for chunk in chunks]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self):
        return iter(self.lines)


def _streamed(monkeypatch, pieces, final=None):
    chunks = [{"message": {"content": piece}, "done": False} for piece in pieces]
    chunks.append(final or {"message": {"content": ""}, "done": True})
    monkeypatch.setattr(llm.requests, "post", lambda *args, **kwargs: _FakeStream(chunks))
    return list(llm.chat_stream([], "Explique-moi un trou noir", 0.6))


def test_long_first_sentence_starts_at_the_first_comma(monkeypatch):
    pieces = ["Un trou noir est une région de l'espace ", "où la gravité est si intense, ", "que rien ne s'en échappe. ", "Voilà, Monsieur."]
    assert _streamed(monkeypatch, pieces) == [
        "Un trou noir est une région de l'espace où la gravité est si intense,",
        "que rien ne s'en échappe.",
        "Voilà, Monsieur.",
    ]
    # Une courte proposition attend la fin de la phrase : « Bien, » seul sonnerait mal.
    assert llm.first_clause("Bien, Monsieur, je m'en occupe") == (None, "Bien, Monsieur, je m'en occupe")
    assert llm.first_clause("Le prix est de 3,5 euros") == (None, "Le prix est de 3,5 euros")


def test_stream_ends_with_the_tool_call(monkeypatch):
    call = {"message": {"content": "", "tool_calls": [{"function": {"name": "recherche_web", "arguments": {"requete": "horaires Leclerc Blagnac"}}}]}, "done": False}
    produced = _streamed(monkeypatch, [], final=call)
    assert produced == [llm.ToolCall("recherche_web", {"requete": "horaires Leclerc Blagnac"})]


@pytest.mark.parametrize(
    "pieces",
    [
        ['recherche_web{requete: "concerts Toulouse ', 'ce week-end"}'],
        ['```tool_code\nprint(recherche_web(requete="concerts Toulouse ce week-end"))\n```'],
        ['{"name": "recherche_web", "arguments": {"requete": "concerts Toulouse ce week-end"}}'],
        ['recherche_web{requete:<|"|>concerts Toulouse ce week-end<|"|>}'],
    ],
)
def test_tool_call_written_as_text_is_not_read_aloud(monkeypatch, pieces):
    # Vu en vrai : le modèle écrit l'appel au lieu de le déclarer, et Jarvis le prononçait.
    chunks = [{"message": {"content": piece}, "done": False} for piece in pieces] + [{"message": {"content": ""}, "done": True}]
    monkeypatch.setattr(llm.requests, "post", lambda *args, **kwargs: _FakeStream(chunks))
    produced = list(llm.chat_stream([], "Quels concerts à Toulouse ce week-end ?", 0.6, tools=[llm.WEB_TOOL]))
    assert produced == [llm.ToolCall("recherche_web", {"requete": "concerts Toulouse ce week-end"})]


class _FakeReply:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": self.content}}


def test_search_query_uses_a_short_prompt(monkeypatch):
    sent = []

    def post(url, json, timeout):
        sent.append(json)
        return _FakeReply("Requête : « horaires Leclerc Blagnac lundi »\n")

    monkeypatch.setattr(llm.requests, "post", post)
    history = [
        {"role": "user", "content": "Le Leclerc de Blagnac est ouvert dimanche ?"},
        {"role": "assistant", "content": "Oui, de 9 heures à 12 h 30, Monsieur."},
        {"role": "user", "content": "Et lundi ?"},
    ]
    assert llm.search_query(history, "Et lundi ?") == "horaires Leclerc Blagnac lundi"

    payload = sent[0]
    system, user = payload["messages"]
    # Ni la persona complète ni l'outil : le prompt tient en quelques lignes.
    assert "tools" not in payload and len(system["content"]) < 700 and llm.CITY in system["content"]
    assert user["content"].startswith("Échanges précédents :\nUtilisateur : Le Leclerc de Blagnac est ouvert dimanche ?")
    assert user["content"].endswith("Demande : Et lundi ?") and user["content"].count("Et lundi ?") == 1
    assert payload["options"]["num_predict"] <= 32


def test_search_query_gives_up_quietly(monkeypatch):
    monkeypatch.setattr(llm.requests, "post", lambda *args, **kwargs: _FakeReply(""))
    assert llm.search_query([], "Quels sont les horaires de la piscine ?") is None


def test_gpu_recognition_is_preferred_when_available(monkeypatch):
    monkeypatch.setattr(voice, "STT_ENGINE", "auto")
    monkeypatch.setattr(voice, "_stt_resolved", False)
    monkeypatch.setattr(voice, "_stt_engine", None)
    monkeypatch.setattr(voice.MlxWhisperEngine, "available", lambda self: True)
    engine = voice.stt_engine()
    assert (engine.name, engine.model_name, engine.repo) == ("mlx-whisper", "large-v3-turbo", "mlx-community/whisper-large-v3-turbo")
    assert voice.MlxWhisperEngine("small").repo == "mlx-community/whisper-small-mlx"
    # Sans puce Apple (ou sans mlx-whisper), faster-whisper prend le relais.
    monkeypatch.setattr(voice, "_stt_resolved", False)
    monkeypatch.setattr(voice.MlxWhisperEngine, "available", lambda self: False)
    monkeypatch.setattr(voice.WhisperEngine, "available", lambda self: True)
    assert (voice.stt_engine().name, voice.stt_engine().model_name) == ("whisper", "small")
    monkeypatch.setattr(voice, "_stt_resolved", False)
    monkeypatch.setattr(voice, "_stt_engine", None)
