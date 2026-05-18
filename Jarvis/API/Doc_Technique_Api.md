# Jarvis API - Documentation technique

## But du dossier

Ce dossier regroupe la logique serveur de Jarvis:

- l'API FastAPI
- le routage des intentions
- la logique metier des mails
- la logique metier du calendrier
- la logique metier des alarmes
- le client Google OAuth / Gmail / Calendar
- le stockage persistant des alarmes

## Vue d'ensemble des fichiers

### `main.py`
- **Role**: point d'entree de l'API FastAPI.
- **Responsabilite**: expose les routes HTTP, orchestre les appels vers Ollama, Google, les alarmes et les modules metier.

#### Classes

| Classe | Role |
|---|---|
| `HistoryMessage` | message d'historique avec `role` et `content` |
| `ChatRequest` | requete principale du chat (`message`, `history`, `temperature`) |
| `ChatResponse` | reponse de l'API (`reply`, `action`, `source`) |

#### Fonctions

| Fonction | Paramètres | Rôle des paramètres | Rôle |
|---|---|---|---|
| `load_system_prompt()` | aucun | aucun | charge `system_prompt.txt` ou renvoie un prompt par defaut |
| `ollama_status()` | aucun | aucun | verifie si Ollama repond et si le modele est disponible |
| `call_ollama(history, message, temperature)` | `history`, `message`, `temperature` | `history`: historique de conversation, `message`: message courant, `temperature`: niveau de creativite | appelle l'instance Ollama locale sur `http://localhost:11434` avec le modele `jarvis` |
| `run_action(action_payload)` | `action_payload` | `action_payload`: dictionnaire contenant l'action detectee et ses parametres | redirige vers les handlers mail/calendrier/alarmes |
| `classify_support_request(text)` | `text` | `text`: message utilisateur brut | detecte les demandes de support (`help`/`commandes`) et de capacites (`que peux-tu faire`) |
| `api_status()` | aucun | aucun | retourne l'etat global API / Ollama / provider mail |
| `api_commands()` | aucun | aucun | expose l'aide des commandes |
| `api_google_connect()` | aucun | aucun | lance le flux OAuth Google |
| `api_google_disconnect()` | aucun | aucun | revoque et supprime le token local Google |
| `api_alarms()` | aucun | aucun | retourne la liste des alarmes actives |
| `api_chat(request)` | `request` | `request`: corps de requete contenant le message, l'historique et la temperature | point d'entree principal: detecte une intention, puis gere les demandes support, puis applique le fallback strict/permissif |

Configuration associee:

- `JARVIS_STRICT_ACTIONS_ONLY=1` (par defaut): refuse les demandes hors mail/calendrier/alarmes et n'appelle pas Ollama
- `JARVIS_STRICT_ACTIONS_ONLY=0`: comportement permissif, fallback conversationnel via Ollama si aucune action n'est detectee
- les messages `help`/`aide`/`commandes` renvoient `COMMAND_HELP` meme sans action metier detectee
- les messages `que peux-tu faire` (ou variantes) renvoient un resume de capacites (`CAPABILITIES_REPLY`)
- ces deux routes de support sont traitees avant le refus hors perimetre (mode strict) et avant l'appel Ollama (mode permissif)

### `intents.py`
- **Role**: detection des intentions et parsing des commandes slash ou phrases naturelles.
- **Responsabilite**: transforme du texte libre en dictionnaires d'actions structurees.

#### Constantes

- `COMMAND_HELP`: texte d'aide des commandes supportees
- `EMAIL_PATTERN`: regex de detection d'email
- `WEEKDAY_INDEX`: correspondance jour de semaine -> index Python

#### Fonctions principales

| Fonction | Paramètres | Rôle des paramètres | Rôle |
|---|---|---|---|
| `detect_action(text, fallback_email=None)` | `text`, `fallback_email` | `text`: phrase utilisateur a analyser, `fallback_email`: email de secours si la phrase reference un mail precedent | entree principale: choisit le bon parser et renvoie une action |
| `_parse_command(text)` | `text` | `text`: commande slash brute | parse `/help`, `/sendmail`, `/addevent`, etc. |
| `_parse_natural_send_mail(text, fallback_email)` | `text`, `fallback_email` | `text`: phrase naturelle d'envoi, `fallback_email`: adresse a reutiliser si elle manque | comprend une demande naturelle d'envoi de mail et retourne une clarification si le contenu est incomplet |
| `_parse_natural_alarm(text)` | `text` | `text`: phrase naturelle liee aux alarmes | comprend les requetes d'alarmes |
| `_parse_natural_calendar(text)` | `text` | `text`: phrase naturelle liee au calendrier | comprend les requetes calendrier |

#### Aides de parsing

| Fonction | Paramètres | Rôle des paramètres | Rôle |
|---|---|---|---|
| `_extract_email(value)` | `value` | `value`: texte source a analyser | extrait la premiere adresse email |
| `_parse_datetime(value)` | `value` | `value`: date ISO/FR a convertir | convertit une date ISO/FR en `datetime` |
| `_extract_time_of_day(text)` | `text` | `text`: phrase a analyser | extrait une heure/minute |
| `_parse_datetime_expression(text)` | `text` | `text`: expression naturelle de date/heure | interprete une date/heure naturelle |
| `_parse_day_value(value, now=None)` | `value`, `now` | `value`: jour a convertir, `now`: reference temporelle optionnelle | convertit un jour en datetime a minuit |
| `_extract_day_period_bounds(text)` | `text` | `text`: phrase contenant une journee ou une periode | deduit une plage de dates |
| `_extract_duration_minutes(text)` | `text` | `text`: phrase contenant une duree | extrait une duree en minutes |
| `_clean_fragment(value)` | `value` | `value`: fragment texte brut | nettoie un fragment texte |
| `_extract_alarm_title(text, lowered)` | `text`, `lowered` | `text`: phrase originale, `lowered`: version en minuscules | extrait le titre d'une alarme |
| `_extract_mail_subject(text, quoted_parts)` | `text`, `quoted_parts` | `text`: phrase originale, `quoted_parts`: morceaux entre guillemets | extrait l'objet d'un mail |
| `_extract_mail_body(text)` | `text` | `text`: phrase originale | extrait le corps d'un mail et indique s'il etait explicite |
| `_references_previous_mail(text)` | `text` | `text`: phrase originale | detecte une reference a un mail deja cite |
| `_is_mail_followup_payload(text)` | `text` | `text`: phrase originale | detecte une reponse de suivi (`message ...`, `objet ...`, `sujet ...`) sans verbe d'envoi |

### `mail_actions.py`
- **Role**: logique metier des emails.
- **Responsabilite**: formatage des mails, generation assistée par Ollama, envoi.

#### Fonctions

| Fonction | Paramètres | Rôle des paramètres | Rôle |
|---|---|---|---|
| `extract_first_email(value)` | `value` | `value`: texte source a analyser | extrait la premiere adresse email |
| `extract_recent_email_from_history(history, max_messages=8)` | `history`, `max_messages` | `history`: messages recents, `max_messages`: nombre max de messages a analyser | recupere le dernier email visible dans l'historique |
| `normalize_generated_french(text)` | `text` | `text`: sortie brute du modele | corrige certaines erreurs francaises du modele |
| `format_mail_resume(items)` | `items` | `items`: liste d'emails non lus au format commun | formate le resume des emails non lus |
| `format_last_mail(item)` | `item` | `item`: email unique ou `None` | formate le dernier email recu |
| `fallback_email_subject(draft_context, body_hint)` | `draft_context`, `body_hint` | `draft_context`: contexte de la requete, `body_hint`: extrait du corps si disponible | fabrique un objet de secours |
| `fallback_email_body(subject, draft_context, body_hint)` | `subject`, `draft_context`, `body_hint` | `subject`: objet choisi, `draft_context`: contexte, `body_hint`: contenu deja extrait | fabrique un corps de secours |
| `generate_email_subject(draft_context, body_hint, ollama_url, ollama_model)` | `draft_context`, `body_hint`, `ollama_url`, `ollama_model` | `draft_context`/`body_hint`: contexte de generation, `ollama_url`: URL locale Ollama (`http://localhost:11434` par defaut), `ollama_model`: modele local utilise (`jarvis` par defaut) | demande a Ollama un objet tres court (1-2 mots) et filtre les sorties hors contexte |
| `generate_email_body(subject, draft_context, body_hint, polish_only, ollama_url, ollama_model)` | `subject`, `draft_context`, `body_hint`, `polish_only`, `ollama_url`, `ollama_model` | `subject`: objet du mail, `draft_context`: contexte global, `body_hint`: brouillon extrait, `polish_only`: vrai pour juste ameliorer, `ollama_url`: URL locale Ollama (`http://localhost:11434` par defaut), `ollama_model`: modele local utilise (`jarvis` par defaut) | demande a Ollama de rediger ou d'ameliorer un corps d'email |
| `handle_send_mail(mail_client, params, ollama_url, ollama_model)` | `mail_client`, `params`, `ollama_url`, `ollama_model` | `mail_client`: client Gmail, `params`: dictionnaire de l'action detectee, `ollama_url`: URL locale Ollama (`http://localhost:11434` par defaut), `ollama_model`: modele local utilise (`jarvis` par defaut) | orchestre l'envoi avec garde-fous: contenu obligatoire et blocage des textes inappropries |

#### Regles appliquees au flux d'envoi mail

- le message est obligatoire: si le corps est vide, l'API renvoie une demande de precision et n'envoie rien
- l'objet auto-genere est limite a 1-2 mots maximum
- les sorties verbeuses/hors sujet du modele sont ignorees au profit d'un fallback base sur le contexte
- en mode `polish_only`, si le modele renvoie un texte trop proche du brouillon brut, l'API applique un fallback de corps formate
- les contenus offensants ou sexuellement vulgaires explicites sont bloques avant l'appel Gmail
- les contournements par espaces/ponctuation (ex: `z i z i`, `sui ci der`) sont aussi bloques apres normalisation du texte

### `calendar_actions.py`
- **Role**: logique metier du calendrier.
- **Responsabilite**: affichage des evenements, disponibilites, creation/suppression.

#### Fonctions

| Fonction | Parametres | Role des parametres | Role |
|---|---|---|---|
| `format_datetime(value)` | `value` | `value`: date a formater | formate une date pour l'affichage |
| `format_week_events(events)` | `events` | `events`: liste des evenements deja converts | formate les evenements de la semaine |
| `compute_availability(events, timezone)` | `events`, `timezone` | `events`: evenements occupes, `timezone`: fuseau utilise pour le calcul | calcule les disponibilites du lundi au vendredi |
| `handle_events_week(mail_client)` | `mail_client` | `mail_client`: client Google contenant la methode de lecture calendrier | retourne les evenements de la semaine |
| `handle_availability_week(mail_client)` | `mail_client` | `mail_client`: client Google pour lire les evenements et le fuseau | retourne les disponibilites calculees |
| `handle_add_event(mail_client, params)` | `mail_client`, `params` | `mail_client`: client Google, `params`: contient `title`, `start`, `end` | cree un evenement |
| `handle_delete_event(mail_client, params)` | `mail_client`, `params` | `mail_client`: client Google, `params`: contient `event_id` | supprime un evenement par id |
| `handle_delete_events_range(mail_client, params)` | `mail_client`, `params` | `mail_client`: client Google, `params`: contient `start`, `end` | supprime des evenements sur une plage |
| `handle_events_range(mail_client, params)` | `mail_client`, `params` | `mail_client`: client Google, `params`: contient `start`, `end` | liste les evenements d'une plage ou d'un jour |

### `alarm_actions.py`
- **Role**: logique metier des alarmes.
- **Responsabilite**: stockage en memoire, notification, son, scheduler.

#### Constantes

- `ALARM_NOTIFICATION_ENABLED`
- `ALARM_SOUND_ENABLED`
- `ALARM_SOUND_REPEAT`
- `ALARM_SOUND_FILE`

#### Fonctions privees

| Fonction | Parametres | Role des parametres | Role |
|---|---|---|---|
| `_env_flag(name, default)` | `name`, `default` | `name`: variable d'environnement, `default`: valeur par defaut | lit un booléen depuis l'environnement |
| `_env_int(name, default, min_value, max_value)` | `name`, `default`, `min_value`, `max_value` | `name`: variable a lire, `default`: valeur de secours, `min_value`/`max_value`: bornes | lit un entier borne |
| `_run_command(command)` | `command` | `command`: commande systeme a executer | execute une commande systeme |
| `_escape_applescript(value)` | `value` | `value`: texte brut a echapper | echappe une chaine pour AppleScript |
| `_notify_alarm_desktop(label, when)` | `label`, `when` | `label`: titre de l'alarme, `when`: horodatage affiche | affiche une notification locale |
| `_play_alarm_sound()` | aucun | aucun | joue un son d'alarme avec fallback |

#### Fonctions publiques

| Fonction | Parametres | Role des parametres | Role |
|---|---|---|---|
| `format_alarm_datetime(value, timezone)` | `value`, `timezone` | `value`: date a formater, `timezone`: fuseau de reference | formate une date d'alarme |
| `format_alarm_list(items, timezone)` | `items`, `timezone` | `items`: liste des alarmes, `timezone`: fuseau d'affichage | formate la liste des alarmes actives |
| `trigger_local_alarm(label, when)` | `label`, `when` | `label`: titre de l'alarme, `when`: date/heure de declenchement | lance notification + son |
| `alarm_scheduler_loop(alarms)` | `alarms` | `alarms`: store qui expose `trigger_due_alarms()` | boucle de fond qui surveille les alarmes arrivees a echeance |
| `handle_set_alarm(alarms, timezone, params)` | `alarms`, `timezone`, `params` | `alarms`: store d'alarmes, `timezone`: fuseau d'affichage, `params`: contient `when` et `title` | cree une alarme |
| `handle_list_alarms(alarms, timezone)` | `alarms`, `timezone` | `alarms`: store d'alarmes, `timezone`: fuseau d'affichage | retourne les alarmes actives |
| `handle_delete_alarm(alarms, params)` | `alarms`, `params` | `alarms`: store d'alarmes, `params`: contient `alarm_id` | supprime une alarme par id |
| `handle_delete_alarms_range(alarms, params)` | `alarms`, `params` | `alarms`: store d'alarmes, `params`: contient `start`, `end` | supprime les alarmes sur une plage |
| `handle_delete_alarms_all(alarms)` | `alarms` | `alarms`: store d'alarmes | supprime toutes les alarmes |

### `alarms.py`
- **Role**: stockage persistant des alarmes en JSON.
- **Responsabilite**: lecture/ecriture fichier, CRUD, detection des alarmes dues.

#### Classe `AlarmStore`

| Méthode | Paramètres | Rôle des paramètres | Rôle |
|---|---|---|---|
| `__init__(file_path, timezone_name)` | `file_path`, `timezone_name` | `file_path`: chemin du JSON, `timezone_name`: fuseau utilise pour normaliser les dates | initialise le magasin d'alarmes |
| `from_env(timezone_name)` | `timezone_name` | `timezone_name`: fuseau de travail | fabrique le store depuis les variables d'environnement |
| `create_alarm(when, label)` | `when`, `label` | `when`: date/heure cible, `label`: texte affiche | cree et persiste une alarme |
| `list_alarms(include_triggered=False)` | `include_triggered` | `include_triggered`: inclure ou non les alarmes deja declenchees | liste les alarmes |
| `delete_alarm(alarm_id)` | `alarm_id` | `alarm_id`: identifiant complet ou prefixe | supprime une alarme par id ou prefixe |
| `delete_alarms_in_range(start, end, include_triggered=False)` | `start`, `end`, `include_triggered` | `start`/`end`: bornes temporelles, `include_triggered`: inclure les alarmes deja declenchees | supprime les alarmes sur une plage |
| `delete_all_alarms(include_triggered=False)` | `include_triggered` | `include_triggered`: inclure les alarmes deja declenchees | supprime toutes les alarmes |
| `trigger_due_alarms()` | aucun | aucun | marque et retourne les alarmes arrivees a l'heure |

### `google_client.py`
- **Role**: client OAuth unique pour Gmail et Google Calendar.
- **Responsabilite**: authentification, rafraichissement du token, appels API Google.

#### Exceptions

- `GoogleConfigError`: probleme de configuration
- `GoogleApiError`: erreur runtime API

#### Classe `GoogleClient`

| Méthode | Paramètres | Rôle des paramètres | Rôle |
|---|---|---|---|
| `__init__(client_secret_file, token_file, timezone_name, calendar_id)` | `client_secret_file`, `token_file`, `timezone_name`, `calendar_id` | `client_secret_file`: chemin du secret OAuth, `token_file`: chemin du token local, `timezone_name`: fuseau utilise, `calendar_id`: calendrier cible | initialise le client |
| `from_env()` | aucun | aucun | fabrique le client depuis l'environnement |
| `missing_keys()` | aucun | aucun | liste ce qui manque pour fonctionner |
| `is_configured()` | aucun | aucun | dit si la config est complete |
| `status()` | aucun | aucun | retourne un statut synthétique |
| `disconnect(revoke=True)` | `revoke` | `revoke`: indique si le token doit aussi etre revoque cote Google | revoque et supprime le token local |
| `setup_oauth_token()` | aucun | aucun | lance le flux OAuth et enregistre le token |
| `get_unread_emails(limit=5)` | `limit` | `limit`: nombre maximum d'emails a recuperer | lit les emails non lus |
| `get_latest_email()` | aucun | aucun | retourne le dernier email |
| `send_mail(to_email, subject, body)` | `to_email`, `subject`, `body` | `to_email`: destinataire, `subject`: objet, `body`: contenu du mail | envoie un email via Gmail |
| `list_week_events()` | aucun | aucun | retourne les evenements de la semaine |
| `list_events_in_range(start, end)` | `start`, `end` | `start`/`end`: bornes de la periode a lire | retourne les evenements d'une plage |
| `delete_events_in_range(start, end)` | `start`, `end` | `start`/`end`: bornes des evenements a supprimer | supprime les evenements d'une plage |
| `create_event(subject, start, end)` | `subject`, `start`, `end` | `subject`: titre de l'evenement, `start`: debut, `end`: fin | cree un evenement calendrier |
| `delete_event(event_id)` | `event_id` | `event_id`: identifiant de l'evenement a supprimer | supprime un evenement |

### `google_auth_setup.py`
- **Role**: point d'entree simple pour creer le token OAuth Google.
- **Responsabilite**: lance `GoogleClient.setup_oauth_token()` et affiche le resultat.

#### Fonction

| Fonction | Paramètres | Rôle des paramètres | Rôle |
|---|---|---|---|
| `main()` | aucun | aucun | lance le flux OAuth et affiche le chemin du token |

## Dependances entre fichiers

| Fichier | Dependance principale |
|---|---|
| `main.py` | appelle `intents.py`, `mail_actions.py`, `calendar_actions.py`, `alarm_actions.py`, `google_client.py`, `alarms.py` |
| `intents.py` | prepare les actions pour `main.py` |
| `mail_actions.py` | utilise `GoogleClient` passe en parametre |
| `calendar_actions.py` | utilise `GoogleClient` passe en parametre |
| `alarm_actions.py` | utilise `AlarmStore` passe en parametre |
| `alarms.py` | stockage persistant indépendant |
| `google_client.py` | client métier central pour Gmail + Calendar |
| `google_auth_setup.py` | utilitaire de configuration OAuth |
