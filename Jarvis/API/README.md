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

## Organisation : routes, Jarvis, contrôleurs, agents, services

```text
API/
├── main.py         assemble tout : services → agents → contrôleurs → Jarvis → routes
├── routes/         reçoivent les requêtes HTTP et les passent à Jarvis (aucune logique métier)
├── core/           Jarvis, le chef : comprend, choisit le contrôleur, applique les règles
├── controllers/    les chefs d'équipe : chacun répartit le travail entre les agents de son domaine
├── agents/         les spécialistes : chacun déclare ses actions et les exécute
└── services/       les outils techniques des agents (Google, Ollama, voix, météo, web, stockage)
```

Les dépendances ne vont que vers le bas : une route appelle Jarvis, Jarvis appelle un contrôleur, le contrôleur appelle l'agent, l'agent utilise les services. Un service ne connaît aucun agent, un agent ne connaît ni HTTP, ni Jarvis, ni son contrôleur.

| Contrôleur | Agent | Fichier | Actions |
|---|---|---|---|
| organisation | messagerie | `agents/mail.py` | `mail_resume` (non lus triés par le modèle), `mail_last`, `send_mail`, `search_mail`, `read_mail`, `reply_mail`, `archive_mail`, `trash_mail` |
| organisation | agenda | `agents/calendar.py` | `events_week`, `events_range`, `availability_week`, `add_event` (récurrent avec une règle RRULE), `move_event`, `delete_event`, `delete_events_range` ; son veilleur (`agents/heads_up.py`) prévient avant chaque rendez-vous, trajet compris |
| organisation | alarmes | `agents/alarms.py` | `set_alarm` (récurrente avec `repeat`), `snooze_alarm`, `list_alarms`, `delete_alarm`, `delete_alarms_range`, `delete_alarms_all`, `delete_timers` |
| organisation | notes | `agents/notes.py` | `add_note` (app Notes), `add_to_list`, `read_list` (app Rappels) |
| organisation | trajets | `agents/travel.py` | `travel_time` (Nominatim + routage OpenStreetMap, voiture, vélo, pied) |
| ordinateur | poste | `agents/system.py` | `system_status`, `open_app`, `quit_app`, `open_url`, `volume`, `sleep_display`, `brightness`, `dark_mode`, `lock_screen`, `screenshot`, `wifi`, `bluetooth`, `do_not_disturb` |
| ordinateur | informations | `agents/info.py` | `time`, `date`, `weather` (7 jours, ou heure par heure : `day="hours"`, `period` = matin, après-midi, soir, nuit), `sun`, `air_quality`, `briefing` |
| ordinateur | musique | `agents/music.py` | `music` (`play`, `pause`, `next`, `previous`, `current`, `play_query`) |
| ordinateur | fichiers | `agents/files.py` | `find_file` (Spotlight), `open_file`, `summarize_file` (texte, Word, PDF via PDFKit) |
| savoir | web | `agents/web.py` | `web_search` (navigateur), `summarize_url` ; lit les pages pour l'agent de conversation |
| savoir | conversation | `agents/conversation.py` | aucune : reçoit tout ce qu'aucun autre agent n'a pris |
| savoir | mémoire | `agents/memory.py` | `remember`, `recall`, `forget` ; ses faits sont donnés au modèle pendant la conversation |
| savoir | traduction | `agents/translate.py` | `translate` |
| savoir | vision | `agents/vision.py` | `look_screen` (capture + modèle qui voit les images), `look_image` (une image du Mac, retrouvée par son nom) |
| création | code | `agents/code.py` | `write_code`, `code_tests` (tests du dernier programme, lancés en bac à sable), `fix_code` (version corrigée enregistrée à part), `explain_code` |
| création | design | `agents/design.py` | `design_page`, `design_logo` (avec favicon et icônes d'app), `design_palette` ; `count` = plusieurs propositions |
| création | documents | `agents/document.py` | `write_document` (HTML converti en .docx par `textutil`, ou en PDF : `format="pdf"`) |
| création | atelier | `agents/atelier.py` | `revise_creation`, `open_creation`, `list_creations`, `previous_version`, `choose_creation` (« la deuxième »), `export_pdf`, `make_icons` |
| routines | routines | `agents/routines.py` | `run_routine`, `list_routines`, `create_routine`, `schedule_routine` (à heure fixe), `unschedule_routine` |
| maison | maison | `agents/home.py` | `run_shortcut`, `list_shortcuts` (app Raccourcis, donc HomeKit) |

Jarvis répond lui-même aux politesses, à l'aide, aux erreurs de commande et à `/incompris`.

**Routage de secours** (`core/fallback.py`) : une phrase qui ressemble à un ordre mais qu'aucun parseur ne reconnaît est soumise au modèle, qui choisit dans une liste fermée d'actions sans risque (rien qui envoie, supprime ou demande une date). La phrase est notée dans `JARVIS_MISSES_FILE` avec le choix du modèle, pour être apprise au routeur et ajoutée à l'examen.

**Phrases** : chaque agent a son fichier de phrases dans `core/intents/` (`mail.py`, `calendar.py`, `alarms.py`…) ; `core/intents/__init__.py` (`detect_action`) les essaie dans un ordre fixe (le premier qui reconnaît la phrase l'emporte). `common.py` rassemble ce qu'ils partagent : dates et heures dites, durées, récurrences, nombres en lettres (« à sept heures trente »), et `commands.py` les commandes slash. Les heures se calculent dans le fuseau de l'utilisateur (`GOOGLE_TIMEZONE`, via `config.local_now()`), pas dans celui du poste.

**Contrôles avant livraison des créations** : l'agent code lance chaque script Python dans un bac à sable macOS (`sandbox-exec` : sans réseau, écriture limitée à un dossier temporaire qui sert de dossier personnel), et les tests qu'il écrit y tournent avec le programme ; l'agent design photographie son rendu avec Quick Look et le fait relire par le modèle, qui voit les images, puis corrige les défauts graves une fois.

**Modèle des créations** : `JARVIS_CREATION_MODEL` donne aux agents code, design et documents un modèle à part (plus gros, par exemple). Ollama le fait tourner en même temps que celui de la conversation : Jarvis ne fait plus attendre la conversation derrière une création. `./run_jarvis.sh tune` règle aussi Ollama pour deux demandes à la fois avec un seul modèle.

## Parcours d'une demande

```text
HUD (voix ou clavier) ──► routes/chat.py ──► Jarvis.stream (core/jarvis.py)
                              │
                              ├─ 1. réponse à une confirmation en attente ? (« oui » / « non »)
                              ├─ 2. intention reconnue ? (core/intents/) ──► contrôleur ──► agent ──► Reply
                              ├─ 3. demande d'aide ? (commandes / capacités)
                              └─ 4. sinon : savoir › conversation ──► services/llm.py ──► Ollama (phrases en flux)
                                     └─ recherche web si nécessaire ──► agent web ──► réponse rédigée
```

Le journal du serveur indique pour chaque demande le contrôleur et l'agent qui l'ont traitée et sa durée, et pour la conversation le délai avant la première phrase :

```text
[JARVIS] organisation › alarmes › set_alarm (0 ms)
[JARVIS] savoir › conversation › 1re phrase 263 ms, réponse 264 ms
```

Une recherche web est lancée dans deux cas : le routeur reconnaît une question d'information (« horaires », « prix », « qui a gagné », « cherche … »), ou le modèle décide lui-même d'appeler l'outil `recherche_web`. Dans les deux cas, Jarvis prévient, cherche, lit les pages, puis le modèle rédige la réponse à partir des résultats.

Chaque agent renvoie un objet `Reply` :

- `text` : ce que le HUD affiche (listes, identifiants, liens)
- `speech` : ce que Jarvis prononce (court, sans identifiants ni symboles)
- `data` : données structurées pour le HUD
- `pending` : action en attente d'une confirmation (`{"action": ..., "params": ...}`)

Le modèle de langage ne déclenche jamais d'action : il ne sert qu'à converser, à rédiger les mails et à demander une recherche web. Les actions sont exécutées par le code, de façon déterministe.

## Routes HTTP

| Route | Méthode | Rôle |
|---|---|---|
| `/` | GET | sert le HUD (`Jarvis/Interface/`) |
| `/api/status` | GET | état global : modèle, voix, Google, persona, contrôleurs, leurs agents et leurs actions |
| `/api/chat` | POST | demande → réponse complète (utilisée par Discord) |
| `/api/chat/stream` | POST | même chose en flux NDJSON, phrase par phrase (utilisée par le HUD) |
| `/api/tts` | POST | texte → voix de Jarvis (WAV) |
| `/api/stt` | POST | enregistrement du micro (WAV 16 bits) → texte + mot d'activation |
| `/api/system` | GET | relevé du poste : processeur, mémoire, disque, batterie, alertes |
| `/api/dashboard` | GET | météo, agenda du jour, messages non lus, alarmes |
| `/api/briefing` | GET | briefing prononcé par Jarvis (`kind=boot` ou `kind=full`) |
| `/api/warmup` | POST | garde le modèle en mémoire (appelé par le HUD toutes les 10 minutes) |
| `/api/events` | GET | événements proactifs (alarmes, créations prêtes, rappels de rendez-vous et routines : `notice`) depuis le dernier relevé |
| `/api/creations` | GET | dernières créations de l'atelier, avec leur adresse |
| `/api/creations/{chemin}` | GET | le fichier d'une création (page, logo, PDF, code en texte) ; rien en dehors du dossier des créations |
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
- **Role**: point d'entrée, le seul endroit où les pièces sont assemblées.
- **Responsabilite**: crée les services partagés (`Context`), les contrôleurs (qui créent leurs agents), Jarvis, puis l'application FastAPI et ses routes.

| Élément | Rôle |
|---|---|
| `context` | ressources partagées : client Google, alarmes, tableau de bord |
| `jarvis` | le chef, avec ses trois contrôleurs |
| `lifespan(app)` | démarre les agents (planificateur d'alarmes), précharge le modèle et la voix ; à l'arrêt, supprime le token Google (sauf `GOOGLE_FORGET_TOKEN_ON_EXIT=0`) |
| `serve()` | démarre le serveur (ou reprend le port surveillé par le service macOS) |

### `core/jarvis.py`
- **Role**: le chef d'orchestre.
- **Responsabilite**: comprend la demande, choisit l'agent, applique les règles communes, confie la conversation au modèle.

| Élément | Rôle |
|---|---|
| `Jarvis.dispatch`, `Jarvis.routes` | tables de routage action → contrôleur et action → agent, construites à partir des contrôleurs (une action n'appartient qu'à un contrôleur et un agent) |
| `resolve(request)` | traite tout ce qui ne demande pas le modèle : confirmation, action, aide, mode strict, modèle hors ligne ; sinon renvoie un plan (conversation, avec ou sans recherche web) |
| `run(action_payload)` | confie l'action au contrôleur du domaine (ou y répond lui-même : politesses, aide) |
| `execute(action_payload)` | exécute et traduit les erreurs Google dans le ton de Jarvis |
| `allows(action, request)` / `guarded(...)` | refuse le pilotage du poste aux clients distants |
| `stream(request)` | réponse en événements (phrases une à une, puis `final`) |
| `answer(request)` | réponse d'un bloc (Discord), sources ajoutées au texte |
| `classify_support_request(text)` | détecte « aide » / « commandes » et « que peux-tu faire » |

Règles appliquées:

- un appel à l'API venu d'un autre appareil (autre nom d'hôte, ou requête relayée par Tailscale) doit présenter le code d'accès `X-Jarvis-Token` (`routes/security.py`) ; sans `JARVIS_ACCESS_TOKEN`, l'accès à distance est refusé
- les actions d'un agent `needs_google` sont refusées poliment tant que le compte n'est pas relié (aucun brouillon n'est rédigé pour rien)
- les actions `local_only` d'un agent (pilotage du poste) sont refusées aux clients distants (`client: "discord"`) sauf `JARVIS_REMOTE_SYSTEM_CONTROL=1`
- les actions `confirmable` attendent un « oui » ; `JARVIS_CONFIRM_ACTIONS=0` désactive les confirmations
- après une action `writes` (mail envoyé, agenda modifié), le tableau de bord est relu
- `JARVIS_STRICT_ACTIONS_ONLY=1` refuse toute demande qui n'est pas une action
- `JARVIS_WEB_SEARCH=0` coupe la recherche web : l'outil n'est plus proposé au modèle et « cherche … » ouvre le navigateur
- si la recherche échoue, Jarvis propose d'ouvrir le navigateur (confirmation par « oui ») ; jamais pour un client distant
- si le modèle est hors ligne, les agents (agenda, mail, alarmes, poste) restent disponibles

### `core/agent.py`
- **Role**: le contrat commun des agents.

| Élément | Rôle |
|---|---|
| `Context` | ressources partagées, lues au moment d'agir (remplacer le client Google ici le remplace partout) |
| `Agent.handlers()` | associe chaque action de l'agent à sa fonction |
| `needs_google`, `writes`, `confirmable`, `local_only` | règles déclarées par l'agent, appliquées par Jarvis |
| `Agent.start()` | tâches de fond (le planificateur d'alarmes) |

Le test `tests/test_architecture.py` vérifie que chaque action reconnue a bien un contrôleur et un agent.

### `core/controller.py` et `controllers/`
- **Role**: les chefs d'équipe, entre Jarvis et les agents.

| Élément | Rôle |
|---|---|
| `Controller(agents)` | répartit les actions entre les agents de l'équipe (une action n'appartient qu'à un agent) |
| `run(action, params)` | passe l'action à l'agent compétent et journalise « contrôleur › agent › action (durée) » |
| `start()` | démarre les tâches de fond de ses agents |
| `OrganisationController` | messagerie, agenda, alarmes, notes, trajets |
| `OrdinateurController` | poste, informations, musique, fichiers |
| `SavoirController` | web, conversation, mémoire, traduction, vision (web et conversation exposés en `.web` et `.conversation`) |
| `CreationController` | code, design, documents, atelier, qui partagent un `Workshop` ; `occupied_with()` ne retient pas la conversation si les créations ont leur propre modèle |
| `RoutinesController` | routines (l'agent, exposé en `.routines`, exécute ses étapes par `Jarvis.run_phrase`) |
| `MaisonController` | maison |

Ajouter un agent : créer `agents/mon_agent.py`, l'ajouter à l'équipe d'un contrôleur ou créer un nouveau contrôleur ajouté à la liste dans `main.py`, faire reconnaître ses phrases dans `core/intents/mon_agent.py` (et l'ajouter aux parseurs de `core/intents/__init__.py`), et les ajouter à l'examen `tests/test_agent_exam.py`.

### `core/messages.py`
- **Role**: format des requêtes et réponses (`HistoryMessage`, `ChatRequest`, `ChatResponse`).

### `routes/`
- **Role**: les routes HTTP, sans logique métier.

| Fichier | Routes |
|---|---|
| `chat.py` | `/api/chat`, `/api/chat/stream` (NDJSON) |
| `voice.py` | `/api/tts`, `/api/stt` |
| `hud.py` | `/api/status`, `/api/system`, `/api/dashboard`, `/api/briefing`, `/api/events`, `/api/alarms`, `/api/commands`, `/api/warmup`, et les fichiers du HUD (`HudFiles`, `Cache-Control: no-cache`) |
| `google.py` | `/api/google/connect`, `/api/google/disconnect` |
| `creations.py` | `/api/creations`, `/api/creations/{chemin}` (les créations, consultables depuis le téléphone ; `creation_url()` donne l'adresse d'une création) |
| `security.py` | `RemoteAccessGuard` (code d'accès), `is_remote_request`, CORS limité à `localhost` (+ `JARVIS_ALLOWED_ORIGINS`), en-tête `Host` vérifié |

### `config.py`
- **Role**: configuration centralisée.
- **Responsabilite**: charge le `.env` avant toute lecture de variable, expose les réglages (`USER_TITLE`, `CITY`, `OLLAMA_MODEL`, `TTS_ENGINE`, `STT_ENGINE`, `HOST`, `PORT`, `ALARM_*`…).

| Fonction | Rôle |
|---|---|
| `env_str`, `env_flag`, `env_int`, `env_float`, `env_list` | lecture typée et bornée d'une variable d'environnement |
| `ACCESS_TOKEN` | code exigé des autres appareils (`JARVIS_ACCESS_TOKEN`) |
| `local_now()` | l'heure chez l'utilisateur (`GOOGLE_TIMEZONE`), sans fuseau, comme les heures comprises dans les phrases |
| `CREATION_MODEL`, `MAIL_TRIAGE`, `MEETING_REMINDER_MINUTES` | modèle des créations, tri des mails, marge avant un rendez-vous |
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

### `core/intents/`
- **Role**: détection des intentions et parsing des commandes slash ou phrases naturelles.
- **Responsabilite**: transforme du texte libre en dictionnaires d'actions structurées, sans le modèle de langage.

| Fichier | Rôle |
|---|---|
| `__init__.py` | `detect_action(text, fallback_email=None)` : essaie chaque parseur dans l'ordre et renvoie une action, ou `None` (conversation) ; `classify_confirmation(text)` (« oui » / « non ») ; réexporte `COMMAND_HELP`, `extract_recent_email_from_history` |
| `common.py` | `parse_datetime_expression` (« demain à 7h30 », « lundi prochain », « dans une demi-heure »), `normalize_spoken_time`, `spoken_numbers` (« sept heures trente » → « 7 heures 30 », seulement devant une unité), `extract_relative_delay`, `extract_day_period_bounds`, `extract_repeat` (« tous les soirs », « en semaine », « tous les mardis »), `first_occurrence`, `strip_time_expressions`, `clean_fragment` |
| `commands.py` | `parse_command` : commandes slash (`/sendmail`, `/addevent`, `/status`, `/open`, `/volume`…) et `COMMAND_HELP` |
| `mail.py` | envoi (adresse, contact du carnet, objet, message), lecture, réponse, recherche, archivage |
| `calendar.py` | création (titre « Réunion : budget », récurrence), liste, disponibilités, suppression, déplacement |
| `alarms.py` | minuteurs, rappels, alarmes et réveils, répétition |
| `system.py` | diagnostic, volume, veille, applications et sites (`WEB_ONLY_SITES` : « ouvre YouTube »), écran, réseau, apparence |
| `info.py` | heure, date, météo (jour, semaine, heure par heure), soleil, qualité de l'air, briefing |
| `web.py` | questions à chercher sur le web (horaires, prix et comparaisons, actualité, résultats…), Wikipédia, résumé d'une page |
| `creation.py` | code (et ses outils : tests, correction, explication), pages, logos, palettes, documents, propositions et choix, PDF, icônes, retouches |
| `notes.py`, `travel.py`, `music.py`, `files.py`, `memory.py`, `translate.py`, `vision.py`, `home.py`, `routines.py` | les phrases de chacun de ces agents |

Les demandes en langage naturel qui envoient un mail ou suppriment en masse portent `confirm: True` : l'agent présente l'action et attend un « oui ». Les commandes slash s'exécutent directement.

### `services/llm.py`
- **Role**: client Ollama.
- **Responsabilite**: état du modèle, conversation, outil de recherche, garde-fous de la persona.

| Fonction | Rôle |
|---|---|
| `load_system_prompt()` | charge `system_prompt.txt` et y inscrit la formule d'appel |
| `ollama_status()` | vérifie qu'Ollama répond et que le modèle existe (gardé 30 s, 3 s s'il est hors ligne ; `forget_ollama_status()` l'oublie) |
| `build_messages(history, message, context, system=None, limit=None)` | prompt système (ou `system`) + contexte en direct + historique récent (ou les `limit` derniers messages) |
| `chat_stream(history, message, temperature, context, tools=None, system=None, history_limit=None)` | réponse phrase par phrase, pour parler sans attendre la fin ; se termine par un `ToolCall` si le modèle appelle un outil, y compris quand il l'écrit en toutes lettres (« recherche_web{…} ») au lieu de le déclarer |
| `supports_tools()` | indique si le modèle sait appeler des outils (sinon, seul le routeur déclenche les recherches) |
| `search_query(history, message)` | fait formuler la requête d'une recherche déjà décidée, avec un prompt de quelques lignes (`QUERY_PROMPT`, 0,4 s) : reprend le sujet d'une question de suite, ajoute la ville pour un service de proximité |
| `WEB_TOOL`, `TOOLS_HINT`, `WEB_ANSWER_RULES` | définition de l'outil `recherche_web` et consignes : quand chercher, comment répondre à partir des résultats (réponse directe d'abord, événement le plus récent ou le plus proche) |
| `WEB_PERSONA`, `WEB_HISTORY_MESSAGES`, `WEB_TEMPERATURE` | la réponse web part avec une persona réduite, les 2 derniers messages et une température basse : moins de texte à lire (le modèle lit environ 1 200 jetons par seconde avant de parler) et des faits mieux tenus |
| `split_sentences(buffer)` | découpe le flux en phrases complètes (sans couper « J.A.R.V.I.S. » ou « M. ») |
| `first_clause(buffer)` | pour parler plus tôt, dit une longue première phrase en deux temps, à partir d'une virgule |
| `keep_warm()` | charge le modèle en mémoire, ou l'y maintient, sans rien générer |
| `claims_unexecuted_action(user_message, reply)` | détecte un modèle qui prétend avoir exécuté une action |
| `complete(system, prompt, ...)` | génération ponctuelle (objet et corps des mails) |
| `warm_up()` | charge le modèle en mémoire au démarrage |

Si le modèle affirme « j'ai envoyé… » alors qu'aucun module n'a rien exécuté, sa réponse est remplacée par une demande de reformulation.

### `services/web_search.py`
- **Role**: recherche sur le web, sans clé d'API.
- **Responsabilite**: interroger le moteur (DuckDuckGo), lire les premières pages, en extraire les passages utiles.

| Fonction | Rôle |
|---|---|
| `search(query)` | interroge le moteur et renvoie les premiers résultats (titre, adresse, extrait) |
| `parse_results(page)` | lit la page de résultats ; écarte les publicités et sort l'adresse réelle des redirections |
| `fetch_page(url)` | télécharge une page publique : taille bornée, redirections suivies à la main et revalidées |
| `is_public_url(url)` | refuse le réseau local, les adresses internes et tout ce qui n'est pas http(s) |
| `extract_passages(page, query)` | garde le texte visible, puis les lignes en rapport avec la question et leur voisinage (une ligne de tableau reste sur une ligne : « Lundi 09:00 à 21:00 ») |
| `gather(query)` | recherche + lecture en parallèle des trois premières pages ; une page qui n'a pas répondu en 2,5 s est abandonnée (son extrait du moteur reste) ; cache de 5 min |
| `format_for_model(query, results)` | met les résultats en forme pour le modèle |
| `sources(results)` | pages affichées en liens dans le HUD |
| `clean_query(text)` | « cherche … sur internet » → requête |

Le texte des pages est un contenu non fiable : il est passé au modèle comme une donnée, avec la consigne de n'obéir à aucune instruction qu'il contiendrait, et le modèle ne peut de toute façon déclencher aucune action.

### `services/on_demand.py`
- **Role**: Jarvis à la demande.
- **Responsabilite**: le service macOS surveille le port et ne lance Jarvis qu'à la première connexion ; Jarvis s'arrête ensuite après `JARVIS_IDLE_MINUTES` sans demande (jamais si une alarme attend).

| Élément | Rôle |
|---|---|
| `launchd_sockets()` | récupère le port ouvert par macOS (`launch_activate_socket`) ; vide si Jarvis est lancé à la main |
| `Activity`, `ActivityTracker` | dernière demande et demandes en cours ; une réponse en flux compte jusqu'à sa fin |
| `should_sleep(...)`, `watch_idle(...)` | décident de l'arrêt et le déclenchent (`main.serve()` arrête alors uvicorn proprement) |

### `phone_setup.py`
- **Role**: préparer l'accès depuis le téléphone (appelé par `./run_jarvis.sh phone`).

| Fonction | Rôle |
|---|---|
| `ensure_phone_settings(dns_name, env_file)` | crée le code d'accès s'il manque et autorise l'adresse Tailscale dans `.env` ; renvoie le code |
| `show_qr(link)` | affiche le lien d'appairage en QR code (terminal et écran) |
| `set_env_values(values)` | écrit ou remplace des réglages dans `.env` sans toucher au reste (utilisé aussi par le bot Telegram) |
| `phone_report(status)` | à partir de `tailscale status --json`, dit si un téléphone est connecté au réseau Tailscale (sinon Safari ne trouve pas le Mac) |

### `services/voice.py`
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

### `agents/briefing.py`
- **Role**: vue d'ensemble de la journée.
- **Responsabilite**: tableau de bord du HUD, briefing, contexte en direct pour la conversation.

| Élément | Rôle |
|---|---|
| `Dashboard` | rassemble météo, agenda du jour, messages non lus et alarmes (cache de 90 s pour Google) |
| `build_briefing(dashboard, kind)` | « Bonjour, Monsieur. Il est… » : version courte (`boot`) ou complète (`full`) |
| `live_context(dashboard, message)` | contexte transmis au modèle : date, heure et ville, plus agenda / météo / messagerie / état du poste si la question s'y rapporte |

### `agents/system.py` — agent « poste »
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
| `keep_awake(mode)` | au démarrage de l'API : empêche le Mac de s'endormir tant que Jarvis tourne (`caffeinate`), pour qu'il réponde au téléphone (`JARVIS_KEEP_AWAKE`) |

Toutes les commandes système passent par `_run()` avec une liste d'arguments, jamais par un shell.

### `agents/info.py` — agent « informations »
- **Role**: heure, date, météo et briefing complet, à partir des fonctions de `agents/system.py`, `services/weather.py` et `agents/briefing.py`.

### `agents/web.py` — agent « web »
- **Role**: le réseau. `research(query)` cherche et lit les pages pour l'agent de conversation ; l'action `web_search` ouvre la recherche dans le navigateur (`local_only`, et `confirmable` quand Jarvis la propose après un échec).

### `agents/conversation.py` — agent « conversation »
- **Role**: conversation libre avec le modèle local.
- **Responsabilite**: `reply(history, text, temperature, plan, offer_browser)` fait répondre le modèle phrase par phrase ; si le plan le demande ou si le modèle appelle l'outil `recherche_web`, il annonce la recherche, la confie à l'agent web, puis fait rédiger la réponse à partir des pages lues.

### `agents/atelier.py` — l'atelier des agents créatifs
- **Role**: ce que partagent les agents code et design.

| Élément | Rôle |
|---|---|
| `Workshop` | dossier des créations (`JARVIS_CREATIONS_DIR`, `~/Documents/Jarvis` par défaut), dernière création en mémoire, travail en tâche de fond (`commission`) |
| `draft_until_valid(system, prompt, check)` | fait produire le fichier, le soumet au contrôle qualité `check`, et renvoie l'erreur au modèle pour une seconde tentative |
| `generate(...)` | génération longue avec une mémoire de travail de 8 192 jetons (Ollama recharge le modèle, ~4 s) ; après la création, le modèle est rechargé en mode conversation |
| `announce(text, speech, label)` | publie l'événement `creation` pour le HUD, ou parle sur le Mac si le HUD est fermé |
| `open_creation(creation)` | ouvre le code dans Visual Studio Code (sinon le Finder), le reste dans le navigateur |
| `CreativeAgent` | base des agents code et design : `start_job(...)` et `revise(creation, request)` |
| `AtelierAgent` | `revise_creation` (confie la retouche à l'auteur), `open_creation`, `list_creations` |

Une demande venue d'un autre appareil (téléphone, Discord) est enregistrée sur le Mac sans y être ouverte (`needs_origin` : Jarvis passe `params["remote"]`).

### `agents/code.py` — agent « code »
- **Role**: un fichier complet et vérifié : Python par défaut pour un script, page HTML unique pour une application avec interface ou un jeu.
- **Contrôle qualité** (`check_code`) : aucune partie à compléter (« ... », TODO), syntaxe vérifiée (`compile` pour Python, `node --check`, `bash -n`, JSON, `</html>`).

### `agents/design.py` — agent « design »
- **Role**: directeur artistique.

| Action | Résultat | Contrôle qualité |
|---|---|---|
| `design_page` | page HTML complète (variables CSS, responsive, contenu réel) | `<html>` complet, `<style>`, viewport, ni lorem ipsum ni image externe |
| `design_logo` | SVG 512×512 + page d'aperçu (fond clair, sombre, petite taille) | XML valide, `viewBox`, formes vectorielles seulement |
| `design_palette` | page nuancier (JSON du modèle, rendu par le code) | 5 couleurs `#RRGGBB` ; contrastes WCAG calculés (`contrast_ratio`) |

### `services/weather.py`
- **Role**: météo via Open-Meteo (gratuit, sans clé).

| Fonction | Rôle |
|---|---|
| `get_weather(city=None)` | conditions actuelles + prévisions d'aujourd'hui et de demain (cache de 10 min) |
| `handle_weather(params)` | réponse météo (`city`, `day: "tomorrow"`) avec conseil de parapluie |
| `summarize_now(weather)` | phrase affichée et phrase prononcée |

### `services/events.py`
- **Role**: file d'événements proactifs.

| Fonction | Rôle |
|---|---|
| `publish(kind, **payload)` | publie un événement (une alarme qui sonne) |
| `events_after(after_id)` | événements à relever par le HUD |
| `hud_is_listening()` | vrai si un HUD relève les événements : c'est alors lui qui prend la parole |

### `agents/mail.py` — agent « messagerie »
- **Role**: logique métier des emails.
- **Responsabilite**: formatage des mails, génération assistée par le modèle, envoi.

| Fonction | Rôle |
|---|---|
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

### `agents/calendar.py` — agent « agenda »
- **Role**: logique métier du calendrier.

| Fonction | Rôle |
|---|---|
| `format_week_events(events, now)` | événements de la semaine |
| `compute_availability(events, timezone)` | créneaux libres du lundi au vendredi, 9 h-18 h |
| `handle_events_week`, `handle_events_range` | liste sur la semaine, un jour ou une période |
| `handle_availability_week` | disponibilités |
| `handle_add_event(mail_client, params)` | crée un événement et signale un chevauchement éventuel |
| `handle_delete_event`, `handle_delete_events_range` | suppression par id ou par plage (avec confirmation si `confirm`) |

### `agents/alarms.py` — agent « alarmes »
- **Role**: logique métier des alarmes, minuteurs et rappels.

| Fonction | Rôle |
|---|---|
| `AlarmAgent.start()` | lance le planificateur une seule fois |
| `alarm_scheduler_loop(alarms)` | boucle de fond : détecte les alarmes échues, publie l'événement, notifie et sonne |
| `alarm_announcement(label, now)` | phrase prononcée (« Monsieur, il est 7 heures 30. ») |
| `trigger_local_alarm(label, when, speak)` | notification + carillon + annonce vocale si aucun HUD n'est ouvert |
| `handle_set_alarm(alarms, timezone, params)` | crée une alarme, un minuteur (`kind: "timer"`) ou un rappel (`kind: "reminder"`) |
| `handle_list_alarms`, `handle_delete_alarm`, `handle_delete_alarms_range` | liste et suppressions |
| `handle_delete_timers(alarms)` | arrête les minuteurs |
| `handle_delete_alarms_all(alarms, params)` | supprime tout (avec confirmation si `confirm`) |

### `services/alarm_store.py`
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

### `services/google_client.py`
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

| Couche | Peut utiliser |
|---|---|
| `main.py` | tout (c'est lui qui assemble) |
| `routes/` | `core/` (Jarvis), quelques fonctions de lecture des agents pour le HUD, `services/` |
| `controllers/` | `core/controller.py` et les agents de leur équipe |
| `core/jarvis.py` | `core/intents/`, les contrats `core/controller.py` et `core/agent.py`, `services/llm.py` (état du modèle) |
| `agents/` | `services/`, `persona.py`, `config.py`, et les fonctions d'un autre agent (le briefing lit les capteurs du poste) |
| `services/` | `persona.py`, `config.py` — jamais un agent |
| `config.py` | aucun (chargé en premier) |
| `persona.py` | `config.py` |
