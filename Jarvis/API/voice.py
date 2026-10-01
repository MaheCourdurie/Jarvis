"""Voix de Jarvis : synthèse (TTS) et reconnaissance (STT), entièrement en local.

Synthèse vocale, par ordre de préférence en mode « auto » :
- piper : voix neuronale locale (toutes plateformes)
- say   : voix système de macOS
- browser : repli sur la synthèse du navigateur (gérée côté HUD)

Reconnaissance vocale, par ordre de préférence en mode « auto » :
- mlx     : Whisper sur la puce graphique des Mac Apple Silicon (mlx-whisper), le plus rapide
- whisper : faster-whisper sur le processeur (toutes plateformes)
- browser : repli sur la reconnaissance du navigateur (gérée côté HUD)
"""

from __future__ import annotations

import io
import os

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import wave
from collections import OrderedDict
from pathlib import Path

from config import (
    CITY,
    PIPER_VOICE,
    STT_ENGINE,
    STT_LANGUAGE,
    STT_VOCABULARY,
    TTS_ENGINE,
    TTS_RATE,
    TTS_VOICE,
    VOICES_DIR,
    WAKE_WORD,
    WHISPER_MODEL,
    env_str,
    load_contacts,
)
from persona import strip_accents, to_speech


SYSTEM = platform.system().lower()
MAX_TTS_CHARS = 900
STT_SAMPLE_RATE = 16000
MAX_STT_SECONDS = 30


class VoiceError(Exception):
    pass


# ── Préparation du texte à prononcer ───────────────────────────────────────

def _spoken_clock(match: re.Match) -> str:
    hour = int(match.group(1))
    minute = int(match.group(2)) if match.group(2) else 0
    unit = "heure" if hour in (0, 1) else "heures"
    return f"{hour} {unit}" if minute == 0 else f"{hour} {unit} {minute}"


def prepare_tts_text(text: str) -> str:
    """Adapte un texte à la synthèse vocale (sigles, heures, unités)."""
    spoken = to_speech(text)
    spoken = re.sub(r"J\.\s?A\.\s?R\.\s?V\.\s?I\.\s?S\.?", "Jarvis", spoken, flags=re.IGNORECASE)
    spoken = re.sub(r"\b(\d{1,2})\s?h\s?(\d{2})?\b(?!\w)", _spoken_clock, spoken)
    spoken = re.sub(r"\b(\d{1,2}):(\d{2})\b", _spoken_clock, spoken)
    spoken = re.sub(r"\s?°\s?C\b", " degrés", spoken)
    spoken = re.sub(r"\s?%", " pour cent", spoken)
    spoken = re.sub(r"(\d)\s?Go\b", r"\1 giga-octets", spoken)
    spoken = spoken.replace("«", "").replace("»", "").replace("⚠", "")
    spoken = re.sub(r"\s+", " ", spoken).strip()
    return spoken[:MAX_TTS_CHARS]


# ── Synthèse vocale ────────────────────────────────────────────────────────

class PiperEngine:
    """Voix neuronale locale Piper."""

    name = "piper"

    def __init__(self, voice_name: str) -> None:
        self.voice = voice_name
        self.model_path = VOICES_DIR / f"{voice_name}.onnx"
        self._voice = None
        self._lock = threading.Lock()

    def available(self) -> bool:
        if not self.model_path.exists():
            return False
        try:
            import piper  # noqa: F401
        except ImportError:
            return False
        return True

    def synthesize(self, text: str) -> bytes:
        from piper import PiperVoice, SynthesisConfig

        with self._lock:
            if self._voice is None:
                self._voice = PiperVoice.load(str(self.model_path))

            speaker = env_str("JARVIS_PIPER_SPEAKER")
            config = SynthesisConfig(
                length_scale=1.0 / TTS_RATE,
                speaker_id=int(speaker) if speaker.isdigit() else None,
            )
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as wav_file:
                self._voice.synthesize_wav(text, wav_file, syn_config=config)
            return buffer.getvalue()


class SayEngine:
    """Voix système de macOS (commande say)."""

    name = "say"
    BASE_WORDS_PER_MINUTE = 185

    def __init__(self, voice_name: str = "") -> None:
        self._requested = voice_name
        self._voice: str | None = None

    def available(self) -> bool:
        return SYSTEM == "darwin" and shutil.which("say") is not None

    @property
    def voice(self) -> str:
        if self._voice is None:
            self._voice = self._requested or self._pick_voice()
        return self._voice

    @staticmethod
    def list_voices() -> list[tuple[str, str]]:
        """Retourne les voix installées sous la forme (nom, langue)."""
        try:
            out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
        except Exception:
            return []
        voices = []
        for line in out.splitlines():
            match = re.match(r"^(.+?)\s+([a-z]{2}_[A-Z0-9]{2,})\s+#", line)
            if match:
                voices.append((match.group(1).strip(), match.group(2)))
        return voices

    def _pick_voice(self) -> str:
        """Choisit la meilleure voix masculine française installée."""
        language = STT_LANGUAGE[:2]
        candidates = [name for name, locale in self.list_voices() if locale.startswith(f"{language}_")]
        if not candidates:
            return ""

        def rank(name: str) -> int:
            lowered = name.lower()
            if "premium" in lowered:
                return 0
            if "enhanced" in lowered:
                return 1
            if lowered.startswith("thomas"):
                return 2
            if lowered.startswith("jacques"):
                return 3
            return 4

        return sorted(candidates, key=rank)[0]

    def synthesize(self, text: str) -> bytes:
        handle, path = tempfile.mkstemp(suffix=".wav", prefix="jarvis-tts-")
        os.close(handle)
        try:
            command = ["say", "-r", str(int(self.BASE_WORDS_PER_MINUTE * TTS_RATE))]
            if self.voice:
                command += ["-v", self.voice]
            # Le texte passe par l'entrée standard : il ne peut pas être pris pour une option.
            command += ["-o", path, "--data-format=LEI16@22050", "-f", "-"]
            proc = subprocess.run(command, input=text, capture_output=True, text=True, timeout=60)
            if proc.returncode != 0:
                raise VoiceError((proc.stderr or "say a échoué").strip())
            return Path(path).read_bytes()
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass


_tts_lock = threading.Lock()
_tts_engine = None
_tts_resolved = False
_tts_cache: OrderedDict = OrderedDict()
TTS_CACHE_SIZE = 48


def tts_engine():
    """Retourne le moteur de synthèse actif côté serveur (None = navigateur ou désactivé)."""
    global _tts_engine, _tts_resolved
    with _tts_lock:
        if _tts_resolved:
            return _tts_engine

        piper_engine = PiperEngine(PIPER_VOICE)
        say_engine = SayEngine(TTS_VOICE)
        if TTS_ENGINE == "piper":
            chain = [piper_engine]
        elif TTS_ENGINE == "say":
            chain = [say_engine]
        elif TTS_ENGINE == "auto":
            chain = [piper_engine, say_engine]
        else:  # browser | off
            chain = []

        _tts_engine = next((engine for engine in chain if engine.available()), None)
        _tts_resolved = True
        return _tts_engine


def tts_status() -> dict:
    """État de la synthèse vocale pour /api/status."""
    if TTS_ENGINE == "off":
        return {"engine": "off", "voice": "", "available": False}
    engine = tts_engine()
    if engine is None:
        return {"engine": "browser", "voice": "", "available": False}
    return {"engine": engine.name, "voice": engine.voice, "available": True}


def synthesize(text: str) -> bytes:
    """Convertit un texte en audio WAV avec le moteur local."""
    engine = tts_engine()
    if engine is None:
        raise VoiceError("aucun moteur de synthèse vocale local")

    spoken = prepare_tts_text(text)
    if not spoken:
        raise VoiceError("texte vide")

    key = (engine.name, engine.voice, spoken)
    with _tts_lock:
        if key in _tts_cache:
            _tts_cache.move_to_end(key)
            return _tts_cache[key]

    audio = engine.synthesize(spoken)
    with _tts_lock:
        _tts_cache[key] = audio
        while len(_tts_cache) > TTS_CACHE_SIZE:
            _tts_cache.popitem(last=False)
    return audio


def speak_local(text: str) -> bool:
    """Prononce un texte sur les haut-parleurs du poste, sans passer par le HUD."""
    try:
        audio = synthesize(text)
    except Exception as exc:
        print(f"[VOICE] Synthèse impossible: {exc}", flush=True)
        return False

    players = {"darwin": ["afplay"], "linux": ["paplay", "aplay"]}.get(SYSTEM, [])
    player = next((shutil.which(name) for name in players if shutil.which(name)), None)
    if not player:
        return False

    handle, path = tempfile.mkstemp(suffix=".wav", prefix="jarvis-say-")
    try:
        with os.fdopen(handle, "wb") as wav_file:
            wav_file.write(audio)
        return subprocess.run([player, path], capture_output=True, timeout=120).returncode == 0
    except Exception as exc:
        print(f"[VOICE] Lecture impossible: {exc}", flush=True)
        return False
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ── Mot d'activation ───────────────────────────────────────────────────────

def _wake_pattern(word: str) -> re.Pattern:
    """Construit l'expression qui repère le mot d'activation et ses graphies proches."""
    if strip_accents(word.lower()) == "jarvis":
        # Whisper transcrit parfois « Jarvis » en Jarvi, Jarvie, J'arvie, Djarvis, Gervais, Jervis…
        body = r"(?:d?j'?[ae]r+v[iy](?:s{1,2}e?|ce|es?)?|gervais|jervis|charvis|jarbis|j\.\s?a\.\s?r\.\s?v\.\s?i\.\s?s\.?)"
    else:
        body = re.escape(strip_accents(word.lower()))
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])")


_WAKE = _wake_pattern(WAKE_WORD)
_EDGE_PUNCTUATION = " \t\n,;:.!?…-–—\"'«»"


def extract_command(text: str) -> tuple[bool, str]:
    """Repère le mot d'activation et isole l'ordre qui l'accompagne.

    « Jarvis, quelle heure est-il ? » → (True, "quelle heure est-il ?")
    « Quelle heure est-il, Jarvis ? » → (True, "Quelle heure est-il")
    « Jarvis ? »                      → (True, "")
    """
    original = (text or "").strip()
    # La recherche se fait sans accents ; les positions restent valides car la
    # normalisation caractère par caractère conserve la longueur de la chaîne.
    folded = "".join(strip_accents(ch) or ch for ch in original.lower())
    if len(folded) != len(original):
        folded = original.lower()

    match = _WAKE.search(folded)
    if not match:
        return False, original

    after = original[match.end():].strip(_EDGE_PUNCTUATION)
    before = original[: match.start()].strip(_EDGE_PUNCTUATION)
    # Un mot de liaison seul avant le prénom (« dis Jarvis », « hey Jarvis ») n'est pas un ordre.
    if strip_accents(before.lower()) in {"dis", "dis-moi", "hey", "he", "eh", "ok", "okay", "bonjour", "salut", "bonsoir"}:
        lead = before
        before = ""
    else:
        lead = ""

    if after:
        command = after
        if lead.lower() in {"bonjour", "salut", "bonsoir"}:
            command = f"{lead}. {after}"
    elif before:
        command = before
    else:
        command = lead if lead.lower() in {"bonjour", "salut", "bonsoir"} else ""

    if command and re.search(r"[?!]\s*$", original) and not re.search(r"[?!.]$", command):
        command += original.rstrip()[-1]
    return True, command


# ── Reconnaissance vocale ──────────────────────────────────────────────────

# Phrases que Whisper « entend » dans le silence ou le bruit de fond.
_HALLUCINATIONS = [
    "sous-titres realises par",
    "sous-titrage",
    "sous-titres par",
    "soustitreur",
    "amara.org",
    "merci d'avoir regarde",
    "merci a tous d'avoir regarde",
    "abonnez-vous",
    "a bientot pour une nouvelle video",
    "thanks for watching",
]


MAX_VOCABULARY_WORDS = 40


def stt_vocabulary() -> list[str]:
    """Noms propres fournis à Whisper : prénom d'activation, ville, vocabulaire personnel, contacts.

    Sans eux, un petit modèle écrit « Colombier » pour « Colomiers » ou « Jarvie » pour « Jarvis ».
    """
    words = [WAKE_WORD.capitalize(), CITY, *STT_VOCABULARY, *load_contacts().keys()]
    unique: list[str] = []
    for word in words:
        word = word.strip()
        if word and word.lower() not in {known.lower() for known in unique}:
            unique.append(word)
    return unique[:MAX_VOCABULARY_WORDS]


def _looks_like_hallucination(text: str) -> bool:
    folded = strip_accents(text.lower())
    return any(marker in folded for marker in _HALLUCINATIONS)


def _keep_segment(segment: dict) -> bool:
    """Écarte les passages que Whisper juge silencieux ou trop incertains."""
    return segment.get("no_speech_prob", 0.0) <= 0.6 and segment.get("avg_logprob", 0.0) >= -1.2


def _join_segments(texts: list[str]) -> str:
    text = re.sub(r"\s+", " ", " ".join(texts)).strip()
    return "" if _looks_like_hallucination(text) else text


class WhisperEngine:
    """Reconnaissance vocale locale avec faster-whisper, sur le processeur."""

    name = "whisper"
    default_model = "small"

    def __init__(self, model_name: str = "") -> None:
        self.model_name = model_name or self.default_model
        self._model = None
        self._lock = threading.Lock()

    def available(self) -> bool:
        try:
            import faster_whisper  # noqa: F401
            import numpy  # noqa: F401
        except ImportError:
            return False
        return True

    def load(self) -> None:
        """Charge le modèle (téléchargé au premier lancement)."""
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(self.model_name, device="auto", compute_type="int8")

    @staticmethod
    def _decode_wav(data: bytes):
        """Décode un WAV PCM 16 bits en signal mono 16 kHz normalisé."""
        import numpy as np

        try:
            with wave.open(io.BytesIO(data), "rb") as wav_file:
                rate = wav_file.getframerate()
                channels = wav_file.getnchannels()
                width = wav_file.getsampwidth()
                frames = wav_file.readframes(wav_file.getnframes())
        except (wave.Error, EOFError) as exc:
            raise VoiceError(f"audio illisible: {exc}") from exc

        if width != 2:
            raise VoiceError("format audio non pris en charge (PCM 16 bits attendu)")

        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1)
        if rate != STT_SAMPLE_RATE and len(samples):
            target = int(round(len(samples) * STT_SAMPLE_RATE / rate))
            positions = np.linspace(0, len(samples) - 1, target)
            samples = np.interp(positions, np.arange(len(samples)), samples).astype(np.float32)
        return samples[: STT_SAMPLE_RATE * MAX_STT_SECONDS]

    def transcribe(self, data: bytes) -> dict:
        samples = self._decode_wav(data)
        duration = len(samples) / STT_SAMPLE_RATE
        if duration < 0.25:
            return {"text": "", "duration": duration}

        self.load()
        with self._lock:
            segments, _info = self._model.transcribe(
                samples,
                language=STT_LANGUAGE or None,
                beam_size=5,
                vad_filter=True,
                condition_on_previous_text=False,
                # Une simple liste de noms : elle oriente l'orthographe sans imposer leur présence.
                initial_prompt=", ".join(stt_vocabulary()) + ".",
                no_speech_threshold=0.6,
            )
            kept = [
                segment.text.strip()
                for segment in segments
                if _keep_segment({"no_speech_prob": segment.no_speech_prob, "avg_logprob": segment.avg_logprob})
            ]
        return {"text": _join_segments(kept), "duration": duration}


class MlxWhisperEngine:
    """Reconnaissance vocale sur la puce graphique des Mac Apple Silicon (mlx-whisper).

    Environ trois fois plus rapide que faster-whisper avec un modèle bien plus grand :
    « large-v3-turbo » comprend une phrase en un tiers de seconde sur un Mac M5.
    """

    name = "mlx-whisper"
    default_model = "large-v3-turbo"

    def __init__(self, model_name: str = "") -> None:
        self.model_name = model_name or self.default_model
        if "/" in self.model_name:
            self.repo = self.model_name
        elif self.model_name in {"turbo", "large-v3-turbo"}:
            self.repo = "mlx-community/whisper-large-v3-turbo"
        else:
            self.repo = f"mlx-community/whisper-{self.model_name}-mlx"
        self._ready = False
        self._lock = threading.Lock()

    def available(self) -> bool:
        if SYSTEM != "darwin" or platform.machine() != "arm64":
            return False
        try:
            import mlx_whisper  # noqa: F401
        except ImportError:
            return False
        return True

    def _run(self, samples, **options) -> dict:
        import mlx_whisper

        return mlx_whisper.transcribe(
            samples,
            path_or_hf_repo=self.repo,
            language=STT_LANGUAGE or None,
            # Une seule température : pas de nouvelles tentatives qui rallongeraient l'attente.
            temperature=0.0,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            verbose=None,
            **options,
        )

    def load(self) -> None:
        """Télécharge (au premier lancement) et charge le modèle sur la puce graphique."""
        import numpy as np

        with self._lock:
            if not self._ready:
                self._run(np.zeros(STT_SAMPLE_RATE, dtype=np.float32))
                self._ready = True

    def transcribe(self, data: bytes) -> dict:
        samples = WhisperEngine._decode_wav(data)
        duration = len(samples) / STT_SAMPLE_RATE
        if duration < 0.25:
            return {"text": "", "duration": duration}

        self.load()
        with self._lock:
            result = self._run(samples, initial_prompt=", ".join(stt_vocabulary()) + ".")
        kept = [segment.get("text", "").strip() for segment in result.get("segments", []) if _keep_segment(segment)]
        return {"text": _join_segments(kept), "duration": duration}


_stt_lock = threading.Lock()
_stt_engine = None
_stt_resolved = False


def stt_engine():
    """Retourne le moteur de reconnaissance local (None = navigateur ou désactivé)."""
    global _stt_engine, _stt_resolved
    with _stt_lock:
        if _stt_resolved:
            return _stt_engine
        if STT_ENGINE == "auto":
            chain = [MlxWhisperEngine(WHISPER_MODEL), WhisperEngine(WHISPER_MODEL)]
        elif STT_ENGINE == "mlx":
            chain = [MlxWhisperEngine(WHISPER_MODEL)]
        elif STT_ENGINE == "whisper":
            chain = [WhisperEngine(WHISPER_MODEL)]
        else:  # browser | off
            chain = []
        _stt_engine = next((engine for engine in chain if engine.available()), None)
        _stt_resolved = True
        return _stt_engine


def stt_status() -> dict:
    """État de la reconnaissance vocale pour /api/status."""
    if STT_ENGINE == "off":
        return {"engine": "off", "model": "", "available": False, "language": STT_LANGUAGE}
    engine = stt_engine()
    if engine is None:
        return {"engine": "browser", "model": "", "available": False, "language": STT_LANGUAGE}
    return {"engine": engine.name, "model": engine.model_name, "available": True, "language": STT_LANGUAGE}


def transcribe(data: bytes) -> dict:
    """Transcrit un enregistrement WAV et repère le mot d'activation."""
    engine = stt_engine()
    if engine is None:
        raise VoiceError("aucun moteur de reconnaissance vocale local")

    result = engine.transcribe(data)
    wake, command = extract_command(result["text"])
    result.update({"wake": wake, "command": command})
    return result


def prepare_stt() -> None:
    """Télécharge et charge le modèle de reconnaissance choisi (utilisé par ./run_jarvis.sh setup)."""
    engine = stt_engine()
    if engine is None:
        print("[voice] Aucun moteur de reconnaissance local : le HUD utilisera celui du navigateur.")
        return
    engine.load()
    print(f"[voice] Reconnaissance vocale prête : {engine.name} {engine.model_name}")


def preload() -> None:
    """Charge les modèles vocaux en tâche de fond pour que la première réponse soit immédiate."""

    def _load() -> None:
        try:
            engine = stt_engine()
            if engine is not None:
                engine.load()
                print(f"[VOICE] Reconnaissance vocale prête ({engine.name} {engine.model_name})", flush=True)
        except Exception as exc:
            print(f"[VOICE] Chargement de la reconnaissance vocale impossible: {exc}", flush=True)
        try:
            if tts_engine() is not None:
                synthesize("Prêt.")
                print(f"[VOICE] Synthèse vocale prête ({tts_status()['engine']} · {tts_status()['voice']})", flush=True)
        except Exception as exc:
            print(f"[VOICE] Initialisation de la synthèse impossible: {exc}", flush=True)

    threading.Thread(target=_load, daemon=True, name="jarvis-voice-preload").start()
