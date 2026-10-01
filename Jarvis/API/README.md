# Jarvis API - Documentation technique

## But du dossier

Ce dossier regroupe la logique serveur de Jarvis:

- l'API FastAPI, qui sert aussi le HUD
- le routage des intentions
- la persona (ton, dates en français, version orale des réponses)
- le client du modèle de langage (Ollama)
- la voix (synthèse et reconnaissance locales)
- la recherche sur le web (Jarvis cherche et répond lui-même)
- la logique métier des mails, du calendrier et des alarmes
- le pilotage du poste (diagnostic, applications, volume, web, veille)
- la météo, le briefing et le tableau de bord du HUD
- le client Google OAuth / Gmail / Calendar
- le stockage persistant des alarmes

## Parcours d'une demande

```text
HUD (voix ou clavier) ──► POST /api/chat/stream
                              │
                              ├─ 1. réponse à une confirmation en attente ? (« oui » / « non »)
                              ├─ 2. intention reconnue ? (intents.py) ──► module métier ──► Reply
                              ├─ 3. demande d'aide ? (commandes / capacités)
                              └─ 4. sinon : conversation ──► llm.py ──► Ollama (phrases en flux)
                                     └─ recherche web si nécessaire ──► web_search.py ──► réponse rédigée
```

Une recherche web est lancée dans deux cas : le routeur reconnaît une question d'information (« horaires », « prix », « qui a gagné », « cherche … »), ou le modèle décide lui-même d'appeler l'outil `recherche_web`. Dans les deux cas, Jarvis prévient, cherche, lit les pages, puis le modèle rédige la réponse à partir des résultats.

Chaque module métier renvoie un objet `Reply` :

- `text` : ce que le HUD affiche (listes, identifiants, liens)
- `speech` : ce que Jarvis prononce (court, sans identifiants ni symboles)
- `data` : données structurées pour le HUD
- `pending` : action en attente d'une confirmation (`{"action": ..., "params": ...}`)

Le modèle de langage ne déclenche jamais d'action : il ne sert qu'à converser, à rédiger les mails et à demander une recherche web. Les actions sont exécutées par le code, de façon déterministe.

## Routes HTTP

| Route | Méthode | Rôle |
|---|---|---|
| `/` | GET | sert le HUD (`Jarvis/Interface/`) |
| `/api/status` | GET | état global : modèle, voix, Google, persona |
| `/api/chat` | POST | demande → réponse complète (utilisée par Discord) |
| `/api/chat/stream` | POST | même chose en flux NDJSON, phrase par phrase (utilisée par le HUD) |
| `/api/tts` | POST | texte → voix de Jarvis (WAV) |
| `/api/stt` | POST | enregistrement du micro (WAV 16 bits) → texte + mot d'activation |
| `/api/system` | GET | relevé du poste : processeur, mémoire, disque, batterie, alertes |
| `/api/dashboard` | GET | météo, agenda du jour, messages non lus, alarmes |
| `/api/briefing` | GET | briefing prononcé par Jarvis (`kind=boot` ou `kind=full`) |
| `/api/warmup` | POST | garde le modèle en mémoire (appelé par le HUD toutes les 10 minutes) |
| `/api/events` | GET | événements proactifs (alarmes) depuis le dernier relevé |
| `/api/alarms` | GET | alarmes actives |
| `/api/commands` | GET | aide des commandes |
| `/api/google/connect` | POST | lance le flux OAuth Google |
| `/api/google/disconnect` | POST | révoque et supprime le token Google |

Corps de `/api/chat` et `/api/chat/stream` :

```json
{
  "message": "Envoie un mail à Paul pour lui dire que je serai en retard",
  "history": [{"role": "user", "content": "..."}],
  "pending": null,
  "client": "hud"
}
```

Réponse (`/api/chat`, ou événement `final` du flux) :

```json
{
  "reply": "J'ai préparé ce message pour Paul, Monsieur : ...",
  "speech": "J'ai préparé le message pour Paul, Monsieur. ... Dois-je l'envoyer ?",
  "action": "send_mail",
  "source": "google",
  "pending": {"action": "send_mail", "params": {"to_email": "...", "subject": "...", "body": "..."}},
  "data": null
}
```

Le client renvoie `pending` tel quel avec le message suivant : « oui » exécute l'action, « non » l'annule, toute autre phrase l'abandonne.

Événements du flux : `{"type": "start"}`, puis `{"type": "sentence", "text": "..."}` pour chaque phrase du modèle, puis `{"type": "final", ...}`. Une action reconnue ne produit qu'un événement `final`. Pendant une recherche web, un événement `{"type": "status", "label": "Recherche web"}` précède les phrases, et l'événement `final` porte les pages consultées dans `data.sources`.

## Vue d'ensemble des fichiers

### `main.py`
- **Role**: point d'entrée de l'API FastAPI.
- **Responsabilite**: expose les routes, gère les confirmations, applique les règles de sécurité, délègue aux modules.

| Élément | Rôle |
|---|---|
| `HistoryMessage`, `ChatRequest`, `ChatResponse`, `SpeakRequest` | modèles des requêtes et réponses |
| `lifespan(app)` | démarre le scheduler d'alarmes, précharge le modèle et la voix ; à l'arrêt, supprime le token Google (sauf `GOOGLE_FORGET_TOKEN_ON_EXIT=0`) |
| `run_action(action_payload)` | redirige une action vers le bon module et renvoie un `Reply` |
| `_execute(action_payload)` | exécute l'action et traduit les erreurs Google dans le ton de Jarvis |
| `resolve(request)` | traite tout ce qui ne demande pas le modèle : confirmation, action, aide, mode strict, modèle hors ligne ; sinon renvoie un plan (conversation, avec ou sans recherche web) |
| `converse(request, plan)` | fait répondre le modèle ; lance la recherche web si le plan le demande ou si le modèle appelle l'outil, puis lui fait rédiger la réponse à partir des résultats |
| `_guarded(request, action_payload)` | exécute une action, sauf si elle pilote le poste et vient d'un client distant |
| `HudFiles` | sert le HUD avec `Cache-Control: no-cache` : une mise à jour est visible au premier rechargement |
| `is_remote_request(headers)` | vrai si la requête ne vient pas directement du Mac (autre nom d'hôte, ou en-têtes de relais) |
| `RemoteAccessGuard` | exige le code d'accès des autres appareils sur `/api/*` ; le HUD lui-même reste servi |
| `classify_support_request(text)` | détecte « aide » / « commandes » et « que peux-tu faire » |
| `_chat_events(request)` | produit le flux NDJSON de `/api/chat/stream` |
| `_allowed_hosts()` | noms d'hôte acceptés par l'API |

Règles appliquées:

- un appel à l'API venu d'un autre appareil (autre nom d'hôte, ou requête relayée par Tailscale) doit présenter le code d'accès `X-Jarvis-Token` (`RemoteAccessGuard`) ; sans `JARVIS_ACCESS_TOKEN`, l'accès à distance est refusé
- les actions Google sont refusées poliment tant que le compte n'est pas relié (aucun brouillon n'est rédigé pour rien)
- les actions de pilotage du poste (`SYSTEM_CONTROL_ACTIONS`) sont refusées aux clients distants (`client: "discord"`) sauf `JARVIS_REMOTE_SYSTEM_CONTROL=1`
- `JARVIS_CONFIRM_ACTIONS=0` désactive les confirmations
- `JARVIS_STRICT_ACTIONS_ONLY=1` refuse toute demande qui n'est pas une action
- `JARVIS_WEB_SEARCH=0` coupe la recherche web : l'outil n'est plus proposé au modèle et « cherche … » ouvre le navigateur
- si la recherche échoue, Jarvis propose d'ouvrir le navigateur (confirmation par « oui ») ; jamais pour un client distant
- si le modèle est hors ligne, les modules (agenda, mail, alarmes, poste) restent disponibles
- CORS limité à `localhost` (+ `JARVIS_ALLOWED_ORIGINS`) et en-tête `Host` vérifié

### `config.py`
- **Role**: configuration centralisée.
- **Responsabilite**: charge le `.env` avant toute lecture de variable, expose les réglages (`USER_TITLE`, `CITY`, `OLLAMA_MODEL`, `TTS_ENGINE`, `STT_ENGINE`, `HOST`, `PORT`, `ALARM_*`…).

| Fonction | Rôle |
|---|---|
| `env_str`, `env_flag`, `env_int`, `env_float`, `env_list` | lecture typée et bornée d'une variable d'environnement |
| `ACCESS_TOKEN` | code exigé des autres appareils (`JARVIS_ACCESS_TOKEN`) |
| `load_contacts()` | carnet d'adresses `contacts.json` (nom → email) |

Tous les modules lisent leur configuration ici : lire `os.getenv` à l'import d'un autre module ferait ignorer le `.env`.

### `persona.py`
- **Role**: le caractère de Jarvis.
- **Responsabilite**: formule d'appel, tournures, dates et heures en français, version orale des textes.

| Élément | Rôle |
|---|---|
| `Reply` | réponse d'un module (`text`, `speech`, `data`, `pending`) ; `spoken` donne le texte à prononcer |
| `ack()` | accusé de réception (« Bien, Monsieur. », « Tout de suite, Monsieur. »…) |
| `greeting(now)` | « Bonjour » ou « Bonsoir » selon l'heure |
| `format_time`, `spoken_time` | « 7 h 30 » pour l'écran, « 7 heures 30 » / « midi » pour la voix |
| `format_date`, `day_label`, `format_when`, `spoken_when`, `period_label` | « mardi 30 septembre », « demain à 7 h 30 », « entre le … et le … » |
| `to_speech(text)` | retire identifiants, liens et markdown d'un texte affiché |
| `strip_vocative(text)` | retire « Jarvis, … » d'une phrase |
| `smalltalk_reply(text)` | réponses immédiates aux petites phrases (« tu es là ? » → « Pour vous, Monsieur, toujours. ») |
| `fold(text)`, `strip_accents(text)` | normalisation pour les détections |

### `intents.py`
- **Role**: détection des intentions et parsing des commandes slash ou phrases naturelles.
- **Responsabilite**: transforme du texte libre en dictionnaires d'actions structurées.

| Fonction | Rôle |
|---|---|
| `detect_action(text, fallback_email=None)` | entrée principale : essaie chaque parseur et renvoie une action, ou `None` (conversation) |
| `classify_confirmation(text)` | interprète « oui » / « non » après une demande de confirmation |
| `_parse_command(text)` | commandes slash (`/sendmail`, `/addevent`, `/status`, `/open`, `/volume`…) |
| `_parse_natural_send_mail(text, fallback_email)` | envoi de mail : adresse, contact du carnet, objet, message ; demande une précision s'il manque un élément |
| `_parse_natural_timer(text)` | minuteurs (« minuteur de 10 minutes », « annule le minuteur ») |
| `_parse_natural_reminder(text)` | rappels (« rappelle-moi à 15h d'appeler Paul ») |
| `_parse_natural_alarm(text)` | alarmes et réveils : création, liste, suppression |
| `_parse_natural_calendar(text)` | calendrier : création, liste, disponibilités, suppression |
| `_parse_mail_reading(text)` | lecture de la messagerie (résumé, dernier mail) |
| `_parse_info(text)` | heure, date, météo, briefing |
| `_parse_web_question(text)` | questions à chercher sur le web : « cherche … », horaires, prix, actualité, résultats, commerces de proximité (sauf ses propres données : « mes mails », « mon agenda ») |
| `_parse_system(text)` | diagnostic, volume, veille, recherche à ouvrir dans le navigateur, ouverture/fermeture d'applications et de sites |

Aides de parsing:

| Fonction | Rôle |
|---|---|
| `_parse_datetime_expression(text)` | date/heure naturelle (« demain à 7h30 », « lundi prochain », « dans une demi-heure », « ce soir ») |
| `_normalize_spoken_time(text)` | heures dictées → `7h30` (« 7 heures et demie », « midi », « 9 heures moins le quart ») |
| `_extract_relative_delay(text)` | durée (« 10 minutes », « 1h30 », « un quart d'heure ») |
| `_extract_day_period_bounds(text)` | plage de dates (jour, période, semaine) |
| `_strip_time_expressions(text)` | retire les indications de temps pour isoler un titre |
| `_extract_alarm_title`, `_event_title` | titre d'une alarme ou d'un événement (« Réunion avec Sophie ») |
| `_extract_mail_subject`, `_extract_mail_body` | objet et corps d'un mail |
| `_find_contact(text)` | retrouve un contact du carnet d'adresses `contacts.json` (nom → email) |
| `_normalize_spoken_email(text)` | adresse dictée (« paul arobase exemple point com ») |
| `_extract_city(text)` | ville d'une demande météo |

Les demandes en langage naturel qui envoient un mail ou suppriment en masse portent `confirm: True` : le module présente l'action et attend un « oui ». Les commandes slash s'exécutent directement.

### `llm.py`
- **Role**: client Ollama.
- **Responsabilite**: état du modèle, conversation, outil de recherche, garde-fous de la persona.

| Fonction | Rôle |
|---|---|
| `load_system_prompt()` | charge `system_prompt.txt` et y inscrit la formule d'appel |
| `ollama_status()` | vérifie qu'Ollama répond et que le modèle existe |
| `build_messages(history, message, context)` | prompt système + contexte en direct + historique récent |
| `chat_stream(history, message, temperature, context, tools=None)` | réponse phrase par phrase, pour parler sans attendre la fin ; se termine par un `ToolCall` si le modèle appelle un outil |
| `supports_tools()` | indique si le modèle sait appeler des outils (sinon, seul le routeur déclenche les recherches) |
| `search_query(history, message, context)` | fait formuler par le modèle la requête d'une recherche déjà décidée (ajoute la ville pour un service de proximité) |
| `WEB_TOOL`, `TOOLS_HINT`, `WEB_ANSWER_RULES` | définition de l'outil `recherche_web` et consignes : quand chercher, comment répondre à partir des résultats |
| `split_sentences(buffer)` | découpe le flux en phrases complètes (sans couper « J.A.R.V.I.S. » ou « M. ») |
| `first_clause(buffer)` | pour parler plus tôt, dit une longue première phrase en deux temps, à partir d'une virgule |
| `keep_warm()` | charge le modèle en mémoire, ou l'y maintient, sans rien générer |
| `claims_unexecuted_action(user_message, reply)` | détecte un modèle qui prétend avoir exécuté une action |
| `complete(system, prompt, ...)` | génération ponctuelle (objet et corps des mails) |
| `warm_up()` | charge le modèle en mémoire au démarrage |

Si le modèle affirme « j'ai envoyé… » alors qu'aucun module n'a rien exécuté, sa réponse est remplacée par une demande de reformulation.

### `web_search.py`
- **Role**: recherche sur le web, sans clé d'API.
- **Responsabilite**: interroger le moteur (DuckDuckGo), lire les premières pages, en extraire les passages utiles.

| Fonction | Rôle |
|---|---|
| `search(query)` | interroge le moteur et renvoie les premiers résultats (titre, adresse, extrait) |
| `parse_results(page)` | lit la page de résultats ; écarte les publicités et sort l'adresse réelle des redirections |
| `fetch_page(url)` | télécharge une page publique : taille bornée, redirections suivies à la main et revalidées |
| `is_public_url(url)` | refuse le réseau local, les adresses internes et tout ce qui n'est pas http(s) |
| `extract_passages(page, query)` | garde le texte visible, puis les lignes en rapport avec la question et leur voisinage (une ligne de tableau reste sur une ligne : « Lundi 09:00 à 21:00 ») |
| `gather(query)` | recherche + lecture en parallèle des trois premières pages, avec délai global et cache de 5 min |
| `format_for_model(query, results)` | met les résultats en forme pour le modèle |
| `sources(results)` | pages affichées en liens dans le HUD |
| `clean_query(text)` | « cherche … sur internet » → requête |

Le texte des pages est un contenu non fiable : il est passé au modèle comme une donnée, avec la consigne de n'obéir à aucune instruction qu'il contiendrait, et le modèle ne peut de toute façon déclencher aucune action.

### `phone_setup.py`
- **Role**: préparer l'accès depuis le téléphone (appelé par `./run_jarvis.sh phone`).

| Fonction | Rôle |
|---|---|
| `ensure_phone_settings(dns_name, env_file)` | crée le code d'accès s'il manque et autorise l'adresse Tailscale dans `.env` ; renvoie le code |
| `show_qr(link)` | affiche le lien d'appairage en QR code (terminal et écran) |

### `voice.py`
- **Role**: la voix de Jarvis, en local.
- **Responsabilite**: synthèse vocale, reconnaissance vocale, mot d'activation.

| Élément | Rôle |
|---|---|
| `PiperEngine` | voix neuronale Piper (`Jarvis/API/voices/<voix>.onnx`) |
| `SayEngine` | voix système de macOS ; choisit la meilleure voix française installée |
| `MlxWhisperEngine` | reconnaissance sur la puce graphique des Mac Apple Silicon (mlx-whisper, large-v3-turbo par défaut : environ 0,35 s par phrase) |
| `WhisperEngine` | reconnaissance avec faster-whisper sur le processeur (small par défaut : environ 1 s) ; décode le WAV, filtre le silence et les hallucinations |
| `tts_engine()`, `stt_engine()` | moteur actif selon `JARVIS_TTS_ENGINE` / `JARVIS_STT_ENGINE` |
| `tts_status()`, `stt_status()` | état pour `/api/status` |
| `prepare_tts_text(text)` | adapte un texte à la voix (« 7 h 30 » → « 7 heures 30 », « °C » → « degrés ») |
| `synthesize(text)` | texte → WAV (avec un petit cache) |
| `speak_local(text)` | fait parler Jarvis sur les haut-parleurs du poste, sans HUD |
| `extract_command(text)` | repère « Jarvis » (et ses graphies proches) et isole l'ordre |
| `stt_vocabulary()` | noms propres fournis à Whisper : prénom d'activation, ville, `JARVIS_STT_VOCABULARY`, contacts |
| `transcribe(data)` | WAV → `{text, wake, command}` |
| `prepare_stt()` | télécharge et charge le modèle de reconnaissance (utilisé par `./run_jarvis.sh setup`) |
| `preload()` | charge les modèles vocaux au démarrage |

En mode `auto` : Piper, sinon `say` (macOS), sinon le HUD utilise la voix du navigateur ; Whisper, sinon la reconnaissance du navigateur.

### `briefing.py`
- **Role**: vue d'ensemble de la journée.
- **Responsabilite**: tableau de bord du HUD, briefing, contexte en direct pour la conversation.

| Élément | Rôle |
|---|---|
| `Dashboard` | rassemble météo, agenda du jour, messages non lus et alarmes (cache de 90 s pour Google) |
| `build_briefing(dashboard, kind)` | « Bonjour, Monsieur. Il est… » : version courte (`boot`) ou complète (`full`) |
| `live_context(dashboard, message)` | contexte transmis au modèle : date, heure et ville, plus agenda / météo / messagerie / état du poste si la question s'y rapporte |

### `system_actions.py`
- **Role**: capteurs et pilotage du poste.
- **Responsabilite**: diagnostic, applications, volume, web, veille, heure et date.

| Fonction | Rôle |
|---|---|
| `read_system_metrics()` | processeur, mémoire, disque, batterie, durée de service (via `psutil`) |
| `system_alerts(metrics)` | points d'attention (batterie faible, mémoire ou disque saturés) |
| `handle_system_status(params)` | rapport de diagnostic (`focus: "battery"` pour la batterie seule) |
| `handle_time(timezone)`, `handle_date(timezone)` | heure et date |
| `resolve_app(raw)` | « la calculette » → application à lancer, avec validation du nom |
| `handle_open_app`, `handle_quit_app` | ouvre / ferme une application |
| `handle_open_url`, `handle_web_search` | ouvre un site ou une recherche (web, Google, YouTube, Wikipédia) |
| `handle_volume(params)` | volume : `get`, `set`, `up`, `down`, `mute`, `unmute` |
| `handle_sleep_display()` | met l'écran en veille |

Toutes les commandes système passent par `_run()` avec une liste d'arguments, jamais par un shell.

### `weather.py`
- **Role**: météo via Open-Meteo (gratuit, sans clé).

| Fonction | Rôle |
|---|---|
| `get_weather(city=None)` | conditions actuelles + prévisions d'aujourd'hui et de demain (cache de 10 min) |
| `handle_weather(params)` | réponse météo (`city`, `day: "tomorrow"`) avec conseil de parapluie |
| `summarize_now(weather)` | phrase affichée et phrase prononcée |

### `events.py`
- **Role**: file d'événements proactifs.

| Fonction | Rôle |
|---|---|
| `publish(kind, **payload)` | publie un événement (une alarme qui sonne) |
| `events_after(after_id)` | événements à relever par le HUD |
| `hud_is_listening()` | vrai si un HUD relève les événements : c'est alors lui qui prend la parole |

### `mail_actions.py`
- **Role**: logique métier des emails.
- **Responsabilite**: formatage des mails, génération assistée par le modèle, envoi.

| Fonction | Rôle |
|---|---|
| `extract_recent_email_from_history(history)` | dernière adresse vue dans la conversation |
| `format_mail_resume(items)` | résumé des non lus (liste affichée + phrase prononcée) |
| `format_last_mail(item)` | dernier email reçu |
| `generate_email_subject(draft_context, body_hint)` | objet très court (1-2 mots), filtré s'il sort du contexte |
| `generate_email_body(subject, draft_context, body_hint, polish_only)` | rédige ou améliore le corps |
| `fallback_email_subject`, `fallback_email_body` | secours si le modèle ne répond pas |
| `handle_send_mail(mail_client, params)` | prépare le message ; avec `confirm`, le présente et attend un « oui » ; sinon l'envoie |

Règles appliquées au flux d'envoi:

- le message est obligatoire : s'il manque, Jarvis le demande et n'envoie rien
- l'objet auto-généré est limité à 1-2 mots
- en mode amélioration, si le modèle recopie le brouillon, un corps formaté de secours est utilisé
- les contenus offensants sont bloqués, y compris les contournements par espaces/ponctuation (`z i z i`)
- le message envoyé après confirmation est exactement celui qui a été présenté

### `calendar_actions.py`
- **Role**: logique métier du calendrier.

| Fonction | Rôle |
|---|---|
| `format_week_events(events, now)` | événements de la semaine |
| `compute_availability(events, timezone)` | créneaux libres du lundi au vendredi, 9 h-18 h |
| `handle_events_week`, `handle_events_range` | liste sur la semaine, un jour ou une période |
| `handle_availability_week` | disponibilités |
| `handle_add_event(mail_client, params)` | crée un événement et signale un chevauchement éventuel |
| `handle_delete_event`, `handle_delete_events_range` | suppression par id ou par plage (avec confirmation si `confirm`) |

### `alarm_actions.py`
- **Role**: logique métier des alarmes, minuteurs et rappels.

| Fonction | Rôle |
|---|---|
| `alarm_scheduler_loop(alarms)` | boucle de fond : détecte les alarmes échues, publie l'événement, notifie et sonne |
| `alarm_announcement(label, now)` | phrase prononcée (« Monsieur, il est 7 heures 30. ») |
| `trigger_local_alarm(label, when, speak)` | notification + carillon + annonce vocale si aucun HUD n'est ouvert |
| `handle_set_alarm(alarms, timezone, params)` | crée une alarme, un minuteur (`kind: "timer"`) ou un rappel (`kind: "reminder"`) |
| `handle_list_alarms`, `handle_delete_alarm`, `handle_delete_alarms_range` | liste et suppressions |
| `handle_delete_timers(alarms)` | arrête les minuteurs |
| `handle_delete_alarms_all(alarms, params)` | supprime tout (avec confirmation si `confirm`) |

### `alarms.py`
- **Role**: stockage persistant des alarmes en JSON.

| Méthode de `AlarmStore` | Rôle |
|---|---|
| `from_env(timezone_name)` | fabrique le store (`ALARMS_FILE`) |
| `create_alarm(when, label)` | crée et persiste une alarme |
| `list_alarms(include_triggered=False)` | liste les alarmes |
| `delete_alarm(alarm_id)` | supprime par id ou préfixe |
| `delete_alarms_in_range(start, end)` | supprime sur une plage |
| `delete_alarms_with_label_prefix(prefix)` | supprime par titre (les minuteurs) |
| `delete_all_alarms(include_triggered=True)` | supprime tout |
| `trigger_due_alarms()` | marque et retourne les alarmes arrivées à l'heure |

### `google_client.py`
- **Role**: client OAuth unique pour Gmail et Google Calendar.
- **Responsabilite**: authentification, rafraîchissement du token, appels API Google.

| Méthode de `GoogleClient` | Rôle |
|---|---|
| `from_env()` | fabrique le client depuis l'environnement |
| `is_configured()`, `missing_keys()`, `status()` | état de la configuration |
| `setup_oauth_token()` | lance le flux OAuth et enregistre le token |
| `disconnect(revoke=True)` | révoque et supprime le token local |
| `get_unread_emails(limit=5)`, `get_latest_email()` | lecture de la boîte de réception |
| `send_mail(to_email, subject, body)` | envoi via Gmail |
| `list_week_events()`, `list_events_in_range(start, end)` | lecture du calendrier |
| `create_event(subject, start, end)` | création d'un événement |
| `delete_event(event_id)`, `delete_events_in_range(start, end)` | suppressions |

Exceptions : `GoogleConfigError` (configuration), `GoogleApiError` (erreur à l'exécution).

### `google_auth_setup.py`
- **Role**: point d'entrée simple pour créer le token OAuth Google en ligne de commande.

## Dépendances entre fichiers

| Fichier | Dépendance principale |
|---|---|
| `main.py` | tous les modules ci-dessous |
| `config.py` | aucun (chargé en premier) |
| `persona.py` | `config.py` |
| `intents.py` | `persona.py`, `config.py` |
| `llm.py` | `persona.py`, `config.py` |
| `web_search.py` | `persona.py`, `config.py` |
| `voice.py` | `persona.py`, `config.py` |
| `briefing.py` | `weather.py`, `system_actions.py`, `persona.py` |
| `system_actions.py`, `weather.py` | `persona.py` |
| `mail_actions.py` | `llm.py`, `persona.py`, `GoogleClient` passé en paramètre |
| `calendar_actions.py` | `persona.py`, `GoogleClient` passé en paramètre |
| `alarm_actions.py` | `events.py`, `voice.py`, `AlarmStore` passé en paramètre |
| `alarms.py`, `events.py` | indépendants |
| `google_client.py` | client central pour Gmail + Calendar |
