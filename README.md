# J.A.R.V.I.S
## Just A Rather Very Intelligent System

## Présentation générale du sujet

J.A.R.V.I.S est un assistant personnel local qui répond à un besoin classique du sujet:

- un chatbot fonctionnel et testable
- une interface de démonstration
- des actions métier réelles (emails, calendrier, alarmes)
- une architecture claire entre intentions, API, intégrations et modèle local

Le projet combine:

- une API Python pour les actions réelles (Gmail + Google Calendar + alarmes locales)
- un modèle Ollama local pour la partie conversation
- une interface web de test
- un pipeline de fine-tuning MLX pour personnaliser le modèle
- un prompt système partagé entre entraînement et inférence

## Sommaire

- [Prérequis](#prerequis)
- [Choisir ton parcours](#choisir-ton-parcours)
- [Installation automatique (run_jarvissh)](#installation-automatique-run_jarvissh)
- [Installation manuelle](#installation-manuelle)
- [Installation du portage Discord](#suite--installation-du-portage-discord)
- [Configuration Google (Gmail + Calendar)](#configuration-google-gmail--calendar)
- [Prompt système partagé](#prompt-système-partagé)
- [Organisation de l'API](#organisation-de-lapi)
- [Commandes slash (interface)](#commandes-slash-interface)
- [Requêtes naturelles utiles](#requêtes-naturelles-utiles)
- [Fine-tuning modèle](#fine-tuning-modèle-explications)
- [Arborescence du projet](#arborescence-du-projet)

## Prérequis

- macOS puce AppleSilicon (uniquement pour l'entraînement MLX, sinon utilisable sur n'importe quel OS)
- Python 3.9+
- Ollama installé
- git
- cmake

Si tu n'es pas sur macOS avec une puce Apple Silicon, retire d'abord la dépendance `mlx-lm` du fichier `requirements.txt`.

## Choisir ton parcours

Tu as 2 façons d'utiliser le projet:

### Option A - Entraîner le modèle de A à Z

Utilise ce mode si tu veux reproduire tout le pipeline:

- entraînement MLX (`train.py`)
- conversion et quantification GGUF (`convert_to_gguf.sh`)
- création du modèle Ollama local (`jarvis`)

Commandes rapides:

```bash
python3 -m venv .venv
./run_jarvis.sh setup
./run_jarvis.sh all
./run_jarvis.sh api
./run_jarvis.sh web
```

### Option B - Démarrage rapide avec GGUF déjà prêt (Drive)

Si tu ne veux pas entraîner, télécharge directement le fichier GGUF:

- https://drive.google.com/file/d/1beJAhbYAGZROt85Tt_EQ-Xqpj5JKpXj-/view?usp=sharing

Puis:

1. Place le fichier dans `Jarvis/export/`.
2. Renomme-le en `jarvis-q4.gguf` (ou adapte la ligne `FROM` dans `Jarvis/Modelfile`).
3. Crée le modèle Ollama puis lance API + web.

Commandes rapides:

```bash
python3 -m venv .venv
./run_jarvis.sh setup
./run_jarvis.sh create
./run_jarvis.sh api
./run_jarvis.sh web
```

Dans cette option, tu peux ignorer `train`, `convert` et `all`.

## Installation automatique (run_jarvis.sh)

Cette section détaille surtout le parcours Option A (entraînement complet).

Le script `run_jarvis.sh` centralise l'installation, le lancement API/web et le pipeline modèle.

Depuis la racine du projet:

```bash
chmod +x run_jarvis.sh
./run_jarvis.sh help
```

Commandes principales:

- `setup`: installe les dépendances Python (`pip install -r requirements.txt`)
- `api`: lance l'API sur `http://localhost:8001`
- `web`: lance l'interface sur `http://localhost:8000`
- `train`: lance `Jarvis/train.py`
- `convert`: lance `Jarvis/convert_to_gguf.sh`
- `create`: génère le Modelfile final puis crée/met à jour le modèle Ollama `jarvis`
- `test`: envoie un prompt de test à Ollama
- `all`: enchaîne `train -> convert -> create -> test`

Lancement de Jarvis :

```bash
python3 -m venv .venv # il faut un env meme vide
./run_jarvis.sh setup
./run_jarvis.sh all # si jamais le model n'est pas encore entrainé

# Dès que l'entraînement est fini dans des terminaux différents, on exécute ces commandes :
./run_jarvis.sh api # Lance l'API
./run_jarvis.sh web # Lance l'interface
```

## Installation manuelle

Cette section détaille surtout le parcours Option A (entraînement complet).

### 1) Environnement Python

Depuis la racine du repo:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Lancer API + interface

```bash
# Terminal API
cd Jarvis/API
uvicorn main:app --host 0.0.0.0 --port 8001

# Terminal web (autre terminal)
cd Jarvis/Interface
python3 -m http.server 8000
```

Puis ouvre `http://localhost:8000/test_interface.html`.

### 3) Créer le modèle Ollama avec prompt système

Depuis `Jarvis/`:

```bash
cd Jarvis
awk -v prompt_file="system_prompt.txt" '
    BEGIN {
        in_system = 0
        inserted = 0
    }

    /^[[:space:]]*SYSTEM[[:space:]]+"""/ {
        in_system = 1
        next
    }

    in_system {
        if ($0 ~ /"""/) {
            in_system = 0
        }
        next
    }

    {
        print $0
        if (!inserted && $1 == "FROM") {
            print ""
            print "SYSTEM \"\"\""
            while ((getline line < prompt_file) > 0) {
                print line
            }
            close(prompt_file)
            print "\"\"\""
            inserted = 1
        }
    }

    END {
        if (!inserted) {
            print ""
            print "SYSTEM \"\"\""
            while ((getline line < prompt_file) > 0) {
                print line
            }
            close(prompt_file)
            print "\"\"\""
        }
    }
' Modelfile > .Modelfile.generated

ollama create jarvis -f .Modelfile.generated
ollama run jarvis
```

## Suite : Installation du portage Discord

### 1) Configurer les variables d'environnement

Dans le fichier `.env` à la racine:

```env
DISCORD_TOKEN=your_discord_bot_token
JARVIS_API_URL=http://127.0.0.1:8001/api/chat
```

Notes importantes:

- `DISCORD_TOKEN` est obligatoire
- `JARVIS_API_URL` doit pointer vers l'API Jarvis (`:8001/api/chat`) et pas vers Ollama (`:11434`)
- ne commit jamais `.env` dans git

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

Pour les actions mail/calendrier depuis Discord, connecte d'abord Google via l'interface web Jarvis (`Connecter`).

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

OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=jarvis
JARVIS_STRICT_ACTIONS_ONLY=1 # 1 par défaut: refuse les questions hors mail/calendrier/alarmes

# Alarmes locales (notification native + son selon l'OS)
ALARMS_FILE=/chemin/vers/Jarvis/API/.alarms.json
ALARM_NOTIFICATION_ENABLED=1
ALARM_SOUND_ENABLED=1
ALARM_SOUND_REPEAT=1 # Nombre de répétitions (1 à 10)
ALARM_SOUND_FILE= # Chemin complet vers un fichier son (ex: /System/Library/Sounds/Glass.aiff). Laisser vide pour utiliser le son par défaut de l'OS.
```

Dans l'interface web:

- clique sur `Connecter` pour lancer le consentement Google
- clique sur `Deconnecter` pour révoquer et supprimer le token

Le token local est supprimé automatiquement quand l'API s'arrete.

## Prompt système partagé

Source de vérité:

- `Jarvis/system_prompt.txt`

Utilise par:

- l'API (`Jarvis/API/main.py`)
- le train (`Jarvis/train.py`)
- la création du modèle Ollama (via `.Modelfile.generated`)

## Organisation de l'API

Le backend API est découplé par domaine:

- `Jarvis/API/main.py`: orchestration FastAPI (routes + dispatch)
- `Jarvis/API/intents.py`: parsing commandes slash + intentions naturelles
- `Jarvis/API/mail_actions.py`: logique emails (lecture, envoi, génération)
- `Jarvis/API/calendar_actions.py`: logique calendrier (liste, disponibilités, CRUD)
- `Jarvis/API/alarm_actions.py`: logique alarmes (scheduler, notification, son)

Ce découpage facilite la maintenance et limite les régressions croisées.

## Commandes slash (interface)

- `/help`
- `/mailresume`
- `/maillast`
- `/sendmail "destinataire@domaine.com" "Objet" "Message"`
- `/eventsweek`
- `/availability`
- `/addevent "Titre" "YYYY-MM-DD HH:MM" "YYYY-MM-DD HH:MM"`
- `/deleteevent "id"`
- `/deleteeventsrange "YYYY-MM-DD" "YYYY-MM-DD"`
- `/setalarm "YYYY-MM-DD HH:MM" "Titre"`
- `/alarms`
- `/deletealarm "id"`
- `/deletealarmsrange "YYYY-MM-DD" "YYYY-MM-DD"`
- `/deletealarmsall`

## Requêtes naturelles utiles

Calendrier:

- `Quels sont mes événements de mardi ?`
- `Montre mes événements de demain`
- `Supprime les événements de vendredi`

Mail:

- `Envoie un mail à client@exemple.com, objet Devis, message Bonjour`
- `Écris un mail à ... et dis-lui que ...`
- `Envoi un mail à ... pour lui dire qu'il est beau`
- `Envoi un mail à ... pour l'école et lui dire qu'il faut aller en cours`
- `message Bonjour, je confirme le rendez-vous` (si l'adresse est déjà connue dans l'échange)

Notes:

- les commandes mail/calendrier utilisent Google
- les alarmes sont locales (JSON persistant côté API)
- si le message est manquant, Jarvis demande une précision au lieu d'envoyer un mail générique
- l'objet auto-généré est limité à 1-2 mots maximum, en lien avec la demande
- en mode amélioration (`auto_polish`), Jarvis évite de renvoyer le brouillon brut tel quel et applique un format d'email si nécessaire
- un contenu mail inapproprié (insultes/grossièretés explicites) est bloqué localement et n'est pas envoyé
- les contournements par séparation de lettres (`z i z i`, `sui ci der`, etc.) sont également détectés et bloqués
- si l'utilisateur écrit `help`, `aide` ou `commandes`, Jarvis renvoie la liste des commandes disponibles
- si l'utilisateur demande `que peux-tu faire` (ou équivalent), Jarvis renvoie un résumé court des capacités
- si aucune action métier n'est détectée et qu'il ne s'agit pas d'une demande d'aide/capacités, Jarvis refuse la demande hors périmètre au lieu d'interroger Ollama
- au déclenchement d'une alarme, Jarvis tente notification native + son (macOS, Windows, Linux) avec fallback si commande système manquante

## Fine-tuning modèle explications

```bash
# 1) entraînement
cd Jarvis
python train.py

# 2) conversion GGUF
bash convert_to_gguf.sh

# 3) création du modèle Ollama
ollama create jarvis -f .Modelfile.generated

# 4) test
ollama run jarvis
```

Notes:

- `train` utilise `Jarvis/conversations.jsonl`
- la conversion GGUF utilise `Jarvis/convert_to_gguf.sh`
- au premier lancement, `convert_to_gguf.sh` clone/build `llama.cpp` dans `Jarvis/.tools/llama.cpp`
- le script de conversion déquantise automatiquement `Jarvis/jarvis-fused` en FP16 avant conversion GGUF
- si `torch` est manquant, il est installé automatiquement dans le venv

Sorties de train (si lancé depuis `Jarvis/`):

- `Jarvis/mlx-data/`
- `Jarvis/jarvis-mlx/`
- `Jarvis/jarvis-fused/`

## Arborescence du projet

```text
.
├── README.md
├── requirements.txt
├── run_jarvis.sh
├── .env
├── Discord/
│   └── main.py
├── Marketing/
│   └── report.md
├── Page/
│   ├── index.html
│   └── style.css
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
    │   ├── intents.py
    │   ├── mail_actions.py
    │   ├── calendar_actions.py
    │   ├── alarm_actions.py
    │   ├── alarms.py
    │   ├── google_client.py
    │   ├── google_auth_setup.py
    │   ├── google-client-secret.json
    │   ├── .google-token.json # Génèré automatiquement lors de la connexion
    │   └── .alarms.json # Génèré automatiquement lors de la visite de l'interface
    └── Interface/
        ├── test_interface.html
        ├── test_interface.js
        └── test_interface.css
```