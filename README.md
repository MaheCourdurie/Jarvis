# J.A.R.V.I.S
## Just A Rather Very Intelligent System

## Présentation générale du sujet

J.A.R.V.I.S est un assistant personnel local, pensé comme celui de Tony Stark dans Iron Man :

- tu lui **parles** (« Jarvis, quel temps fait-il ? ») et il te **répond à voix haute**
- il a le caractère du majordome : il te vouvoie, t'appelle « Monsieur », reste flegmatique et pince-sans-rire
- il s'affiche dans un **HUD holographique** : réacteur animé qui réagit à la voix, capteurs système, agenda, météo
- il **agit** vraiment : emails, calendrier, alarmes, minuteurs, applications, volume, recherches
- il est **proactif** : briefing d'accueil, annonce des alarmes, signalement des conflits d'agenda et de la batterie faible
- il **converse** librement sur n'importe quel sujet, grâce à un modèle de langage local

Le projet combine:

- une API Python pour les actions réelles (Gmail + Google Calendar + alarmes locales + pilotage du poste)
- un modèle Ollama local pour la conversation
- une voix 100 % locale : reconnaissance Whisper et synthèse neuronale Piper
- un HUD web servi par l'API
- un pipeline de fine-tuning MLX pour personnaliser le modèle
- un prompt système partagé entre entraînement et inférence

Rien ne quitte ta machine, à part les appels que tu demandes (Google, météo).

## Sommaire

- [Prérequis](#prérequis)
- [Démarrage rapide](#démarrage-rapide)
- [Parler à Jarvis](#parler-à-jarvis)
- [Ce que Jarvis sait faire](#ce-que-jarvis-sait-faire)
- [Commandes de run_jarvis.sh](#commandes-de-run_jarvissh)
- [Configuration (.env)](#configuration-env)
- [Configuration Google (Gmail + Calendar)](#configuration-google-gmail--calendar)
- [Installation du portage Discord](#installation-du-portage-discord)
- [Sécurité](#sécurité)
- [Entraîner ton propre modèle](#entraîner-ton-propre-modèle)
- [Prompt système partagé](#prompt-système-partagé)
- [Organisation de l'API](#organisation-de-lapi)
- [Tests](#tests)
- [Arborescence du projet](#arborescence-du-projet)

## Prérequis

- Python 3.9+
- Ollama installé (version 0.30.9 ou plus récente pour le modèle par défaut)
- un navigateur récent (Chrome, Arc, Edge, Safari) et un micro
- pour l'entraînement uniquement : macOS Apple Silicon, git, cmake

Le pilotage du poste (applications, volume, veille) est complet sur macOS, partiel sur Linux et Windows.

## Démarrage rapide

Aucun entraînement n'est nécessaire : Jarvis s'appuie sur un modèle de la bibliothèque Ollama, habillé de son prompt système.

```bash
python3 -m venv .venv          # il faut un env, même vide
./run_jarvis.sh setup          # dépendances + voix (Piper) + reconnaissance (Whisper)
./run_jarvis.sh create         # crée le modèle Ollama "jarvis"
./run_jarvis.sh start          # lance Jarvis et ouvre le HUD
```

Le HUD s'ouvre sur `http://localhost:8001/`. Clique sur **Initialiser**, autorise le micro, et Jarvis t'accueille : « Bonjour, Monsieur. Il est 7 heures… ».

Notes:

- `setup` télécharge une fois la voix (~60 Mo) et le modèle Whisper (~480 Mo)
- `create` télécharge une fois le modèle de base (`gemma4:e4b`, ~6,6 Go). Pour en choisir un autre, mets `JARVIS_BASE_MODEL` dans `.env` (par exemple `llama3.1:8b` ou `gemma3:4b`, plus léger)
- copie `.env.example` en `.env` pour personnaliser (formule d'appel, ville, voix…)

## Parler à Jarvis

| Geste | Effet |
|---|---|
| Dire « Jarvis, … » | donne un ordre (le prénom peut aussi venir à la fin de la phrase) |
| Dire « Jarvis » seul | il répond « Monsieur ? » et écoute la suite |
| Parler juste après sa réponse | pas besoin de redire son prénom pendant une douzaine de secondes |
| Barre d'espace, ou clic sur le réacteur | le met à l'écoute sans dire son prénom |
| Échap, ou clic pendant qu'il parle | le fait taire |
| Écrire dans la barre du bas | tout fonctionne aussi au clavier |

Les boutons en haut à droite :

- **Micro** : active ou coupe l'écoute
- **Voix** : active ou coupe la voix de Jarvis
- **Continu** : conversation continue, sans mot d'activation (à réserver aux pièces calmes)
- **Aide** : exemples de phrases et liste des commandes

Le réacteur change de couleur selon l'état : bleu (veille, écoute, réponse), ambre (analyse), rouge (alerte).

Pendant que Jarvis parle ou réfléchit, le micro est ignoré : il ne s'entend pas lui-même.

## Ce que Jarvis sait faire

Conversation:

- `Jarvis, tu es là ?` → « Pour vous, Monsieur, toujours. »
- `Explique-moi ce qu'est un trou noir`
- `Je vais déployer en production un vendredi soir`

Informations:

- `Quelle heure est-il ?` · `On est quel jour ?`
- `Quel temps fait-il ?` · `Quel temps fait-il à Lyon demain ?`
- `Fais-moi le point` (briefing : heure, météo, agenda, messagerie, alertes)

Poste de travail:

- `Lance un diagnostic` · `Niveau de batterie ?`
- `Ouvre Safari` · `Ferme la calculette` · `Ouvre github.com`
- `Monte le volume` · `Volume à 40` · `Coupe le son`
- `Cherche les dernières news sur l'IA` · `Recherche Iron Man sur YouTube`
- `Mets l'écran en veille`

Alarmes, minuteurs, rappels:

- `Réveille-moi demain à 7h30`
- `Minuteur de 10 minutes pour les pâtes` · `Annule le minuteur`
- `Rappelle-moi à 15h d'appeler Paul`
- `Quelles sont mes alarmes ?` · `Supprime toutes mes alarmes`

Calendrier:

- `Qu'est-ce que j'ai de prévu demain ?` · `Quels sont mes événements de mardi ?`
- `Planifie une réunion avec Sophie demain à 10h`
- `Crée un événement lundi de 14h à 16h pour réunion client`
- `Suis-je libre cette semaine ?`
- `Supprime les événements de vendredi`

Mail:

- `Résume mes mails` · `Lis mon dernier mail`
- `Envoie un mail à client@exemple.com pour lui dire que le devis est prêt`
- `Envoie un mail à Paul pour lui dire que je serai en retard` (avec un carnet d'adresses, voir plus bas)

Notes:

- avant d'envoyer un mail demandé en langage naturel, Jarvis **montre le message final** (objet et corps rédigés) et demande « Dois-je l'envoyer ? ». Réponds « oui » ou « non »
- même confirmation avant de supprimer plusieurs événements ou toutes les alarmes
- les commandes slash (`/sendmail`, `/deleteeventsrange`…) sont explicites et s'exécutent sans confirmation
- quand tu crées un événement sur un créneau déjà pris, Jarvis le signale
- un contenu mail inapproprié (insultes/grossièretés explicites) est bloqué localement, y compris les contournements par lettres séparées
- Jarvis ne prétend jamais avoir fait une action qu'il n'a pas exécutée : s'il lui manque une information, il la demande
- quand une alarme sonne, Jarvis l'annonce à voix haute dans le HUD ; si le HUD est fermé, l'API parle directement sur les haut-parleurs

### Carnet d'adresses

Dicter une adresse email est pénible. Copie `Jarvis/API/contacts.example.json` en `Jarvis/API/contacts.json` :

```json
{
  "Paul": "paul@exemple.com",
  "Sophie Martin": "sophie.martin@exemple.com"
}
```

Tu peux alors dire « envoie un mail à Paul pour lui dire que… ».

### Commandes slash

- `/help`
- `/mailresume` · `/maillast`
- `/sendmail "destinataire@domaine.com" "Objet" "Message"`
- `/eventsweek` · `/availability`
- `/addevent "Titre" "YYYY-MM-DD HH:MM" "YYYY-MM-DD HH:MM"`
- `/deleteevent "id"` · `/deleteeventsrange "YYYY-MM-DD" "YYYY-MM-DD"`
- `/setalarm "YYYY-MM-DD HH:MM" "Titre"` · `/alarms`
- `/deletealarm "id"` · `/deletealarmsrange "YYYY-MM-DD" "YYYY-MM-DD"` · `/deletealarmsall`
- `/briefing` · `/status` · `/battery` · `/weather "Ville"` · `/time` · `/date`
- `/open "Application"` · `/close "Application"` · `/volume 40` · `/search "requête"` · `/sleep`

## Commandes de run_jarvis.sh

Depuis la racine du projet:

```bash
chmod +x run_jarvis.sh
./run_jarvis.sh help
```

- `setup`: installe les dépendances Python, la voix Piper et le modèle Whisper
- `start`: lance Jarvis (API + HUD) et ouvre l'interface dans le navigateur
- `api`: lance l'API seule sur `http://localhost:8001` (elle sert aussi le HUD)
- `web`: sert le HUD seul sur `http://localhost:8000` (l'API doit tourner à part)
- `create`: crée/met à jour le modèle Ollama `jarvis` (GGUF fine-tuné s'il existe, sinon modèle de base)
- `voice`: télécharge seulement les modèles de voix
- `test`: envoie un prompt de test à Ollama
- `pytest`: lance les tests automatiques
- `train`: lance `Jarvis/train.py`
- `convert`: lance `Jarvis/convert_to_gguf.sh`
- `all`: enchaîne `train -> convert -> create -> test`

### Installation manuelle

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-voice.txt     # voix locale (facultatif)

cd Jarvis/API
python main.py
```

Puis ouvre `http://localhost:8001/`.

## Configuration (.env)

Tout est optionnel. Copie `.env.example` en `.env` à la racine et adapte.

| Variable | Défaut | Rôle |
|---|---|---|
| `JARVIS_USER_TITLE` | `Monsieur` | formule d'appel employée par Jarvis (`Madame`, un prénom…) |
| `JARVIS_CITY` | `Paris` | ville par défaut pour la météo et le briefing |
| `OLLAMA_URL` | `http://localhost:11434` | adresse d'Ollama |
| `OLLAMA_MODEL` | `jarvis` | modèle utilisé pour la conversation |
| `JARVIS_BASE_MODEL` | `gemma4:e4b` | modèle de base utilisé par `create` sans GGUF fine-tuné |
| `JARVIS_STRICT_ACTIONS_ONLY` | `0` | `1` : Jarvis refuse tout ce qui n'est pas une action (ancien comportement) |
| `JARVIS_CONFIRM_ACTIONS` | `1` | confirmation avant envoi de mail et suppressions en masse |
| `JARVIS_TTS_ENGINE` | `auto` | synthèse : `auto`, `piper`, `say` (macOS), `browser`, `off` |
| `JARVIS_PIPER_VOICE` | `fr_FR-tom-medium` | voix Piper |
| `JARVIS_TTS_VOICE` | *(auto)* | voix macOS pour le moteur `say` |
| `JARVIS_TTS_RATE` | `1.0` | débit de la voix |
| `JARVIS_STT_ENGINE` | `auto` | reconnaissance : `auto`, `whisper`, `browser`, `off` |
| `JARVIS_WHISPER_MODEL` | `small` | `tiny`, `base`, `small`, `medium` |
| `JARVIS_WAKE_WORD` | `jarvis` | mot d'activation |
| `JARVIS_HOST` / `JARVIS_PORT` | `127.0.0.1` / `8001` | adresse d'écoute de l'API |
| `JARVIS_ALLOWED_ORIGINS` | *(vide)* | origines web supplémentaires autorisées |
| `JARVIS_REMOTE_SYSTEM_CONTROL` | `0` | `1` : Discord peut piloter le poste |
| `GOOGLE_FORGET_TOKEN_ON_EXIT` | `1` | `0` : conserve la connexion Google entre deux lancements |

Après avoir changé `JARVIS_USER_TITLE`, relance `./run_jarvis.sh create`.

En mode `auto`, si les moteurs locaux ne sont pas installés, le HUD se rabat sur la voix et la reconnaissance du navigateur. Attention : la reconnaissance du navigateur envoie le son du micro à son éditeur, et ne fonctionne pas dans tous les navigateurs.

## Configuration Google (Gmail + Calendar)

1. Sur Google Cloud Console (https://console.cloud.google.com/):
- crée un projet
- dans API et Services active `Gmail API` et `Google Calendar API`
- configure l'écran de consentement OAuth (External)
- ajoute ton compte dans `Test users` dans l'onglet Audience
- crée un OAuth client `Desktop app` dans l'onglet Client
2. Télécharge le JSON client OAuth (secret client)
3. Mets à jour `.env`:

```bash
GOOGLE_CLIENT_SECRET_FILE=/chemin/vers/Jarvis/API/le-json-client-de-OAuth.json
GOOGLE_TOKEN_FILE=/chemin/vers/Jarvis/API/.google-token.json
GOOGLE_CALENDAR_ID=primary
GOOGLE_TIMEZONE=Europe/Paris

# Alarmes locales (notification native + son selon l'OS)
ALARMS_FILE=/chemin/vers/Jarvis/API/.alarms.json
ALARM_NOTIFICATION_ENABLED=1
ALARM_SOUND_ENABLED=1
ALARM_SOUND_REPEAT=1 # Nombre de répétitions (1 à 10)
ALARM_SOUND_FILE= # Chemin complet vers un fichier son. Laisser vide pour le carillon du système.
```

Dans le HUD, panneau **Liaisons**:

- clique sur `Connecter` pour lancer le consentement Google
- clique sur `Déconnecter` pour révoquer et supprimer le token

Par défaut, le token local est supprimé quand l'API s'arrête (`GOOGLE_FORGET_TOKEN_ON_EXIT=0` pour le conserver).

Sans Google, tout le reste fonctionne : conversation, météo, alarmes, pilotage du poste.

## Installation du portage Discord

### 1) Configurer les variables d'environnement

Dans le fichier `.env` à la racine:

```env
DISCORD_TOKEN=your_discord_bot_token
JARVIS_API_URL=http://127.0.0.1:8001/api/chat
```

Notes importantes:

- `DISCORD_TOKEN` est obligatoire
- `JARVIS_API_URL` doit pointer vers l'API Jarvis (`:8001/api/chat`) et pas vers Ollama (`:11434`)
- ne commit jamais `.env` dans git (le `.gitignore` l'exclut)

### 2) Configurer le bot sur Discord Developer Portal

1. Va sur https://discord.com/developers/applications.
2. Crée une application puis ouvre la section `Bot`.
3. Crée un bot et copie son token dans `DISCORD_TOKEN`.
4. Active `Message Content Intent`.
5. Génère une URL d'invitation avec les scopes `bot` et `applications.commands`.
6. Ajoute les permissions nécessaires pour lire/envoyer des messages.
7. Invite le bot sur ton serveur.

### 3) Lancer le bot

Depuis la racine du projet:

```bash
python3 Discord/main.py
```

Log attendu:

```text
Jarvis est pret: <nom_du_bot>
```

### 4) Connexion API/Google

Pour les actions mail/calendrier depuis Discord, connecte d'abord Google avec la commande `/google` ou depuis le HUD.

Depuis Discord, Jarvis converse et gère mails, agenda et alarmes, avec les mêmes confirmations. Il refuse en revanche de piloter ton ordinateur (applications, volume, veille), sauf si tu mets `JARVIS_REMOTE_SYSTEM_CONTROL=1`.

## Sécurité

Jarvis envoie des mails en ton nom et agit sur ton ordinateur : l'API est donc verrouillée par défaut.

- elle n'écoute que sur `127.0.0.1` : elle n'est pas joignable depuis le réseau
- seules les pages servies depuis `localhost` peuvent l'appeler : un site web quelconque ouvert dans ton navigateur ne peut pas faire agir Jarvis
- les requêtes adressées à un autre nom d'hôte sont refusées (protection contre le DNS rebinding)
- les commandes système ne passent jamais par un shell, et les noms d'applications et adresses web sont validés
- `.env`, le secret client Google, le token et le carnet d'adresses sont exclus de git

Pour ouvrir Jarvis à ton réseau local, en connaissance de cause : `JARVIS_HOST=0.0.0.0` et `JARVIS_ALLOWED_ORIGINS=http://ton-ip:8001`. Le micro du navigateur exige alors HTTPS ou `localhost`.

## Entraîner ton propre modèle

Facultatif : le fine-tuning ancre la personnalité de Jarvis dans le modèle lui-même (macOS Apple Silicon).

```bash
./run_jarvis.sh all      # train -> convert -> create -> test
```

ou étape par étape:

```bash
# 1) entraînement
cd Jarvis
python train.py

# 2) conversion GGUF
bash convert_to_gguf.sh

# 3) création du modèle Ollama (depuis la racine)
./run_jarvis.sh create

# 4) test
ollama run jarvis
```

Notes:

- `train` utilise `Jarvis/conversations.jsonl` : une centaine d'échanges dans le ton de Jarvis (vouvoiement, flegme, réponses courtes faites pour être dites, refus de prétendre avoir agi)
- le jeu de données est écrit avec « Monsieur » ; `train.py` y inscrit ta formule d'appel (`JARVIS_USER_TITLE`)
- les exemples sont fournis à MLX au format « chat » : c'est le gabarit de conversation du modèle qui est appliqué, le même qu'à l'inférence
- `JARVIS_TRAIN_MODEL` et `JARVIS_TRAIN_ITERS` permettent un essai rapide avec un petit modèle
- dès que `Jarvis/export/jarvis-q4.gguf` existe, `create` l'utilise à la place du modèle de base
- au premier lancement, `convert_to_gguf.sh` clone/build `llama.cpp` dans `Jarvis/.tools/llama.cpp`
- le script de conversion déquantise automatiquement `Jarvis/jarvis-fused` en FP16 avant conversion GGUF
- si `torch` est manquant, il est installé automatiquement dans le venv

Sorties de train (si lancé depuis `Jarvis/`):

- `Jarvis/mlx-data/`
- `Jarvis/jarvis-mlx/`
- `Jarvis/jarvis-fused/`

### Ancien modèle pré-entraîné

Le GGUF partagé sur Drive a été entraîné avec l'ancienne personnalité de Jarvis (tutoiement, refus de toute conversation hors mail/agenda/alarmes) :

- https://drive.google.com/file/d/1beJAhbYAGZROt85Tt_EQ-Xqpj5JKpXj-/view?usp=sharing

Il reste utilisable (place-le dans `Jarvis/export/jarvis-q4.gguf` puis `./run_jarvis.sh create`), mais il ne correspond plus au personnage : préfère le modèle de base, ou relance un entraînement.

## Prompt système partagé

Source de vérité:

- `Jarvis/system_prompt.txt`

Utilisé par:

- l'API (`Jarvis/API/llm.py`), qui y ajoute le contexte en direct (date, heure, et selon la question : agenda, météo, état du poste)
- le train (`Jarvis/train.py`)
- la création du modèle Ollama (via `.Modelfile.generated`)

Le marqueur `{titre}` y est remplacé par `JARVIS_USER_TITLE`.

## Organisation de l'API

Le backend est découpé par domaine:

- `Jarvis/API/main.py`: orchestration FastAPI (routes, confirmations, dispatch)
- `Jarvis/API/config.py`: lecture du `.env` et réglages
- `Jarvis/API/persona.py`: ton de Jarvis, dates en français, version orale des réponses
- `Jarvis/API/intents.py`: parsing commandes slash + intentions naturelles
- `Jarvis/API/llm.py`: client Ollama (conversation en flux, garde-fous)
- `Jarvis/API/voice.py`: synthèse (Piper / say) et reconnaissance (Whisper), mot d'activation
- `Jarvis/API/briefing.py`: tableau de bord du HUD, briefing, contexte en direct
- `Jarvis/API/system_actions.py`: diagnostic, applications, volume, web, veille
- `Jarvis/API/weather.py`: météo (Open-Meteo, sans clé)
- `Jarvis/API/events.py`: événements proactifs (alarmes annoncées par le HUD)
- `Jarvis/API/mail_actions.py`: logique emails (lecture, envoi, génération)
- `Jarvis/API/calendar_actions.py`: logique calendrier (liste, disponibilités, CRUD, conflits)
- `Jarvis/API/alarm_actions.py`: logique alarmes (scheduler, notification, son, annonce)

Le détail de chaque fichier est dans [Jarvis/API/README.md](Jarvis/API/README.md).

## Tests

```bash
./run_jarvis.sh pytest
```

Les tests couvrent le routeur d'intentions, la persona, le pilotage du poste (commandes système simulées), la voix et l'API de bout en bout avec un faux compte Google. Ils ne touchent ni à ta messagerie, ni à ton agenda, ni à ton ordinateur.

## Arborescence du projet

```text
.
├── README.md
├── requirements.txt            # API, Google, Discord
├── requirements-voice.txt      # voix locale (Whisper + Piper)
├── requirements-train.txt      # fine-tuning MLX
├── requirements-dev.txt        # tests
├── run_jarvis.sh
├── .env.example
├── .env                        # à créer (non versionné)
├── Discord/
│   └── main.py
├── Marketing/
│   └── report.md
├── Page/
│   ├── index.html
│   └── style.css
├── tests/
└── Jarvis/
    ├── README.md
    ├── Modelfile
    ├── conversations.jsonl
    ├── system_prompt.txt
    ├── train.py
    ├── convert_to_gguf.sh
    ├── API/
    │   ├── README.md
    │   ├── main.py
    │   ├── config.py
    │   ├── persona.py
    │   ├── intents.py
    │   ├── llm.py
    │   ├── voice.py
    │   ├── briefing.py
    │   ├── system_actions.py
    │   ├── weather.py
    │   ├── events.py
    │   ├── mail_actions.py
    │   ├── calendar_actions.py
    │   ├── alarm_actions.py
    │   ├── alarms.py
    │   ├── google_client.py
    │   ├── google_auth_setup.py
    │   ├── contacts.example.json
    │   ├── contacts.json           # à créer (non versionné)
    │   ├── google-client-secret.json
    │   ├── voices/                 # voix Piper, téléchargée par setup
    │   ├── .google-token.json      # généré lors de la connexion
    │   └── .alarms.json            # généré au premier lancement
    └── Interface/
        ├── index.html              # le HUD
        ├── hud.css
        ├── hud.js                  # dialogue, panneaux, démarrage
        ├── core.js                 # réacteur animé
        ├── voice.js                # micro, détection de parole, lecture de la voix
        └── mic-worklet.js
```
