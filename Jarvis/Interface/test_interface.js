const API_URL = 'http://localhost:8001';

let history     = [];
let msgCount    = 0;
let isLoading   = false;
let isApiReachable = false;
let isJarvisAvailable = false;
let mailConfigured = false;
let mailProvider = 'google';
let mailMissingKeys = [];
let isAuthLoading = false;

function providerLabel(provider) {
  const p = String(provider || '').toLowerCase();
  if (p === 'google') return 'Google';
  return 'mail/calendrier';
}

// Commandes liées au provider mail/calendrier qui nécessitent une vérification spéciale
const MAIL_COMMANDS = new Set([
  '/mailresume',
  '/maillast',
  '/sendmail',
  '/eventsweek',
  '/availability',
  '/addevent',
  '/deleteevent',
]);

// Vérifie si le message est une commande mail/calendrier
function isMailCommand(text) {
  const t = text.trim().toLowerCase();
  if (!t.startsWith('/')) return false;
  const command = t.split(/\s+/)[0];
  return MAIL_COMMANDS.has(command);
}

function isLikelyMailPhrase(text) {
  const t = text.toLowerCase();
  if (/mail|email|courrier/.test(t)) return true;
  if (/calendrier|agenda|réunion|reunion|événement|evenement|planning|disponib/.test(t)) return true;
  return false;
}

function isLikelyActionPhrase(text) {
  const t = text.toLowerCase();
  if (/mail|email|courrier/.test(t)) return true;
  if (/calendrier|agenda|réunion|reunion|événement|evenement|planning|disponib/.test(t)) return true;
  if (/alarme|réveil|reveil|rappel/.test(t)) return true;
  return false;
}

// Met à jour l'état du bouton d'envoi en fonction de la disponibilité de Jarvis et de l'API
function updateSendAvailability() {
  const sendBtn = document.getElementById('sendBtn');
  sendBtn.disabled = isLoading || !isApiReachable;
}

function updateAuthButtons() {
  const connectBtn = document.getElementById('googleConnectBtn');
  const disconnectBtn = document.getElementById('googleDisconnectBtn');

  if (!connectBtn || !disconnectBtn) return;

  const disabledBase = !isApiReachable || isAuthLoading;
  connectBtn.disabled = disabledBase || mailConfigured;
  disconnectBtn.disabled = disabledBase || !mailConfigured;
}

// Affiche une notification si Jarvis n'est pas disponible et empêche l'envoi du message
function showJarvisUnavailable() {
  showToast('JARVIS INDISPONIBLE');
  addMessage('jarvis', 'JARVIS INDISPONIBLE\nTon message n\'a pas été envoyé.');
}

// ── Verifie le statut ───────────────────────────────────────
async function checkStatus() {
  try {
    const res  = await fetch(`${API_URL}/api/status`, { signal: AbortSignal.timeout(3000) });
    const data = await res.json();
    const hasJarvis = Boolean(data.model_online);
    const mail = data.mail || {};
    mailProvider = String(mail.provider || 'google').toLowerCase();
    mailMissingKeys = Array.isArray(mail.missing_keys) ? mail.missing_keys : [];

    isApiReachable = true;
    isJarvisAvailable = hasJarvis;
    mailConfigured = Boolean(mail.configured);
    updateSendAvailability();
    updateAuthButtons();

    document.getElementById('statusDot').className   = 'status-dot' + (hasJarvis ? '' : ' offline');
    document.getElementById('statusLabel').textContent = hasJarvis ? 'jarvis · en ligne' : 'jarvis · indisponible';

    const mailAuthState = document.getElementById('mailAuthState');
    const mailAuthHint = document.getElementById('mailAuthHint');
    const provider = providerLabel(mailProvider);
    if (mailAuthState) {
      if (mailConfigured) {
        mailAuthState.textContent = `${provider} actif`;
      } else {
        mailAuthState.textContent = `${provider} non configuré`;
      }
    }
    if (mailAuthHint) {
      if (!mailConfigured && mailMissingKeys.length > 0) {
        mailAuthHint.textContent = `Variables manquantes: ${mailMissingKeys.join(', ')}`;
      } else {
        mailAuthHint.textContent = mailConfigured
          ? 'Compte connecté. Tu peux te déconnecter à tout moment.'
          : 'Clique sur Connecter pour ouvrir le consentement Google.';
      }
    }

    const modelLabel = document.getElementById('modelLabel');
    if (modelLabel) modelLabel.textContent = 'api → ollama + google';
    if (!hasJarvis) showToast('JARVIS INDISPONIBLE');
  } catch {
    isApiReachable = false;
    isJarvisAvailable = false;
    mailConfigured = false;
    updateSendAvailability();
    updateAuthButtons();
    document.getElementById('statusDot').className   = 'status-dot offline';
    document.getElementById('statusLabel').textContent = 'API · hors ligne';
    const mailAuthState = document.getElementById('mailAuthState');
    const mailAuthHint = document.getElementById('mailAuthHint');
    if (mailAuthState) mailAuthState.textContent = 'API indisponible';
    if (mailAuthHint) mailAuthHint.textContent = '';
    showToast('API non accessible sur localhost:8001');
  }
}

// Connecte le compte Google en appelant l'API et met à jour l'interface et 
async function connectGoogle() {
  if (isAuthLoading) return;

  isAuthLoading = true;
  updateAuthButtons();
  showToast('Ouverture de la connexion Google...');

  try {
    const res = await fetch(`${API_URL}/api/google/connect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      const msg = data.detail || data.error || `HTTP ${res.status}`;
      throw new Error(msg);
    }

    addMessage('jarvis', data.message || 'Compte Google connecté.');
    showToast('Connexion Google réussie');
  } catch (err) {
    const message = (err && err.message) ? err.message : 'Impossible de connecter Google.';
    addMessage('jarvis', `Connexion Google impossible: ${message}`);
    showToast('Connexion Google échouée');
  } finally {
    isAuthLoading = false;
    await checkStatus();
    updateAuthButtons();
  }
}


// Déconnecte le compte Google en appelant l'API et met à jour l'interface
async function disconnectGoogle() {
  if (isAuthLoading) return;

  isAuthLoading = true;
  updateAuthButtons();
  showToast('Déconnexion Google en cours...');

  try {
    const res = await fetch(`${API_URL}/api/google/disconnect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      const msg = data.detail || data.error || `HTTP ${res.status}`;
      throw new Error(msg);
    }

    addMessage('jarvis', data.message || 'Compte Google déconnecté.');
    showToast('Google déconnecté');
  } catch (err) {
    const message = (err && err.message) ? err.message : 'Impossible de déconnecter Google.';
    addMessage('jarvis', `Déconnexion Google impossible: ${message}`);
    showToast('Déconnexion Google échouée');
  } finally {
    isAuthLoading = false;
    await checkStatus();
    updateAuthButtons();
  }
}

// ── On récupère l'intention ───────────────────────────────
function detectIntent(text) {
  const t = text.toLowerCase();
  if (t.startsWith('/')) {
    const command = t.split(/\s+/)[0].replace('/', '');
    return [command || 'slash', 'cmd'];
  }
  if (/email|mail|message|courrier/.test(t)) {
    if (/envo|écri|rédige/.test(t)) return ['send_email', '92%'];
    if (/répond/.test(t))            return ['reply_email', '89%'];
    return ['read_emails', '94%'];
  }
  if (/rdv|réunion|rendez|événement|calendrier|agenda|planif|crée|bloc/.test(t)) {
    if (/annule|supprime/.test(t)) return ['delete_event', '91%'];
    if (/modifie|décale|change/.test(t)) return ['update_event', '88%'];
    if (/conflit/.test(t))         return ['check_conflicts', '90%'];
    if (/planning|agenda|réunion.*semaine/.test(t)) return ['list_events', '93%'];
    return ['add_event', '87%'];
  }
  if (/libre|disponib/.test(t))       return ['check_availability', '95%'];
  if (/alarme|réveille|réveil/.test(t)) {
    if (/supprime|annule/.test(t)) return ['delete_alarm', '92%'];
    if (/modifie|décale/.test(t))  return ['update_alarm', '89%'];
    return ['set_alarm', '96%'];
  }
  if (/rappel|rappelle/.test(t)) return ['set_reminder', '91%'];
  if (/aide|help/.test(t))       return ['help', '99%'];
  return ['unknown', '—'];
}

// ── Envoyer le message ────────────────────────────────────────
async function sendMessage() {
  const input = document.getElementById('input');
  const text  = input.value.trim();
  if (!text || isLoading) return;

  const mailCommand = isMailCommand(text);
  const mailPhrase = isLikelyMailPhrase(text);

  if (!isJarvisAvailable) {
    document.getElementById('welcome')?.remove();
    input.value = '';
    input.style.height = 'auto';
    showJarvisUnavailable();
    input.focus();
    return;
  }

  if ((mailCommand || mailPhrase) && !mailConfigured) {
    document.getElementById('welcome')?.remove();
    addMessage('user', text);
    const provider = providerLabel(mailProvider);
    const missing = mailMissingKeys.length > 0 ? `\nVariables manquantes: ${mailMissingKeys.join(', ')}` : '';
    addMessage('jarvis', `${provider} non configuré.${missing}\nClique sur Connecter pour lancer l'authentification.`);
    return;
  }

  document.getElementById('welcome')?.remove();
  input.value = '';
  input.style.height = 'auto';

  addMessage('user', text);
  history.push({ role: 'user', content: text });

  const [intent, conf] = detectIntent(text);
  const intentBadgeEl = document.getElementById('intentBadge');
  const intentConfEl = document.getElementById('intentConf');
  if (intentBadgeEl) intentBadgeEl.textContent = intent;
  if (intentConfEl) intentConfEl.textContent = conf + ' confiance';

  addHistoryItem(text);

  isLoading = true;
  updateSendAvailability();

  const typingEl = addTyping();
  const t0 = Date.now();

  try {
    const res = await fetch(`${API_URL}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: text,
        history,
      }),
    });

    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }

    const data = await res.json();

    typingEl.remove();

    const reply = data.reply || 'Je n\'ai pas de réponse pour le moment.';
    addMessage('jarvis', reply);
    history.push({ role: 'assistant', content: reply });

    if (data.action) {
      const actionBadgeEl = document.getElementById('intentBadge');
      const actionConfEl = document.getElementById('intentConf');
      if (actionBadgeEl) actionBadgeEl.textContent = data.action;
      if (actionConfEl) actionConfEl.textContent = (data.source || 'api') + ' source';
    }

  } catch (err) {
    typingEl?.remove();
    addMessage('jarvis', 'Impossible de joindre l\'API Jarvis.\nVérifie qu\'elle tourne sur localhost:8001');
  }

  msgCount++;
  document.getElementById('msgCount').textContent = msgCount;
  isLoading = false;
  updateSendAvailability();
  input.focus();
}

function send(text) {
  document.getElementById('input').value = text;
  sendMessage();
}

// ── Ajouter un message ────────────────────────────────────────
function addMessage(role, text) {
  const messages = document.getElementById('messages');
  const row = document.createElement('div');
  row.className = `msg-row ${role}`;
  row.innerHTML = `
    <div class="avatar ${role === 'jarvis' ? 'jarvis' : 'user-av'}">${role === 'jarvis' ? 'J' : 'U'}</div>
    <div class="bubble ${role}">${text}</div>
  `;
  messages.appendChild(row);
  scrollBottom();
  return row;
}

// ── Ajouter l'animation de "JARVIS tape..." ───────────────────────────────
function addTyping() {
  const messages = document.getElementById('messages');
  const row = document.createElement('div');
  row.className = 'typing-row';
  row.innerHTML = `
    <div class="avatar jarvis">J</div>
    <div class="typing-bubble">
      <div class="dot"></div><div class="dot"></div><div class="dot"></div>
    </div>
  `;
  messages.appendChild(row);
  scrollBottom();
  return row;
}

// ── Ajouter un item à l'historique ───────────────────────────────────────
function addHistoryItem(text) {
  const list = document.getElementById('historyList');
  const item = document.createElement('div');
  item.className = 'history-item';
  item.textContent = text.length > 40 ? text.slice(0, 40) + '…' : text;
  item.onclick = () => send(text);
  list.insertBefore(item, list.firstChild);
  // Garder seulement les 8 derniers
  while (list.children.length > 8) list.removeChild(list.lastChild);
}

// ── Scroll vers le bas ───────────────────────────────────────
function scrollBottom() {
  const m = document.getElementById('messages');
  m.scrollTop = m.scrollHeight;
}

// ── Effacer la conversation ───────────────────────────────────────
function clearChat() {
  history = [];
  msgCount = 0;
  document.getElementById('messages').innerHTML = `
    <div class="welcome" id="welcome">
      <div class="big">JARVIS_</div>
      <div class="sub">Interface de test — utilise /help pour voir les commandes</div>
    </div>`;
  document.getElementById('msgCount').textContent = '0';
  const intentBadgeEl = document.getElementById('intentBadge');
  const intentConfEl = document.getElementById('intentConf');
  if (intentBadgeEl) intentBadgeEl.textContent = '—';
  if (intentConfEl) intentConfEl.textContent = '';
  document.getElementById('historyList').innerHTML = '';
  showToast('Conversation effacée');
}

// ── Afficher une notification ───────────────────────────────────────
function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3000);
}

// ── Gérer l'envoi avec la touche Entrée ───────────────────────────────────────
function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

// ── Auto-resize du textarea ───────────────────────────────────────
function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

// ── Initialisation ───────────────────────────────────────
updateSendAvailability();
updateAuthButtons();
checkStatus();
setInterval(checkStatus, 15000);

const inputEl = document.getElementById('input');
const sendBtnEl = document.getElementById('sendBtn');

if (inputEl) {
  inputEl.onkeydown = handleKey;
  inputEl.oninput = () => autoResize(inputEl);
  inputEl.focus();
}

if (sendBtnEl) {
  sendBtnEl.onclick = sendMessage;
}
