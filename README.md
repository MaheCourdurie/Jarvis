# J.A.R.V.I.S
## Just A Rather Very Intelligent System

## Présentation générale du sujet

J.A.R.V.I.S est un assistant personnel local, pensé comme celui de Tony Stark dans Iron Man :

- tu lui **parles** (« Jarvis, quel temps fait-il ? ») et il te **répond à voix haute**
- il a le caractère du majordome : il te vouvoie, t'appelle « Monsieur », reste flegmatique et pince-sans-rire
- il s'affiche dans un **HUD holographique** : réacteur animé qui réagit à la voix, capteurs système, agenda, météo
- il **agit** vraiment : emails, calendrier, alarmes, minuteurs, applications, volume
- il **cherche sur le web** à ta place : horaires, prix, actualité, résultats… et te donne la réponse à voix haute
- il est **proactif** : briefing d'accueil, annonce des alarmes, signalement des conflits d'agenda et de la batterie faible
- il **converse** librement sur n'importe quel sujet, grâce à un modèle de langage local

Le projet combine:

- une API Python pour les actions réelles (Gmail + Google Calendar + alarmes locales + pilotage du poste)
- un modèle Ollama local pour la conversation
- une voix 100 % locale : reconnaissance Whisper et synthèse neuronale Piper
- un HUD web servi par l'API
- un pipeline de fine-tuning MLX pour personnaliser le modèle
- un prompt système partagé entre entraînement et inférence

Le modèle, la voix et la reconnaissance tournent sur ta machine. Seuls en sortent les appels que tu demandes : Google, la météo, et les recherches web (DuckDuckGo et les pages consultées), désactivables avec `JARVIS_WEB_SEARCH=0`.

## Sommaire

- [Prérequis](#prérequis)
- [Démarrage rapide](#démarrage-rapide)
- [Parler à Jarvis](#parler-à-jarvis)
- [Utiliser Jarvis depuis ton téléphone](#utiliser-jarvis-depuis-ton-téléphone)
- [Lancer et arrêter Jarvis depuis Telegram](#lancer-et-arrêter-jarvis-depuis-telegram)
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

- `setup` télécharge une fois la voix (~60 Mo) et le modèle de reconnaissance (Whisper large-v3-turbo, ~1,6 Go sur Mac Apple Silicon ; Whisper small, ~480 Mo ailleurs)
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

S'il écorche un nom propre (une ville, une enseigne, un prénom), ajoute-le à `JARVIS_STT_VOCABULARY` dans `.env` : la reconnaissance vocale saura alors l'écrire.

Réactivité mesurée sur un MacBook Air M5, de la fin de ta phrase au début de la réponse : environ 1 seconde pour une action (heure, alarme, volume…), 2 secondes pour une question libre, 4 à 6 secondes pour une recherche web (Jarvis prévient aussitôt ; c'est surtout le temps que met le modèle à lire les pages). Sur Mac Apple Silicon, la reconnaissance vocale tourne sur la puce graphique ; tant que le HUD est ouvert, le modèle de langage reste chargé en mémoire.

## Utiliser Jarvis depuis ton téléphone

Jarvis tourne sur le Mac ; le téléphone n'est qu'un écran et un micro de plus. L'accès passe par [Tailscale](https://tailscale.com), un réseau privé entre tes appareils : il fournit l'adresse HTTPS qu'exige le micro du téléphone, fonctionne aussi hors de chez toi, et Jarvis n'est jamais exposé sur Internet.

1. Installe Tailscale sur le Mac et sur le téléphone, connectés au même compte.
2. Sur le Mac :

   ```bash
   ./run_jarvis.sh phone
   ```

   La première fois, Tailscale demande d'autoriser la publication (« Serve ») : ouvre le lien affiché, accepte, puis la commande continue d'elle-même.
3. Un QR code s'affiche à l'écran : scanne-le avec l'appareil photo du téléphone. Le lien contient un code d'accès, mémorisé une fois pour toutes par le navigateur du téléphone.
4. Relance Jarvis (`./run_jarvis.sh start`) : le code d'accès et l'adresse Tailscale sont pris en compte.

Si Safari affiche « Safari ne peut pas ouvrir la page », Tailscale n'est pas activé sur le téléphone : sans lui, l'adresse du Mac est introuvable. Ouvre l'app Tailscale, vérifie le compte (le même que sur le Mac), active-la (l'icône VPN apparaît en haut de l'écran), puis rescanne le QR code. `./run_jarvis.sh phone` le signale avant d'afficher le QR code.

Depuis un autre appareil que le Mac, l'API exige ce code d'accès (`JARVIS_ACCESS_TOKEN`, créé dans `.env`) : un appareil du réseau Tailscale qui ne l'a pas ne peut rien faire. Pour couper l'accès : `tailscale serve --https=443 off`.

Pour que Jarvis réponde au téléphone à tout moment, installe-le comme service macOS. Il est **à la demande** : rien ne tourne tant que personne ne s'en sert ; macOS surveille son port et le lance à la première connexion (interface, app, Telegram), en moins d'une seconde. Jarvis s'arrête ensuite de lui-même après 20 minutes sans demande (`JARVIS_IDLE_MINUTES`) ; une interface ouverte quelque part, ou une alarme en attente, le garde allumé.

```bash
./run_jarvis.sh service install   # à la demande, dès maintenant et à chaque ouverture de session
./run_jarvis.sh service stop      # le coupe complètement : plus de démarrage à la demande, jusqu'au prochain start
./run_jarvis.sh service start     # le relance (et le démarre tout de suite)
./run_jarvis.sh service restart   # après une mise à jour du code ou du .env
./run_jarvis.sh service status
./run_jarvis.sh service remove    # le désinstalle
```

Le service exige que le projet soit hors du Bureau, des Documents et des Téléchargements : macOS interdit aux programmes d'arrière-plan d'accéder à ces dossiers. Range-le par exemple dans `~/Developer/Jarvis` (et recrée `.venv` après le déplacement). Sinon, lance simplement Jarvis à la main avec `./run_jarvis.sh start` quand tu en as besoin.

### L'app sur l'écran d'accueil

Jarvis s'installe comme une app : icône sur l'écran d'accueil, ouverture en plein écran, sans la barre de Safari.

1. Dans Safari, une fois Jarvis ouvert sur le téléphone, touche **App** en haut de l'écran, puis **Copier le code**.
2. Touche **Partager**, puis **Sur l'écran d'accueil**.
3. Ouvre Jarvis depuis l'écran d'accueil : touche **Coller**, puis **Valider**. Sur iPhone, l'app installée ne partage pas les données de Safari ; elle demande donc le code une seule fois. Le lien complet du QR code se colle aussi.

L'interface reste dans l'app (service worker) : si le Mac ne répond pas, elle s'ouvre quand même, dit ce qui manque et se reconnecte d'elle-même. Quand tu reviens dans l'app après avoir verrouillé l'écran, le micro repart tout seul ; si Jarvis reste muet, touche le réacteur.

### Joindre Jarvis à tout moment

- **Sur l'iPhone** : dans l'app Tailscale, touche ta photo de profil, puis **VPN On Demand**, et choisis **Always** pour le Wi-Fi et le réseau mobile : Tailscale se reconnecte tout seul.
- **Sur le Mac** : Jarvis tourne en service (voir plus haut) et, tant qu'il tourne, empêche le Mac de s'endormir quand il est branché ; l'écran s'éteint normalement. Réglage : `JARVIS_KEEP_AWAKE=secteur` (par défaut), `toujours` (sur batterie aussi) ou `0`. Capot fermé, un MacBook s'endort quoi qu'il arrive : laisse-le ouvert.

## Lancer et arrêter Jarvis depuis Telegram

Un petit bot Telegram lance, arrête et redémarre Jarvis à distance, et dit s'il est en ligne. Il tourne à part de Jarvis (service macOS `fr.jarvis.telegram`) : il reste joignable quand Jarvis est arrêté. Il interroge lui-même Telegram, sans rien ouvrir sur le Mac, et n'obéit qu'à ton compte.

1. Dans Telegram, ouvre **@BotFather**, envoie `/newbot`, choisis un nom (« Jarvis ») puis un identifiant qui finit par « bot ». Copie le token qu'il te donne : copié sur l'iPhone, il arrive aussi dans le presse-papiers du Mac.
2. Sur le Mac :

   ```bash
   ./run_jarvis.sh telegram
   ```

   Le token est lu dans le presse-papiers (ou dans `.env`, ou demandé), puis un code à 6 chiffres s'affiche : envoie-le au bot dans Telegram (ou scanne le QR code affiché et touche **Démarrer**). Ce code à usage unique appaire ton compte ; les messages de tous les autres sont ignorés.
3. Envoie `/aide` au bot pour la liste des commandes (`/statut`, `/lancer`, `/arreter`, `/redemarrer`), aussi proposées par le menu « / » de Telegram. Ses réponses portent des boutons **Lancer**, **Arrêter**, **Redémarrer** et **Statut**, et il comprend aussi « lance », « arrête », « stop »…

Pour changer de token (par exemple après l'avoir régénéré avec `/revoke` dans @BotFather) : copie le nouveau, puis relance `./run_jarvis.sh telegram` ; le token du presse-papiers remplace l'ancien et l'appairage est conservé.

Jarvis étant à la demande, le bot dit s'il est en ligne, en veille (il démarrera seul à la prochaine demande) ou arrêté ; il ne l'interroge que s'il tourne déjà, pour ne pas le réveiller. « Arrêter » coupe aussi le démarrage à la demande, jusqu'à « Lancer », même si le Mac redémarre. Comme Jarvis, le bot empêche le Mac branché de s'endormir (`JARVIS_KEEP_AWAKE`) : sinon, Jarvis arrêté, plus rien ne le tiendrait éveillé. Mac en veille ou éteint, le bot ne répond pas ; une commande arrivée en retard (plus de 5 minutes) n'est pas exécutée.

Ensuite : `./run_jarvis.sh telegram status` ; `./run_jarvis.sh telegram remove` pour retirer le bot. Journal : `~/Library/Logs/Jarvis-Telegram.log`.

## Ce que Jarvis sait faire

Conversation:

- `Jarvis, tu es là ?` → « Pour vous, Monsieur, toujours. »
- `Explique-moi ce qu'est un trou noir`
- `Je vais déployer en production un vendredi soir`

Informations:

- `Quelle heure est-il ?` · `On est quel jour ?`
- `Quel temps fait-il ?` · `Quel temps fait-il à Lyon demain ?` · `La météo du week-end` · `Il fera beau jeudi ?`
- `À quelle heure se couche le soleil ?` · `Quelle est la qualité de l'air ?`
- `Fais-moi le point` (briefing : heure, météo, agenda, messagerie, alertes)
- `Combien de temps pour aller à l'aéroport de Blagnac ?` · `… à vélo jusqu'à la gare` (OpenStreetMap, hors embouteillages ; départ : `JARVIS_HOME_ADDRESS` ou ta ville)

Recherche sur le web:

- `Quels sont les horaires du Leclerc de Blagnac ?`
- `Il y a une pharmacie de garde ce soir ?`
- `Qui a gagné le dernier match du Stade Toulousain ?`
- `Combien coûte un abonnement Netflix ?`
- `Cherche les dernières nouvelles sur l'intelligence artificielle`
- `Résume cette page https://…` · `Ouvre Wikipédia sur Napoléon`
- `Comment on dit « je suis en retard » en anglais ?`
- `Regarde mon écran` · `Qu'est-ce qu'il y a sur mon écran ?` (le modèle voit les images)

Jarvis prévient (« Un instant, Monsieur, je consulte le réseau. »), interroge le web, lit les premières pages et répond en quelques phrases, sources à l'appui (affichées en liens dans le HUD). Il décide seul de chercher quand la question porte sur une information récente ou locale ; pour le forcer, commence par « cherche … ». Si aucun lieu n'est précisé, il utilise ta ville (`JARVIS_CITY`).

Poste de travail:

- `Lance un diagnostic` · `Niveau de batterie ?`
- `Ouvre Safari` · `Ferme la calculette` · `Ouvre github.com`
- `Monte le volume` · `Volume à 40` · `Coupe le son`
- `Recherche Iron Man sur YouTube` · `Ouvre une recherche sur les réacteurs à arc` (dans le navigateur)
- `Mets l'écran en veille` · `Verrouille le Mac` · `Fais une capture d'écran`
- `Augmente la luminosité` · `Active le mode sombre` · `Coupe le Wi-Fi` · `Active le Bluetooth` · `Active ne pas déranger`
- `Chanson suivante` · `Mets du Daft Punk` · `C'est quoi cette chanson ?` (Spotify, sinon Musique)
- `Où est mon fichier budget 2026 ?` · `Résume le document rapport annuel` (texte, Word, PDF)
- `Allume la lumière du salon` · `Lance le raccourci Bonne nuit` (maison connectée, à travers tes Raccourcis)
- `Mode travail` · `Lance la routine bonne nuit` · `Crée une routine soirée : baisse le son, puis mets de la musique`

Alarmes, minuteurs, rappels:

- `Réveille-moi demain à 7h30`
- `Minuteur de 10 minutes pour les pâtes` · `Annule le minuteur`
- `Rappelle-moi à 15h d'appeler Paul`
- `Quelles sont mes alarmes ?` · `Supprime toutes mes alarmes`
- `Réveille-moi tous les jours de semaine à 6h45` · `Encore 5 minutes` (quand ça sonne) · `Il reste combien sur le minuteur ?`
- `Prends une note : appeler le plombier lundi` · `Ajoute du lait à ma liste de courses` (apps Notes et Rappels, synchronisées sur l'iPhone)

Calendrier:

- `Qu'est-ce que j'ai de prévu demain ?` · `Quels sont mes événements de mardi ?`
- `Planifie une réunion avec Sophie demain à 10h`
- `Crée un événement lundi de 14h à 16h pour réunion client`
- `Suis-je libre cette semaine ?`
- `Supprime les événements de vendredi`
- `Décale le dentiste à 16h` · `Ajoute une réunion d'équipe tous les lundis à 9h`

Mail:

- `Résume mes mails` · `Lis mon dernier mail`
- `Envoie un mail à client@exemple.com pour lui dire que le devis est prêt`
- `Envoie un mail à Paul pour lui dire que je serai en retard` (avec un carnet d'adresses, voir plus bas)
- `Réponds à Paul que c'est d'accord` · `Lis-moi le mail de la banque` · `Cherche les mails de Sophie`
- `Archive le dernier mail` · `Supprime le mail de la newsletter` (avec confirmation ; il faut reconnecter Google une fois pour autoriser le rangement)

Mémoire:

- `Souviens-toi que je prends mon café sans sucre` · `Qu'est-ce que tu sais sur moi ?` · `Oublie que…`
- ce que Jarvis retient lui sert aussi pendant la conversation

Création (en tâche de fond, Jarvis prévient quand c'est prêt):

- `Crée-moi un script Python qui range mes téléchargements` (essayé dans un bac à sable avant d'être livré)
- `Fais-moi un site pour une boulangerie à Colomiers` · `Dessine-moi un logo…` · `Propose-moi une palette…` (relus visuellement)
- `Rédige une lettre de résiliation pour ma salle de sport` · `Fais-moi un CV` (livré en .docx)
- `Ajoute un formulaire de contact à la page` · `Reviens à la version précédente` · `Montre-moi mes créations`

Quand une phrase qui ressemble à un ordre n'est pas reconnue, le modèle choisit l'agent (parmi des actions sans risque) et la phrase est notée : `/incompris` les liste, pour les apprendre à Jarvis.

Notes:

- avant d'envoyer un mail demandé en langage naturel, Jarvis **montre le message final** (objet et corps rédigés) et demande « Dois-je l'envoyer ? ». Réponds « oui » ou « non »
- même confirmation avant de supprimer plusieurs événements ou toutes les alarmes
- les commandes slash (`/sendmail`, `/deleteeventsrange`…) sont explicites et s'exécutent sans confirmation
- quand tu crées un événement sur un créneau déjà pris, Jarvis le signale
- un contenu mail inapproprié (insultes/grossièretés explicites) est bloqué localement, y compris les contournements par lettres séparées
- Jarvis ne prétend jamais avoir fait une action qu'il n'a pas exécutée : s'il lui manque une information, il la demande
- quand une alarme sonne, Jarvis l'annonce à voix haute dans le HUD ; si le HUD est fermé, l'API parle directement sur les haut-parleurs

### Autorisations macOS

À la première utilisation, macOS demande d'autoriser le terminal (ou Python) qui fait tourner Jarvis. Elles se règlent dans Réglages Système › Confidentialité et sécurité :

| Pour | Autorisation |
|---|---|
| luminosité, verrouillage | Accessibilité |
| mode sombre, musique, Notes, Rappels | Automatisation (et Rappels) |
| capture d'écran, « regarde mon écran » | Enregistrement de l'écran |

« Ne pas déranger » passe par deux raccourcis à créer dans l'app Raccourcis : « Activer Ne pas déranger » et « Désactiver Ne pas déranger » (action « Définir la concentration »). Le Bluetooth demande l'outil `blueutil` (`brew install blueutil`).

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
- `phone`: rend Jarvis accessible depuis le téléphone (Tailscale, HTTPS, code d'accès, QR code)
- `service install|start|stop|restart|remove|status`: installe Jarvis comme service macOS à la demande (lancé à la première connexion, arrêté après `JARVIS_IDLE_MINUTES` sans demande ; projet hors du Bureau, des Documents et des Téléchargements)
- `telegram [setup]|status|remove`: bot Telegram qui lance et arrête Jarvis à distance (token de BotFather, appairage par QR code)
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
| `JARVIS_CITY` | `Paris` | ta ville : météo, briefing et recherches locales |
| `OLLAMA_URL` | `http://localhost:11434` | adresse d'Ollama |
| `OLLAMA_MODEL` | `jarvis` | modèle utilisé pour la conversation |
| `JARVIS_BASE_MODEL` | `gemma4:e4b` | modèle de base utilisé par `create` sans GGUF fine-tuné |
| `JARVIS_STRICT_ACTIONS_ONLY` | `0` | `1` : Jarvis refuse tout ce qui n'est pas une action (ancien comportement) |
| `JARVIS_CONFIRM_ACTIONS` | `1` | confirmation avant envoi de mail et suppressions en masse |
| `JARVIS_WEB_SEARCH` | `1` | `0` : Jarvis ne cherche plus lui-même sur le web, il ouvre la recherche dans le navigateur |
| `JARVIS_TTS_ENGINE` | `auto` | synthèse : `auto`, `piper`, `say` (macOS), `browser`, `off` |
| `JARVIS_PIPER_VOICE` | `fr_FR-tom-medium` | voix Piper |
| `JARVIS_TTS_VOICE` | *(auto)* | voix macOS pour le moteur `say` |
| `JARVIS_TTS_RATE` | `1.0` | débit de la voix |
| `JARVIS_STT_ENGINE` | `auto` | reconnaissance : `auto` (puce graphique du Mac, sinon processeur), `mlx`, `whisper`, `browser`, `off` |
| `JARVIS_WHISPER_MODEL` | *(auto)* | `large-v3-turbo` sur la puce graphique, `small` sur le processeur ; aussi `tiny`, `base`, `medium` |
| `JARVIS_WAKE_WORD` | `jarvis` | mot d'activation |
| `JARVIS_STT_VOCABULARY` | *(vide)* | noms propres à bien reconnaître à l'oral (`Blagnac, Toulouse, Leclerc`) ; la ville et les contacts sont ajoutés d'office |
| `JARVIS_HOST` / `JARVIS_PORT` | `127.0.0.1` / `8001` | adresse d'écoute de l'API |
| `JARVIS_ALLOWED_ORIGINS` | *(vide)* | origines web supplémentaires autorisées |
| `JARVIS_REMOTE_SYSTEM_CONTROL` | `0` | `1` : Discord peut piloter le poste |
| `JARVIS_ACCESS_TOKEN` | *(vide)* | code exigé des autres appareils (téléphone) ; vide = accès à distance refusé ; créé par `./run_jarvis.sh phone` |
| `JARVIS_IDLE_MINUTES` | `20` | lancé à la demande par le service, Jarvis s'arrête après ce nombre de minutes sans demande ; `0` = jamais |
| `JARVIS_KEEP_AWAKE` | `secteur` | tant que Jarvis tourne, le Mac ne s'endort pas : `secteur` (branché seulement), `toujours`, ou `0` |
| `TELEGRAM_BOT_TOKEN` | *(vide)* | token du bot Telegram (donné par BotFather) ; écrit par `./run_jarvis.sh telegram` |
| `TELEGRAM_ALLOWED_USERS` | *(vide)* | identifiants des comptes Telegram autorisés ; écrit lors de l'appairage |
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
- l'accès depuis le téléphone passe par ton réseau privé Tailscale, et chaque appel à l'API venu d'un autre appareil doit présenter le code d'accès
- seules les pages servies depuis `localhost` peuvent l'appeler : un site web quelconque ouvert dans ton navigateur ne peut pas faire agir Jarvis
- les requêtes adressées à un autre nom d'hôte sont refusées (protection contre le DNS rebinding)
- les commandes système ne passent jamais par un shell, et les noms d'applications et adresses web sont validés
- lors d'une recherche web, seules des pages publiques sont lues (jamais le réseau local), et leur texte n'est qu'une donnée : le modèle qui le lit ne peut déclencher aucune action
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

- l'API (`Jarvis/API/services/llm.py`), qui y ajoute le contexte en direct (date, heure, et selon la question : agenda, météo, état du poste)
- le train (`Jarvis/train.py`)
- la création du modèle Ollama (via `.Modelfile.generated`)

Le marqueur `{titre}` y est remplacé par `JARVIS_USER_TITLE`.

## Organisation de l'API

Jarvis dirige des **contrôleurs**, des chefs d'équipe qui répartissent le travail entre leurs **agents**, chacun spécialisé dans une tâche précise.

```text
HUD / téléphone / Discord
        │  HTTP
        ▼
routes/   chat · voice · hud · google · security        (la porte d'entrée)
        │
        ▼
JARVIS  core/jarvis.py                                  (le chef)
        │  1. comprend la phrase (core/intents.py)
        │  2. choisit le contrôleur du domaine
        │  3. applique les règles communes : confirmation, accès distant, liaison Google
        ▼
CONTRÔLEURS  controllers/                               (les chefs d'équipe)
   ├── organisation → messagerie, agenda, alarmes, notes, trajets
   ├── ordinateur   → poste, informations, musique, fichiers
   ├── savoir       → web, conversation, mémoire, traduction, vision
   ├── création     → code, design, documents, atelier
   ├── routines     → routines
   └── maison       → maison
        │
        ▼
AGENTS  agents/                                         (les spécialistes)
        │
        ▼
services/   Google · Ollama · voix · météo · recherche web · stockage des alarmes
```

- `Jarvis/API/main.py` : point d'entrée, assemble services, contrôleurs, Jarvis et routes
- `Jarvis/API/core/` : `jarvis.py` (le chef), `controller.py` et `agent.py` (le contrat commun des contrôleurs et des agents), `intents.py` et `phrases.py` (compréhension des commandes et des phrases), `fallback.py` (routage de secours par le modèle et journal des incompris), `messages.py` (format des requêtes)
- `Jarvis/API/controllers/` : `organisation.py`, `ordinateur.py`, `savoir.py`, `creation.py`, `routines.py`, `maison.py` — chacun liste les agents de son équipe
- `Jarvis/API/agents/` : `mail.py`, `calendar.py`, `alarms.py`, `system.py`, `info.py`, `web.py`, `conversation.py` (modèle local, qui appelle l'agent web s'il lui manque une information), `memory.py`, `translate.py`, `vision.py`, `notes.py`, `travel.py`, `music.py`, `files.py`, `code.py`, `design.py`, `document.py`, `atelier.py` (ce que partagent les agents créatifs), `routines.py`, `home.py` ; `briefing.py` fournit le tableau de bord et le contexte en direct
- `Jarvis/API/routes/` : les routes HTTP — `chat.py` (`/api/chat`, `/api/chat/stream`), `voice.py` (`/api/tts`, `/api/stt`), `hud.py` (état, tableau de bord, briefing, alarmes, fichiers du HUD), `google.py` (liaison Google), `security.py` (code d'accès, origines, noms d'hôte)
- `Jarvis/API/services/` : les outils techniques — `google_client.py`, `llm.py`, `voice.py`, `weather.py`, `web_search.py`, `alarm_store.py`, `events.py`, `on_demand.py`
- `Jarvis/API/config.py` et `persona.py` : réglages et ton de Jarvis, partagés par tous

Chaque agent déclare ses actions et ses règles (Google requis, confirmation, interdit à distance) ; une action ne peut appartenir qu'à un seul agent et un seul contrôleur. `GET /api/status` liste les contrôleurs, leurs agents et leurs actions, et le journal montre le chemin de chaque demande avec son temps de réponse :

```text
[JARVIS] organisation › alarmes › set_alarm (0 ms)
[JARVIS] savoir › conversation › 1re phrase 263 ms, réponse 264 ms
```

**Ajouter un agent** :

1. créer `agents/mon_agent.py` avec une classe qui hérite d'`Agent` et déclare ses actions dans `handlers()`
2. l'ajouter à l'équipe d'un contrôleur (`controllers/*.py`), ou créer un nouveau contrôleur et l'ajouter à la liste dans `main.py`
3. faire reconnaître ses phrases dans `core/intents.py`
4. ajouter ses phrases à l'examen des agents (`tests/test_agent_exam.py`)

**L'examen des agents** (`tests/test_agent_exam.py`) : une centaine de phrases de tous les jours, avec l'action que chaque agent doit en tirer, plus celles qui doivent rester à la conversation. C'est l'entraînement des agents : une tournure mal comprise y est ajoutée, puis apprise dans `core/intents.py`, et ne peut plus être oubliée.

**Les agents code et design** travaillent en tâche de fond (le modèle local écrit environ 20 mots par seconde : une à trois minutes par création). Jarvis répond tout de suite, puis annonce le résultat dans le HUD — ou à voix haute sur le Mac si le HUD est fermé. Chaque création passe un contrôle qualité avant d'être livrée (syntaxe du code, page HTML complète, SVG valide, contrastes de la palette) ; si elle échoue, le modèle reçoit l'erreur et corrige une fois. Les créations sont rangées dans `~/Documents/Jarvis` (`JARVIS_CREATIONS_DIR`) et ouvertes sur le poste : le code dans Visual Studio Code, le reste dans le navigateur.

| Demande | Agent |
|---|---|
| « Crée-moi un script Python qui range mes téléchargements » | code |
| « Fais-moi un petit jeu du serpent » | code (page HTML jouable) |
| « Fais-moi un site pour une boulangerie à Colomiers » | design (page web) |
| « Dessine-moi un logo pour mon club de tennis » | design (SVG + aperçu clair, sombre, en petit) |
| « Propose-moi une palette de couleurs pour une appli de méditation » | design (nuancier avec contrastes vérifiés) |
| « Ajoute un formulaire de contact à la page », « corrige-le » | atelier → l'agent qui l'a faite (nouvelle version, l'ancienne est gardée) |
| « Montre-moi mes créations », « ouvre ma dernière création » | atelier |

Le détail de chaque fichier est dans [Jarvis/API/README.md](Jarvis/API/README.md).

## Tests

```bash
./run_jarvis.sh pytest
```

Les tests couvrent le routeur d'intentions, la persona, le pilotage du poste (commandes système simulées), la voix, la recherche web (faux moteur), l'app installable, le bot Telegram (faux Telegram) et l'API de bout en bout avec un faux compte Google. Ils ne touchent ni à ta messagerie, ni à ton agenda, ni à ton ordinateur, ni au réseau.

## Arborescence du projet

```text
.
├── README.md
├── requirements.txt            # API, Google, Discord
├── requirements-voice.txt      # voix locale (Whisper, sur puce graphique ou processeur, + Piper)
├── requirements-train.txt      # fine-tuning MLX
├── requirements-dev.txt        # tests
├── run_jarvis.sh
├── .env.example
├── .env                        # à créer (non versionné)
├── Discord/
│   └── main.py
├── Telegram/
│   └── telegram_bot.py         # bot qui lance et arrête Jarvis à distance
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
    │   ├── main.py                 # assemble tout et démarre le serveur
    │   ├── config.py
    │   ├── persona.py
    │   ├── core/                   # Jarvis, le chef
    │   │   ├── jarvis.py
    │   │   ├── controller.py
    │   │   ├── agent.py
    │   │   ├── intents.py
    │   │   └── messages.py
    │   ├── controllers/            # les chefs d'équipe
    │   │   ├── organisation.py
    │   │   ├── ordinateur.py
    │   │   ├── savoir.py
    │   │   └── creation.py
    │   ├── agents/                 # les spécialistes
    │   │   ├── mail.py
    │   │   ├── calendar.py
    │   │   ├── alarms.py
    │   │   ├── system.py
    │   │   ├── info.py
    │   │   ├── web.py
    │   │   ├── conversation.py
    │   │   ├── code.py
    │   │   ├── design.py
    │   │   ├── atelier.py
    │   │   └── briefing.py
    │   ├── routes/                 # routes HTTP
    │   │   ├── chat.py
    │   │   ├── voice.py
    │   │   ├── hud.py
    │   │   ├── google.py
    │   │   └── security.py
    │   ├── services/               # outils techniques
    │   │   ├── google_client.py
    │   │   ├── llm.py
    │   │   ├── voice.py
    │   │   ├── weather.py
    │   │   ├── web_search.py
    │   │   ├── alarm_store.py
    │   │   ├── events.py
    │   │   └── on_demand.py
    │   ├── phone_setup.py
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
        ├── mic-worklet.js
        ├── manifest.webmanifest    # l'app installable (nom, icônes, plein écran)
        ├── sw.js                   # service worker : l'interface s'ouvre même Mac injoignable
        └── icons/                  # icône de l'app (icon.svg et ses rendus PNG)
```
