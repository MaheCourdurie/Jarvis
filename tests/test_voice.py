import io
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
        # Sans le prénom, la phrase n'est pas adressée à Jarvis.
        ("Il fait beau aujourd'hui.", False, "Il fait beau aujourd'hui."),
        ("Le service est fermé", False, "Le service est fermé"),
    ],
)
def test_wake_word(heard, wake, command):
    assert voice.extract_command(heard) == (wake, command)


def test_text_is_prepared_for_speech():
    assert voice.prepare_tts_text("Il est 7 h 30, Monsieur.") == "Il est 7 heures 30, Monsieur."
    assert voice.prepare_tts_text("J.A.R.V.I.S. à 12 h, 18 °C") == "Jarvis à 12 heures, 18 degrés."
    assert voice.prepare_tts_text("Mémoire : 58 %") == "Mémoire : 58 pour cent."
    assert voice.prepare_tts_text("- **Point** [id: abc]\nVoir https://x.y/z") == "Point. Voir."
    assert len(voice.prepare_tts_text("mot " * 1000)) <= voice.MAX_TTS_CHARS


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
