// Voix de Jarvis côté navigateur : lecture de la synthèse, écoute du micro,
// découpage des prises de parole et envoi à la reconnaissance vocale locale.

const STT_RATE = 16000;
const PRE_ROLL_MS = 450;      // ce qui précède le début de la parole est conservé
const START_MS = 60;          // durée de voix nécessaire pour ouvrir une prise de parole
const SILENCE_MS = 600;       // silence qui clôt une prise de parole
const MIN_SPEECH_MS = 320;
const MAX_SPEECH_MS = 15000;
const MIN_THRESHOLD = 0.012;

// Graphies proches de « Jarvis » (utilisé seulement avec la reconnaissance du navigateur).
const WAKE = /(?:^|[^a-z0-9])(d?j'?[ae]r+v[iy](?:s{1,2}e?|ce|es?)?|gervais|jervis|charvis|jarbis)(?![a-z0-9])/i;

function extractCommand(text) {
  const match = WAKE.exec(text);
  if (!match) return { wake: false, command: text };
  const index = match.index + match[0].indexOf(match[1]);
  const trim = (value) => value.replace(/^[\s,;:.!?-]+|[\s,;:.-]+$/g, '');
  const after = trim(text.slice(index + match[1].length));
  const before = trim(text.slice(0, index));
  return { wake: true, command: after || (/^(dis|hey|hé|eh|ok|okay)$/i.test(before) ? '' : before) };
}

export class VoiceEngine {
  // headers(extra) ajoute le code d'accès aux requêtes quand Jarvis est utilisé à distance.
  constructor(apiUrl, headers = (extra) => extra) {
    this.apiUrl = apiUrl;
    this.headers = headers;
    this.ctx = null;

    // Synthèse
    this.serverTts = false;
    this.ttsEnabled = true;
    this.queue = [];
    this.draining = false;
    this.generation = 0;
    this.currentSource = null;
    this.browserSpeaking = false;
    this.onSpeakingChange = () => {};

    // Écoute
    this.serverStt = false;
    this.language = 'fr';
    this.micStream = null;
    this.recognition = null;
    this.gated = true;
    this.onTranscript = () => {};
    this.onSpeechStart = () => {};
    this.onMicError = () => {};

    this.resetCapture();
    this.noise = 0.004;
  }

  configure(status) {
    const voice = (status && status.voice) || {};
    this.serverTts = Boolean(voice.tts && voice.tts.available);
    this.ttsOff = Boolean(voice.tts && voice.tts.engine === 'off');
    this.serverStt = Boolean(voice.stt && voice.stt.available);
    this.sttOff = Boolean(voice.stt && voice.stt.engine === 'off');
    this.language = (voice.stt && voice.stt.language) || 'fr';
  }

  // À appeler depuis un geste de l'utilisateur : les navigateurs bloquent l'audio sinon.
  async init() {
    if (!this.ctx) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      this.ctx = new AudioCtx();
      this.outputGain = this.ctx.createGain();
      this.outputAnalyser = this.ctx.createAnalyser();
      this.outputAnalyser.fftSize = 256;
      this.outputAnalyser.smoothingTimeConstant = 0.6;
      this.outputGain.connect(this.outputAnalyser);
      this.outputAnalyser.connect(this.ctx.destination);
      this.outputBins = new Uint8Array(this.outputAnalyser.frequencyBinCount);
      this.outputWave = new Uint8Array(this.outputAnalyser.fftSize);
    }
    if (this.ctx.state === 'suspended') await this.ctx.resume();
  }

  // ── Synthèse vocale ─────────────────────────────────────────────────────

  get speaking() {
    return this.draining;
  }

  get canSpeak() {
    return !this.ttsOff && (this.serverTts || 'speechSynthesis' in window);
  }

  speak(text) {
    const clean = (text || '').trim();
    if (!clean || !this.ttsEnabled || !this.canSpeak) return;
    const item = { text: clean, generation: this.generation, audio: null };
    // La synthèse démarre tout de suite, pendant que la phrase précédente est encore lue.
    if (this.serverTts) item.audio = this.fetchAudio(clean);
    this.queue.push(item);
    if (!this.draining) this.drain();
  }

  async fetchAudio(text) {
    try {
      const res = await fetch(`${this.apiUrl}/api/tts`, {
        method: 'POST',
        headers: this.headers({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ text }),
      });
      if (!res.ok) {
        if (res.status === 503) this.serverTts = false;
        return null;
      }
      return await this.ctx.decodeAudioData(await res.arrayBuffer());
    } catch (err) {
      console.warn('[voix] synthèse indisponible', err);
      return null;
    }
  }

  async drain() {
    this.draining = true;
    this.onSpeakingChange(true);
    while (this.queue.length) {
      const item = this.queue.shift();
      if (item.generation !== this.generation) continue;
      const buffer = item.audio ? await item.audio : null;
      if (item.generation !== this.generation) continue;
      if (buffer) await this.playBuffer(buffer);
      else await this.speakWithBrowser(item.text);
    }
    this.draining = false;
    this.onSpeakingChange(false);
  }

  playBuffer(buffer) {
    return new Promise((resolve) => {
      const source = this.ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(this.outputGain);
      source.onended = () => {
        if (this.currentSource === source) this.currentSource = null;
        resolve();
      };
      this.currentSource = source;
      source.start();
    });
  }

  speakWithBrowser(text) {
    return new Promise((resolve) => {
      if (!('speechSynthesis' in window)) return resolve();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = this.language === 'fr' ? 'fr-FR' : this.language;
      const voices = window.speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith(this.language));
      utterance.voice = voices.find((v) => /thomas|jacques|daniel/i.test(v.name)) || voices[0] || null;
      utterance.rate = 1.05;
      const done = () => {
        this.browserSpeaking = false;
        resolve();
      };
      utterance.onend = done;
      utterance.onerror = done;
      this.browserSpeaking = true;
      window.speechSynthesis.speak(utterance);
    });
  }

  stopSpeaking() {
    this.generation += 1;
    this.queue = [];
    if (this.currentSource) {
      try { this.currentSource.stop(); } catch (err) { /* déjà arrêtée */ }
    }
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  }

  // Niveau et spectre de la voix de Jarvis, pour animer le réacteur.
  outputLevel() {
    if (this.browserSpeaking) {
      const t = performance.now() / 1000;
      return { level: 0.35 + 0.25 * Math.abs(Math.sin(t * 7.3) * Math.sin(t * 2.1)), bins: null };
    }
    return this.readAnalyser(this.outputAnalyser, this.outputBins, this.outputWave, 2.2);
  }

  inputLevel() {
    return this.readAnalyser(this.inputAnalyser, this.inputBins, this.inputWave, 3.2);
  }

  readAnalyser(analyser, bins, wave, gain) {
    if (!analyser) return { level: 0, bins: null };
    analyser.getByteFrequencyData(bins);
    analyser.getByteTimeDomainData(wave);
    let sum = 0;
    for (let i = 0; i < wave.length; i++) {
      const sample = (wave[i] - 128) / 128;
      sum += sample * sample;
    }
    const normalized = new Float32Array(bins.length);
    for (let i = 0; i < bins.length; i++) normalized[i] = bins[i] / 255;
    return { level: Math.min(1, Math.sqrt(sum / wave.length) * gain), bins: normalized };
  }

  // ── Écoute ──────────────────────────────────────────────────────────────

  get canListen() {
    if (this.sttOff) return false;
    return this.serverStt || Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
  }

  get listening() {
    return Boolean(this.micStream || this.recognition);
  }

  async startListening() {
    if (this.listening) return true;
    if (!this.canListen) return false;
    return this.serverStt ? this.startMic() : this.startBrowserRecognition();
  }

  // Retour au premier plan : l'iPhone suspend le son et coupe le micro quand l'app passe en
  // arrière-plan. On relance ce qui peut l'être ; le son peut attendre un toucher de l'écran.
  async resume(wantMic) {
    if (this.ctx && this.ctx.state !== 'running') {
      const timeout = new Promise((resolve) => setTimeout(resolve, 1500));
      await Promise.race([this.ctx.resume().catch(() => {}), timeout]);
    }
    const track = this.micStream && this.micStream.getAudioTracks()[0];
    if (track && track.readyState === 'ended') this.stopListening();
    if (wantMic && !this.listening && this.canListen) return this.startListening();
    return this.listening;
  }

  stopListening() {
    if (this.micStream) {
      this.micStream.getTracks().forEach((track) => track.stop());
      this.micStream = null;
    }
    if (this.micSource) this.micSource.disconnect();
    if (this.micNode) this.micNode.disconnect();
    this.micSource = null;
    this.micNode = null;
    this.inputAnalyser = null;
    if (this.recognition) {
      const recognition = this.recognition;
      this.recognition = null;
      try { recognition.stop(); } catch (err) { /* déjà arrêtée */ }
    }
    this.resetCapture();
  }

  // Quand Jarvis parle ou réfléchit, le micro est ignoré : il ne doit pas s'entendre lui-même.
  setGated(gated) {
    if (gated && !this.gated) this.resetCapture();
    this.gated = gated;
  }

  async startMic() {
    try {
      this.micStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
    } catch (err) {
      this.micStream = null;
      this.onMicError(err);
      return false;
    }

    try {
      await this.ctx.audioWorklet.addModule('./mic-worklet.js');
      this.micSource = this.ctx.createMediaStreamSource(this.micStream);
      this.inputAnalyser = this.ctx.createAnalyser();
      this.inputAnalyser.fftSize = 256;
      this.inputAnalyser.smoothingTimeConstant = 0.55;
      this.inputBins = new Uint8Array(this.inputAnalyser.frequencyBinCount);
      this.inputWave = new Uint8Array(this.inputAnalyser.fftSize);
      this.micSource.connect(this.inputAnalyser);

      this.micNode = new AudioWorkletNode(this.ctx, 'mic-capture');
      this.micNode.port.onmessage = (event) => this.onBlock(event.data);
      this.micSource.connect(this.micNode);
      // Relié à la sortie à volume nul : certains navigateurs ne traitent que les nœuds reliés.
      const silent = this.ctx.createGain();
      silent.gain.value = 0;
      this.micNode.connect(silent);
      silent.connect(this.ctx.destination);
    } catch (err) {
      this.stopListening();
      this.onMicError(err);
      return false;
    }
    return true;
  }

  resetCapture() {
    this.preRoll = [];
    this.preRollSamples = 0;
    this.speech = [];
    this.speechSamples = 0;
    this.inSpeech = false;
    this.voicedMs = 0;
    this.silenceMs = 0;
  }

  // Détection d'activité vocale : ouvre une prise de parole quand le niveau dépasse
  // le bruit ambiant, la clôt après un silence, puis l'envoie à la transcription.
  onBlock(block) {
    if (this.gated) return;

    const rate = this.ctx.sampleRate;
    const blockMs = (block.length / rate) * 1000;
    let sum = 0;
    for (let i = 0; i < block.length; i++) sum += block[i] * block[i];
    const rms = Math.sqrt(sum / block.length);
    const threshold = Math.max(MIN_THRESHOLD, this.noise * 3.2);

    if (!this.inSpeech) {
      this.preRoll.push(block);
      this.preRollSamples += block.length;
      while (this.preRollSamples - this.preRoll[0].length > (PRE_ROLL_MS / 1000) * rate) {
        this.preRollSamples -= this.preRoll.shift().length;
      }

      if (rms > threshold) {
        this.voicedMs += blockMs;
        if (this.voicedMs >= START_MS) {
          this.inSpeech = true;
          this.speech = this.preRoll;
          this.speechSamples = this.preRollSamples;
          this.preRoll = [];
          this.preRollSamples = 0;
          this.silenceMs = 0;
          this.onSpeechStart();
        }
      } else {
        this.voicedMs = 0;
        // Le bruit de fond est estimé en continu, hors des prises de parole.
        this.noise = Math.min(0.05, this.noise * 0.96 + rms * 0.04);
      }
      return;
    }

    this.speech.push(block);
    this.speechSamples += block.length;
    this.silenceMs = rms > threshold * 0.7 ? 0 : this.silenceMs + blockMs;

    const durationMs = (this.speechSamples / rate) * 1000;
    if (this.silenceMs >= SILENCE_MS || durationMs >= MAX_SPEECH_MS) {
      const blocks = this.speech;
      const total = this.speechSamples;
      const voicedMs = durationMs - this.silenceMs - PRE_ROLL_MS;
      this.resetCapture();
      if (voicedMs >= MIN_SPEECH_MS) this.transcribe(blocks, total, rate);
    }
  }

  async transcribe(blocks, total, rate) {
    const samples = new Float32Array(total);
    let offset = 0;
    for (const block of blocks) {
      samples.set(block, offset);
      offset += block.length;
    }

    try {
      const res = await fetch(`${this.apiUrl}/api/stt`, {
        method: 'POST',
        headers: this.headers({ 'Content-Type': 'audio/wav' }),
        body: encodeWav(downsample(samples, rate, STT_RATE), STT_RATE),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const result = await res.json();
      if (result.text) this.onTranscript(result);
    } catch (err) {
      console.warn('[voix] transcription impossible', err);
    }
  }

  // Repli : reconnaissance vocale du navigateur (le son part alors chez son éditeur).
  startBrowserRecognition() {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) return false;

    const recognition = new Recognition();
    recognition.lang = this.language === 'fr' ? 'fr-FR' : this.language;
    recognition.continuous = true;
    recognition.interimResults = false;
    recognition.onresult = (event) => {
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (!event.results[i].isFinal || this.gated) continue;
        const text = event.results[i][0].transcript.trim();
        if (text) this.onTranscript({ text, ...extractCommand(text) });
      }
    };
    recognition.onerror = (event) => {
      if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
        this.recognition = null;
        this.onMicError(new Error(event.error));
      }
    };
    // Le navigateur coupe l'écoute après un silence : on la relance tant qu'elle est voulue.
    recognition.onend = () => {
      if (this.recognition === recognition) {
        setTimeout(() => {
          try { recognition.start(); } catch (err) { /* déjà relancée */ }
        }, 300);
      }
    };

    try {
      recognition.start();
    } catch (err) {
      this.onMicError(err);
      return false;
    }
    this.recognition = recognition;
    return true;
  }
}

// Ramène le signal à 16 kHz en moyennant les échantillons (filtre simple, suffisant pour la voix).
function downsample(samples, fromRate, toRate) {
  if (fromRate === toRate) return samples;
  const ratio = fromRate / toRate;
  const length = Math.floor(samples.length / ratio);
  const output = new Float32Array(length);
  for (let i = 0; i < length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(samples.length, Math.max(start + 1, Math.floor((i + 1) * ratio)));
    let sum = 0;
    for (let j = start; j < end; j++) sum += samples[j];
    output[i] = sum / (end - start);
  }
  return output;
}

function encodeWav(samples, rate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeText = (offset, text) => {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
  };

  writeText(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  writeText(8, 'WAVE');
  writeText(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);        // PCM
  view.setUint16(22, 1, true);        // mono
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeText(36, 'data');
  view.setUint32(40, samples.length * 2, true);

  for (let i = 0; i < samples.length; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  }
  return buffer;
}
