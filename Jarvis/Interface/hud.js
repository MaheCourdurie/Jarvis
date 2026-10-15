import { ReactorCore } from './core.js';
import { VoiceEngine } from './voice.js';

// Le HUD est normalement servi par l'API (même origine). S'il est servi à part
// (./run_jarvis.sh web, port 8000), l'API est attendue sur le port 8001.
const API_URL = location.port === '8000' ? `${location.protocol}//${location.hostname}:8001` : location.origin;

// Depuis un autre appareil (téléphone), l'API exige un code d'accès. Il est transmis une
// fois par le lien d'appairage (…/#code=XXXX), puis conservé dans ce navigateur.
const TOKEN_KEY = 'jarvis.token';

function readToken() {
  try { return localStorage.getItem(TOKEN_KEY) || ''; } catch (err) { return ''; }
}

function storeToken(token) {
  try { localStorage.setItem(TOKEN_KEY, token); } catch (err) { /* stockage indisponible */ }
}

(function pairFromLink() {
  const match = location.hash.match(/(?:^#|&)code=([^&]+)/);
  if (!match) return;
  storeToken(decodeURIComponent(match[1]));
  // Le code ne reste ni dans la barre d'adresse ni dans l'historique.
  history.replaceState(null, '', location.pathname + location.search);
})();

// Le code se colle tel quel, ou avec le lien d'appairage entier (…/#code=XXXX).
function codeFrom(text) {
  const value = (text || '').trim();
  const match = value.match(/[#&?]code=([^&\s]+)/);
  return match ? decodeURIComponent(match[1]) : value;
}

// Où tourne l'interface : sur le Mac lui-même, ou dans l'app installée sur l'écran d'accueil.
// Sur iPhone, l'app installée a son propre stockage : elle redemande le code une fois.
const ON_MAC = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
const INSTALLED = navigator.standalone === true || window.matchMedia('(display-mode: standalone)').matches;
const IOS = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

// Le service worker garde l'interface en cache : l'app s'ouvre même quand le Mac est injoignable.
if ('serviceWorker' in navigator && window.isSecureContext) {
  navigator.serviceWorker.register('./sw.js').catch((err) => console.warn('[app] mise en cache impossible', err));
}

function authHeaders(headers = {}) {
  const token = readToken();
  return token ? { ...headers, 'X-Jarvis-Token': token } : headers;
}

const ATTENTIVE_MS = 12000;        // après une réponse, Jarvis écoute sans qu'on redise son prénom
const CONFIRM_MS = 30000;          // délai laissé pour répondre à « Dois-je l'envoyer ? »
const UNGATE_DELAY_MS = 350;       // le micro rouvre un instant après la fin de la voix

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function loadSetting(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? fallback : raw === 'true';
  } catch (err) {
    return fallback;
  }
}

function saveSetting(key, value) {
  try { localStorage.setItem(key, String(value)); } catch (err) { /* stockage indisponible */ }
}

const state = {
  status: null,
  title: 'Monsieur',
  history: [],
  pending: null,              // action en attente d'un « oui » ou d'un « non »
  mode: 'offline',            // offline | standby | attentive | thinking | speaking
  attentiveUntil: 0,
  afterReply: 'attentive',
  busy: false,
  silenced: false,            // l'utilisateur a fait taire la réponse en cours
  activity: '',               // ce que Jarvis est en train de faire (« Recherche web »)
  alertUntil: 0,
  lastEventId: null,
  booted: false,
  authLoading: false,
  micWanted: loadSetting('jarvis.mic', true),
  voiceWanted: loadSetting('jarvis.voice', true),
  continuous: loadSetting('jarvis.continuous', false),
};

const voice = new VoiceEngine(API_URL, authHeaders);
const core = new ReactorCore($('core'));
let ungateTimer = null;
let heardTimer = null;
let toastTimer = null;

// ── Accès à l'API ─────────────────────────────────────────────────────────

async function api(path, options = {}) {
  const res = await fetch(`${API_URL}${path}`, {
    signal: AbortSignal.timeout(options.timeout || 8000),
    ...options,
    headers: authHeaders(options.headers || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(data.detail || `HTTP ${res.status}`);
    error.status = res.status;
    throw error;
  }
  return data;
}

// ── États du HUD ──────────────────────────────────────────────────────────

function stateLabel() {
  switch (state.mode) {
    case 'thinking': return state.activity || 'Analyse';
    case 'speaking': return 'Réponse';
    case 'attentive': return 'À l\'écoute';
    case 'standby':
      if (!voice.listening) return 'En veille';
      return state.continuous ? 'À l\'écoute' : 'En veille · dites « Jarvis »';
    default: return 'Hors ligne';
  }
}

function coreState() {
  if (Date.now() < state.alertUntil) return 'alert';
  switch (state.mode) {
    case 'thinking': return 'thinking';
    case 'speaking': return 'speaking';
    case 'attentive': return 'listening';
    case 'standby': return state.continuous && voice.listening ? 'listening' : 'idle';
    default: return 'offline';
  }
}

function render() {
  const visual = coreState();
  core.setState(visual);
  document.body.dataset.state = visual;
  $('coreState').textContent = Date.now() < state.alertUntil ? 'Alerte' : stateLabel();
}

function setMode(mode) {
  state.mode = mode;
  clearTimeout(ungateTimer);
  if (mode === 'standby' || mode === 'attentive') {
    // Le micro ne rouvre qu'après un court délai, pour ne pas capter la fin de la voix de Jarvis.
    ungateTimer = setTimeout(() => voice.setGated(false), UNGATE_DELAY_MS);
  } else {
    voice.setGated(true);
  }
  render();
}

function finishTurn() {
  const wantsAnswer = Boolean(state.pending);
  if (voice.listening && (state.afterReply === 'attentive' || wantsAnswer)) {
    state.attentiveUntil = Date.now() + (wantsAnswer ? CONFIRM_MS : ATTENTIVE_MS);
    setMode('attentive');
  } else {
    setMode('standby');
  }
}

// ── Journal de conversation ───────────────────────────────────────────────

function fillText(node, text) {
  node.textContent = '';
  const parts = String(text).split(/(https?:\/\/[^\s]+)/g);
  for (const part of parts) {
    if (/^https?:\/\//.test(part)) {
      const link = document.createElement('a');
      link.href = part;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = part;
      node.appendChild(link);
    } else if (part) {
      node.appendChild(document.createTextNode(part));
    }
  }
}

function addEntry(role, text, extraClass = '') {
  const log = $('log');
  const entry = document.createElement('div');
  entry.className = `entry ${role} ${extraClass}`.trim();
  const who = document.createElement('span');
  who.className = 'who';
  who.textContent = role === 'user' ? state.title : 'Jarvis';
  const body = document.createElement('div');
  body.className = 'text';
  fillText(body, text);
  entry.append(who, body);
  log.appendChild(entry);
  log.scrollTop = log.scrollHeight;
  return entry;
}

// Sous une réponse tirée du web : les pages consultées, en liens cliquables.
function addSources(entry, sources) {
  if (!sources || !sources.length) return;
  const list = document.createElement('div');
  list.className = 'sources';
  const label = document.createElement('span');
  label.textContent = 'Sources';
  list.appendChild(label);
  for (const source of sources) {
    if (!/^https?:\/\//.test(source.url)) continue;
    const link = document.createElement('a');
    link.href = source.url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = source.site || source.title;
    link.title = source.title || source.url;
    list.appendChild(link);
  }
  entry.querySelector('.text').appendChild(list);
  $('log').scrollTop = $('log').scrollHeight;
}

function setEntryText(entry, text) {
  fillText(entry.querySelector('.text'), text);
  $('log').scrollTop = $('log').scrollHeight;
}

function showHeard(text, accepted) {
  const heard = $('heard');
  heard.textContent = accepted ? `» ${text}` : `… ${text}`;
  heard.style.opacity = accepted ? '1' : '0.45';
  clearTimeout(heardTimer);
  heardTimer = setTimeout(() => { heard.textContent = ''; }, accepted ? 6000 : 2500);
}

function showToast(message) {
  const toast = $('toast');
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 3200);
}

// ── Dialogue ──────────────────────────────────────────────────────────────

async function readStream(res, onEvent) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let newline;
    while ((newline = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (line) onEvent(JSON.parse(line));
    }
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer));
}

async function send(rawText) {
  const text = rawText.trim();
  if (!text || state.busy || !state.booted) return;

  voice.stopSpeaking();
  state.busy = true;
  state.silenced = false;
  state.activity = '';
  addEntry('user', text);
  state.history.push({ role: 'user', content: text });
  setMode('thinking');

  const entry = addEntry('jarvis', '', 'pending');
  let streamed = '';
  let final = null;

  try {
    const res = await fetch(`${API_URL}/api/chat/stream`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        message: text,
        history: state.history.slice(-20),
        pending: state.pending,
        client: 'hud',
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    await readStream(res, (event) => {
      if (event.type === 'sentence') {
        // Chaque phrase est affichée et prononcée dès qu'elle arrive.
        streamed += (streamed ? ' ' : '') + event.text;
        setEntryText(entry, streamed);
        if (!state.silenced) voice.speak(event.text);
      } else if (event.type === 'status') {
        state.activity = event.label || '';
        render();
      } else if (event.type === 'final') {
        final = event;
      }
    });
  } catch (err) {
    console.warn('[hud] échange impossible', err);
  }

  if (!final) {
    const reply = `Je ne parviens pas à joindre mon noyau, ${state.title}. Vérifiez que l'API est lancée.`;
    final = { reply: streamed || reply, speech: streamed ? '' : reply, streamed: Boolean(streamed) };
  }

  entry.classList.remove('pending');
  if (!final.streamed) {
    setEntryText(entry, final.reply);
    if (!state.silenced) voice.speak(final.speech || final.reply);
  }

  if (final.data && final.data.sources) addSources(entry, final.data.sources);

  state.pending = final.pending || null;
  state.history.push({ role: 'assistant', content: final.reply });
  state.afterReply = final.data && final.data.standby ? 'standby' : 'attentive';
  state.busy = false;
  state.activity = '';

  if (final.action && !['smalltalk', 'web_answer'].includes(final.action)) refreshDashboard();
  if (voice.speaking) setMode('speaking');
  else finishTurn();
}

// Ce que le micro a entendu : un ordre s'il est adressé à Jarvis, sinon on l'ignore.
function onTranscript(result) {
  const text = (result.text || '').trim();
  if (!text || state.busy || state.mode === 'thinking' || state.mode === 'speaking') return;

  const attentive = state.continuous || (state.mode === 'attentive' && Date.now() < state.attentiveUntil);
  let command = null;
  if (result.wake) command = result.command || 'Jarvis';
  else if (attentive) command = text;

  if (command === null) {
    showHeard(text, false);
    return;
  }
  showHeard(text, true);
  send(command);
}

// Fait taire Jarvis : la réponse en cours reste affichée, mais la suite n'est plus prononcée.
function silence() {
  state.silenced = true;
  voice.stopSpeaking();
}

// Réveil sans prononcer le prénom (clic sur le réacteur ou barre d'espace).
function wake() {
  if (!state.booted) return;
  // Un toucher suffit à rétablir le son si l'iPhone l'a suspendu.
  voice.init().catch(() => {});
  if (voice.speaking) {
    silence();
    return;
  }
  if (state.busy) return;
  if (voice.listening) {
    state.attentiveUntil = Date.now() + ATTENTIVE_MS;
    setMode('attentive');
  } else {
    $('commandInput').focus();
  }
}

// ── Panneaux ──────────────────────────────────────────────────────────────

function setGauge(id, percent, label, inverted = false) {
  const gauge = $(id);
  const known = typeof percent === 'number' && !Number.isNaN(percent);
  gauge.querySelector('.gauge-value').textContent = label;
  gauge.querySelector('.gauge-bar i').style.width = known ? `${Math.max(2, Math.min(100, percent))}%` : '0%';
  // inverted : la jauge est préoccupante quand elle est basse (batterie).
  const stress = known ? (inverted ? 100 - percent : percent) : 0;
  gauge.classList.toggle('warn', stress >= 80 && stress < 92);
  gauge.classList.toggle('crit', stress >= 92);
}

async function refreshSystem() {
  try {
    const metrics = await api('/api/system', { timeout: 4000 });
    setGauge('gaugeCpu', metrics.cpu_percent, metrics.cpu_percent === null ? '—' : `${metrics.cpu_percent} %`);
    if (metrics.memory) {
      setGauge('gaugeMem', metrics.memory.percent, `${metrics.memory.percent} % · ${metrics.memory.total_gb} Go`);
    }
    if (metrics.disk) {
      setGauge('gaugeDisk', metrics.disk.percent, `${metrics.disk.free_gb} Go libres`);
    }
    if (metrics.battery) {
      const source = metrics.battery.plugged ? 'secteur' : 'batterie';
      setGauge('gaugeBattery', metrics.battery.percent, `${metrics.battery.percent} % · ${source}`, !metrics.battery.plugged);
    } else {
      setGauge('gaugeBattery', 100, 'secteur');
    }
    const note = $('systemNote');
    const alerts = metrics.alerts || [];
    note.textContent = alerts.length ? alerts[0] : `${metrics.hostname} · ${metrics.os}`;
    note.classList.toggle('warn', alerts.length > 0);
  } catch (err) {
    $('systemNote').textContent = 'Capteurs injoignables';
  }
}

function formatHour(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
}

function listItem(when, what, sub, extraClass) {
  const item = document.createElement('li');
  if (extraClass) item.className = extraClass;
  const left = document.createElement('span');
  left.className = 'when';
  left.textContent = when;
  const right = document.createElement('span');
  right.className = 'what';
  right.textContent = what;
  if (sub) {
    const detail = document.createElement('span');
    detail.className = 'sub';
    detail.textContent = sub;
    right.appendChild(detail);
  }
  item.append(left, right);
  return item;
}

function emptyItem(text) {
  const item = document.createElement('li');
  item.className = 'muted';
  item.textContent = text;
  return item;
}

async function refreshDashboard() {
  let data;
  try {
    data = await api('/api/dashboard', { timeout: 15000 });
  } catch (err) {
    return;
  }

  const weather = data.weather;
  if (weather) {
    $('weatherTemp').textContent = `${weather.temperature}°`;
    $('weatherDesc').textContent = `${weather.city} · ${weather.description}`;
    $('weatherNote').textContent = weather.today
      ? `${weather.today.min}° / ${weather.today.max}° · pluie ${weather.today.rain_probability} % · vent ${weather.wind_kmh} km/h`
      : '';
  } else {
    $('weatherTemp').textContent = '—';
    $('weatherDesc').textContent = 'Météo indisponible';
    $('weatherNote').textContent = '';
  }

  const agenda = $('agendaList');
  agenda.textContent = '';
  if (data.events === null || data.events === undefined) {
    agenda.appendChild(emptyItem(data.google ? 'Agenda indisponible' : 'Google non relié'));
  } else if (!data.events.length) {
    agenda.appendChild(emptyItem('Rien de prévu aujourd\'hui'));
  } else {
    const now = Date.now();
    for (const event of data.events) {
      const past = new Date(event.end).getTime() < now;
      agenda.appendChild(listItem(event.all_day ? 'Jour' : formatHour(event.start), event.title, event.location, past ? 'past' : ''));
    }
  }

  const mailCount = $('mailCount');
  const mailList = $('mailList');
  mailList.textContent = '';
  if (data.unread === null || data.unread === undefined) {
    mailCount.textContent = '—';
    mailList.appendChild(emptyItem(data.google ? 'Messagerie indisponible' : 'Google non relié'));
  } else {
    mailCount.textContent = data.unread >= 5 ? '5+' : String(data.unread);
    const unit = document.createElement('small');
    unit.textContent = data.unread > 1 ? 'non lus' : 'non lu';
    mailCount.appendChild(unit);
    for (const mail of data.unread_items || []) {
      mailList.appendChild(listItem('✉', mail.from, mail.subject));
    }
  }

  const alarmList = $('alarmList');
  alarmList.textContent = '';
  if (!data.alarms || !data.alarms.length) {
    alarmList.appendChild(emptyItem('Aucune alarme'));
  } else {
    for (const alarm of data.alarms.slice(0, 6)) {
      const when = new Date(alarm.when);
      const sameDay = when.toDateString() === new Date().toDateString();
      const day = sameDay ? '' : when.toLocaleDateString('fr-FR', { weekday: 'short', day: 'numeric' });
      alarmList.appendChild(listItem(formatHour(alarm.when), alarm.label, day));
    }
  }
}

function setLink(id, text, level) {
  const node = $(id);
  node.textContent = text;
  node.className = `link-value ${level}`;
}

function renderStatus() {
  const status = state.status;
  if (!status) return;

  setLink('linkModel', status.model_name, status.model_online ? 'ok' : 'ko');

  const tts = status.voice.tts;
  if (tts.engine === 'off') setLink('linkVoice', 'désactivée', 'warn');
  else if (tts.available) setLink('linkVoice', `${tts.engine} · locale`, 'ok');
  else setLink('linkVoice', 'navigateur', 'warn');

  const stt = status.voice.stt;
  if (stt.engine === 'off') setLink('linkEars', 'désactivée', 'warn');
  else if (stt.available) setLink('linkEars', `${stt.engine} ${stt.model} · locale`, voice.listening ? 'ok' : 'warn');
  else setLink('linkEars', voice.canListen ? 'navigateur (cloud)' : 'indisponible', voice.canListen ? 'warn' : 'ko');

  const google = status.mail || {};
  setLink('linkGoogle', google.configured ? 'relié' : 'non relié', google.configured ? 'ok' : 'warn');
  $('googleConnectBtn').disabled = state.authLoading || Boolean(google.configured);
  $('googleDisconnectBtn').disabled = state.authLoading || !google.configured;
}

async function refreshStatus() {
  state.status = await api('/api/status', { timeout: 5000 });
  state.title = state.status.persona.title;
  voice.configure(state.status);
  renderStatus();
  return state.status;
}

function updateClock() {
  const now = new Date();
  $('clock').textContent = now.toLocaleTimeString('fr-FR');
  $('date').textContent = now.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' });
  // L'état « alerte » et la fenêtre d'écoute expirent sans autre événement : on rafraîchit ici.
  if (state.mode === 'attentive' && Date.now() > state.attentiveUntil && !state.busy) setMode('standby');
  else render();
}

// ── Événements proactifs (alarmes) ────────────────────────────────────────

async function pollEvents() {
  try {
    const query = state.lastEventId === null ? '' : `?after=${state.lastEventId}`;
    const data = await api(`/api/events${query}`, { timeout: 4000 });
    state.lastEventId = data.last_id;
    for (const event of data.events || []) {
      if (event.type === 'alarm') announceAlarm(event);
      else if (event.type === 'creation') announceCreation(event);
      else if (event.type === 'notice') announceNotice(event);
    }
  } catch (err) {
    /* l'API redémarre peut-être : on réessaiera */
  }
}

function announceAlarm(event) {
  state.alertUntil = Date.now() + 8000;
  addEntry('jarvis', `⏰ ${event.speech || event.label}`, 'alert');
  voice.speak(event.speech || event.label);
  render();
  refreshDashboard();
}

// Une création de l'atelier (code, page, logo, palette) est prête, ou a échoué.
function announceCreation(event) {
  addEntry('jarvis', `✦ ${event.text || event.speech || event.label}`);
  voice.speak(event.speech || event.label);
  render();
}

// Un rappel de Jarvis (rendez-vous qui approche, trajet compris).
function announceNotice(event) {
  state.alertUntil = Date.now() + 6000;
  addEntry('jarvis', `🔔 ${event.text || event.speech || event.label}`, 'alert');
  voice.speak(event.speech || event.text || event.label);
  render();
}

// ── Liaison Google ────────────────────────────────────────────────────────

async function toggleGoogle(connect) {
  if (state.authLoading) return;
  state.authLoading = true;
  renderStatus();
  showToast(connect ? 'Ouverture du consentement Google…' : 'Coupure de la liaison Google…');
  try {
    const data = await api(`/api/google/${connect ? 'connect' : 'disconnect'}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      timeout: 180000,
    });
    addEntry('jarvis', data.message);
    voice.speak(data.message);
  } catch (err) {
    addEntry('jarvis', `La liaison Google a échoué, ${state.title} : ${err.message}`);
  } finally {
    state.authLoading = false;
    await refreshStatus().catch(() => {});
    refreshDashboard();
  }
}

// ── Réglages ──────────────────────────────────────────────────────────────

function renderToggles() {
  $('micToggle').setAttribute('aria-pressed', String(voice.listening));
  $('voiceToggle').setAttribute('aria-pressed', String(voice.ttsEnabled));
  $('continuousToggle').setAttribute('aria-pressed', String(state.continuous));
  renderStatus();
  render();
}

async function setMic(enabled) {
  state.micWanted = enabled;
  saveSetting('jarvis.mic', enabled);
  if (enabled) {
    if (!voice.canListen) {
      showToast('Aucune reconnaissance vocale disponible');
    } else if (!(await voice.startListening())) {
      showToast('Micro inaccessible — vérifiez l\'autorisation du navigateur');
    }
  } else {
    voice.stopListening();
  }
  if (state.mode === 'attentive' && !voice.listening) setMode('standby');
  renderToggles();
}

function setVoice(enabled) {
  state.voiceWanted = enabled;
  voice.ttsEnabled = enabled;
  saveSetting('jarvis.voice', enabled);
  if (!enabled) voice.stopSpeaking();
  renderToggles();
}

function setContinuous(enabled) {
  state.continuous = enabled;
  saveSetting('jarvis.continuous', enabled);
  renderToggles();
}

function clearConversation() {
  voice.stopSpeaking();
  state.history = [];
  state.pending = null;
  $('log').textContent = '';
  showToast('Conversation effacée');
}

async function openHelp() {
  $('help').hidden = false;
  try {
    const data = await api('/api/commands');
    $('commandsHelp').textContent = data.commands_help;
  } catch (err) {
    $('commandsHelp').textContent = 'Commandes indisponibles : API injoignable.';
  }
}

// ── Installation sur l'écran d'accueil ────────────────────────────────────

let installPrompt = null;   // Android : l'installation proposée par le navigateur

function setupInstall() {
  $('installToggle').hidden = INSTALLED || ON_MAC || !(IOS || installPrompt);
}

function openInstall() {
  if (installPrompt) {
    // Android : le navigateur installe l'app lui-même, et elle garde le code d'accès.
    installPrompt.prompt();
    installPrompt = null;
    setupInstall();
    return;
  }
  $('installCode').hidden = true;
  $('install').hidden = false;
}

async function copyCode() {
  const code = readToken();
  if (!code) {
    showToast('Aucun code d\'accès sur cet appareil');
    return;
  }
  try {
    await navigator.clipboard.writeText(code);
    showToast('Code copié');
  } catch (err) {
    // Copie refusée : le code s'affiche, prêt à être copié à la main.
    const field = $('installCode');
    field.value = code;
    field.hidden = false;
    field.select();
  }
}

// ── Démarrage ─────────────────────────────────────────────────────────────

function bootLine(label, value, level) {
  const line = document.createElement('li');
  const left = document.createElement('span');
  left.textContent = label;
  const right = document.createElement('span');
  right.className = level;
  right.textContent = value;
  line.append(left, right);
  $('bootLines').appendChild(line);
}

// Demande le code d'accès sur l'écran de démarrage (connexion depuis un autre appareil).
function askAccessCode(message) {
  const form = $('bootCode');
  form.hidden = false;
  $('bootBtn').hidden = true;     // « Connexion… » attend le code : inutile de l'afficher
  $('bootHint').textContent = message;
  const paste = $('bootCodePaste');
  paste.hidden = !(navigator.clipboard && navigator.clipboard.readText);
  paste.onclick = async () => {
    try {
      $('bootCodeInput').value = codeFrom(await navigator.clipboard.readText());
    } catch (err) {
      $('bootHint').textContent = 'Collage refusé : touchez longuement le champ, puis « Coller ».';
    }
  };
  return new Promise((resolve) => {
    form.onsubmit = (event) => {
      event.preventDefault();
      const code = codeFrom($('bootCodeInput').value);
      if (!code) return;
      storeToken(code);
      form.hidden = true;
      $('bootBtn').hidden = false;
      resolve();
    };
  });
}

async function waitForCore() {
  const button = $('bootBtn');
  const hint = $('bootHint');
  for (;;) {
    try {
      await refreshStatus();
      button.disabled = false;
      button.textContent = 'Initialiser';
      hint.textContent = 'Noyau détecté. Touchez pour initialiser les systèmes.';
      return;
    } catch (err) {
      if (err.status === 401) {
        const first = INSTALLED
          ? 'Première ouverture de l\'app : collez le code d\'accès copié depuis Safari (bouton « App »).'
          : 'Saisissez le code d\'accès affiché sur le Mac.';
        await askAccessCode(readToken() ? 'Code refusé. Saisissez le code d\'accès affiché sur le Mac.' : first);
        continue;
      }
      if (err.status === 403) hint.textContent = err.message;
      else if (ON_MAC) hint.textContent = `Noyau injoignable sur ${API_URL} — lancez ./run_jarvis.sh start`;
      // Sur le téléphone, l'interface vient du cache : Jarvis se reconnecte dès que le Mac répond.
      else hint.textContent = 'Jarvis est injoignable. Vérifiez que Tailscale est activé sur cet appareil et que le Mac est allumé.';
      await sleep(2500);
    }
  }
}

async function boot() {
  const button = $('bootBtn');
  button.disabled = true;
  button.textContent = 'Initialisation…';
  $('bootHint').textContent = '';

  await voice.init();
  const status = state.status;
  const tts = status.voice.tts;
  const stt = status.voice.stt;

  const lines = [
    [`Noyau J.A.R.V.I.S. v${status.version}`, 'EN LIGNE', 'ok'],
    [`Modèle de langage · ${status.model_name}`, status.model_online ? 'EN LIGNE' : 'HORS LIGNE', status.model_online ? 'ok' : 'ko'],
    ['Synthèse vocale', tts.engine === 'off' ? 'DÉSACTIVÉE' : tts.available ? `${tts.engine.toUpperCase()} · LOCAL` : 'NAVIGATEUR', tts.available ? 'ok' : 'warn'],
    ['Reconnaissance vocale', stt.engine === 'off' ? 'DÉSACTIVÉE' : stt.available ? `${stt.engine.toUpperCase()} · LOCAL` : voice.canListen ? 'NAVIGATEUR' : 'INDISPONIBLE', stt.available ? 'ok' : 'warn'],
    ['Services Google', status.mail.configured ? 'RELIÉS' : 'NON RELIÉS', status.mail.configured ? 'ok' : 'warn'],
    ['Capteurs système', 'EN LIGNE', 'ok'],
  ];
  for (const [label, value, level] of lines) {
    bootLine(label, value, level);
    await sleep(240);
  }

  voice.ttsEnabled = state.voiceWanted;
  if (state.micWanted && voice.canListen) {
    const granted = await voice.startListening();
    bootLine('Microphone', granted ? 'ACTIF' : 'REFUSÉ', granted ? 'ok' : 'warn');
    await sleep(300);
  }

  $('boot').classList.add('done');
  $('hud').classList.add('live');
  $('hud').removeAttribute('aria-hidden');
  state.booted = true;
  setMode('standby');
  renderToggles();

  refreshSystem();
  refreshDashboard();
  keepModelWarm();
  // Tant que le HUD est ouvert, le modèle reste en mémoire : pas d'attente de rechargement.
  setInterval(keepModelWarm, 10 * 60 * 1000);
  setInterval(refreshSystem, 3000);
  setInterval(refreshDashboard, 60000);
  setInterval(() => refreshStatus().catch(() => {}), 15000);
  await pollEvents();
  setInterval(pollEvents, 2500);

  greet();
}

function keepModelWarm() {
  api('/api/warmup', { method: 'POST' }).catch(() => {});
}

// « Bonjour, Monsieur. Il est 7 heures… » : le briefing d'accueil.
async function greet() {
  state.busy = true;
  setMode('thinking');
  let briefing;
  try {
    briefing = await api('/api/briefing?kind=boot', { timeout: 20000 });
  } catch (err) {
    briefing = { reply: `Systèmes en ligne, ${state.title}.`, speech: `Systèmes en ligne, ${state.title}.` };
  }
  addEntry('jarvis', briefing.reply);
  state.history.push({ role: 'assistant', content: briefing.reply });
  voice.speak(briefing.speech || briefing.reply);
  state.afterReply = 'standby';
  state.busy = false;
  if (voice.speaking) setMode('speaking');
  else finishTurn();
}

// ── Branchements ──────────────────────────────────────────────────────────

voice.onTranscript = onTranscript;
voice.onSpeechStart = () => {
  if (state.mode === 'attentive') state.attentiveUntil = Date.now() + ATTENTIVE_MS;
};
voice.onSpeakingChange = (speaking) => {
  if (speaking) setMode('speaking');
  else if (state.busy) setMode('thinking');
  else finishTurn();
};
voice.onMicError = (err) => {
  console.warn('[hud] micro indisponible', err);
  renderToggles();
};

core.setLevelSource(() => {
  if (state.mode === 'speaking') return voice.outputLevel();
  if (voice.listening && (state.mode === 'attentive' || state.mode === 'standby')) {
    const sample = voice.inputLevel();
    // En veille, le réacteur ne réagit que faiblement aux bruits ambiants.
    if (state.mode === 'standby' && !state.continuous) sample.level *= 0.4;
    return sample;
  }
  return { level: 0, bins: null };
});
core.start();

$('bootBtn').addEventListener('click', boot);
$('coreWrap').addEventListener('click', wake);
$('commandForm').addEventListener('submit', (event) => {
  event.preventDefault();
  const input = $('commandInput');
  if (!input.value.trim()) return;
  if (state.busy) {
    // L'ordre reste dans la barre de saisie : il ne doit pas être perdu.
    showToast(`Un instant, ${state.title} : je termine la demande en cours.`);
    return;
  }
  const text = input.value;
  input.value = '';
  send(text);
});
$('micToggle').addEventListener('click', () => setMic(!voice.listening));
$('voiceToggle').addEventListener('click', () => setVoice(!voice.ttsEnabled));
$('continuousToggle').addEventListener('click', () => setContinuous(!state.continuous));
$('clearBtn').addEventListener('click', clearConversation);
$('helpToggle').addEventListener('click', openHelp);
$('helpClose').addEventListener('click', () => { $('help').hidden = true; });
$('help').addEventListener('click', (event) => {
  if (event.target === $('help')) $('help').hidden = true;
});
$('googleConnectBtn').addEventListener('click', () => toggleGoogle(true));
$('googleDisconnectBtn').addEventListener('click', () => toggleGoogle(false));
$('installToggle').addEventListener('click', openInstall);
$('installClose').addEventListener('click', () => { $('install').hidden = true; });
$('install').addEventListener('click', (event) => {
  if (event.target === $('install')) $('install').hidden = true;
});
$('copyCodeBtn').addEventListener('click', copyCode);
window.addEventListener('beforeinstallprompt', (event) => {
  event.preventDefault();
  installPrompt = event;
  setupInstall();
});

// Retour dans l'app (écran déverrouillé, autre app quittée) : l'iPhone a pu couper le son et le micro.
document.addEventListener('visibilitychange', async () => {
  if (document.visibilityState !== 'visible' || !state.booted) return;
  await voice.resume(state.micWanted);
  renderToggles();
  refreshStatus().catch(() => {});
});

// Après un clic à la souris, le bouton rend le focus : la barre d'espace reste dédiée au réveil.
document.addEventListener('mouseup', (event) => {
  const button = event.target.closest ? event.target.closest('button') : null;
  if (button) button.blur();
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    $('help').hidden = true;
    $('install').hidden = true;
    silence();
    return;
  }
  const typing = ['INPUT', 'TEXTAREA', 'BUTTON'].includes(document.activeElement && document.activeElement.tagName);
  if (event.code === 'Space' && !typing) {
    event.preventDefault();
    wake();
  }
});

updateClock();
setInterval(updateClock, 1000);
setupInstall();
waitForCore();
