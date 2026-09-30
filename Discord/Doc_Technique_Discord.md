# J.A.R.V.I.S - Portage Discord (Documentation technique)

Ce dossier contient le code du bot Discord qui relaie les messages utilisateurs vers l'API Jarvis, puis renvoie la réponse dans Discord.

Ce README se concentre sur l'aspect technique.
Toute la partie installation/configuration est centralisée dans le README racine.

## But du dossier

Le dossier `Discord/` contient l'adaptateur Discord de Jarvis:

- réception des messages Discord
- maintien d'un historique conversationnel court par utilisateur
- appel HTTP vers l'API Jarvis
- renvoi des réponses dans Discord
- commande slash de diagnostic (`/jarvis_status`)

## Fonctionnalités

- Répond uniquement s'il est **mentionné** dans un message.
- Conserve un court contexte de conversation par utilisateur (jusqu'à 20 messages).
- Envoie les longues réponses en plusieurs messages Discord (blocs de 2000 caractères).
- Inclut une commande slash : `/jarvis_status` pour voir si l'API est en ligne.
- Inclut une commande slash : `/google` pour lancer la connexion Google comme sur le web (création du token OAuth côté API).
- Inclut une commande slash : `/description` pour renvoyer la phrase "que peux-tu faire" de l'API web.
- Quand l'API signale que Google n'est pas relié, affiche un message clair: `La liaison Google n'est pas établie. Lancez la commande /google pour connecter votre compte.`
- Gère les confirmations de Jarvis : avant d'envoyer un mail ou de supprimer en masse, Jarvis demande « Dois-je l'envoyer ? » et le bot transmet votre « oui » ou « non » au message suivant.
- Se présente à l'API comme client distant : Jarvis converse et gère mails, agenda et alarmes depuis Discord, mais ne pilote pas l'ordinateur (applications, volume, veille), sauf `JARVIS_REMOTE_SYSTEM_CONTROL=1` côté API.

## Vue d'ensemble des fichiers

### `main.py`
- **Role**: point d'entree du bot Discord.
- **Responsabilite**: configure Discord, valide l'URL API, relaie les messages vers Jarvis et renvoie les reponses.

### Variables d'environnement lues

| Variable | Defaut | Role |
|---|---|---|
| `DISCORD_TOKEN` | aucun | token du bot Discord (obligatoire) |
| `JARVIS_API_URL` | `http://127.0.0.1:8001/api/chat` | endpoint chat de l'API Jarvis |
| `JARVIS_API_TIMEOUT` | `180` | timeout HTTP (secondes) pour les appels a l'API |

### Constantes globales principales

| Constante | Valeur par defaut | Role |
|---|---|---|
| `DEFAULT_JARVIS_API_URL` | `http://127.0.0.1:8001/api/chat` | valeur de secours pour `JARVIS_API_URL` |
| `MAX_HISTORY` | `20` | taille max de l'historique conversationnel par utilisateur |
| `conversations` | `dict[int, list[dict[str, str]]]` | stockage memoire des echanges par utilisateur Discord |
| `pending_actions` | `dict[int, dict]` | action proposee par Jarvis et en attente de confirmation, par utilisateur Discord |
| `GOOGLE_REQUIRED_REPLY` | texte | message affiche quand Google n'est pas relie |


## Utilisation

- Mentionnez le bot dans un message, par exemple:
  - `@Jarvis Bonjour, peux-tu m'aider ?`
    ou
  - `@Jarvis /mail`
- Pour obtenir la liste des commandes, mentionnez `help`, `aide` ou `commandes`.
- Pour obtenir un resume des capacites, demandez `que peux-tu faire ?`.
- Lancez `/jarvis_status` pour verifier la connexion a l'API Jarvis.
- Lancez `/google` pour connecter votre compte Google et creer le token OAuth côté API.
- Lancez `/description` pour obtenir la phrase de capacites de Jarvis (meme logique que sur le web).


## Architecture technique

Fichier principal: `Discord/main.py`

### Fonctions utilitaires

| Fonction | Parametres | Role des parametres | Role |
|---|---|---|---|
| `validate_jarvis_api_url(url)` | `url` | `url`: URL candidate lue depuis l'environnement | valide que l'URL est non vide, avec schema HTTP(S), et qu'elle ne pointe pas vers Ollama (`:11434`) |
| `get_status_url(chat_url)` | `chat_url` | `chat_url`: endpoint chat (`/api/chat`) | derive l'URL de status (`/api/status`) |
| `get_google_connect_url(chat_url)` | `chat_url` | `chat_url`: endpoint chat (`/api/chat`) | derive l'URL de connexion Google (`/api/google/connect`) |
| `trim_history(history)` | `history` | `history`: liste des messages deja stockes | conserve uniquement les `MAX_HISTORY` derniers messages |
| `ask_jarvis(history, message, user_id=None)` | `history`, `message`, `user_id` | `history`: contexte conversationnel; `message`: texte utilisateur; `user_id`: auteur Discord, pour suivre sa confirmation en attente | envoie la requete HTTP a Jarvis (`requests.post`) avec `client: "discord"` et l'action en attente, memorise la nouvelle confirmation demandee, et remplace la reponse par `GOOGLE_REQUIRED_REPLY` si l'API indique `data.google_required` |
| `send_long_message(channel, text)` | `channel`, `text` | `channel`: canal Discord cible; `text`: reponse a envoyer | decoupe le texte en morceaux de 2000 caracteres max et envoie chaque bloc |

### Handlers Discord et commande slash

| Fonction | Parametres | Role des parametres | Role |
|---|---|---|---|
| `on_ready()` | aucun | aucun | synchronise les commandes slash puis journalise l'etat de demarrage |
| `jarvis_status(interaction)` | `interaction` | `interaction`: contexte de la commande slash | teste la connectivite via `/api/status` et renvoie le statut modele/API |
| `google_connect(interaction)` | `interaction` | `interaction`: contexte de la commande slash | lance la connexion Google via `POST /api/google/connect` et renvoie le chemin du token cree |
| `description(interaction)` | `interaction` | `interaction`: contexte de la commande slash | demande a l'API la reponse de capacites via `ask_jarvis([], "que peux tu faire")` |
| `on_message(message)` | `message` | `message`: evenement de message Discord recu | filtre les messages non pertinents, gere le mention parsing, appelle Jarvis, met a jour l'historique et renvoie la reponse |

### Regles de traitement dans `on_message`

1. Ignore les messages provenant de bots.
2. Ignore les commandes slash textuelles (`/`), gerees a part.
3. Ne traite que les messages qui mentionnent explicitement le bot.
4. Nettoie la mention (`<@id>`, `<@!id>`) pour extraire le texte utile.
5. Ajoute le message utilisateur dans l'historique puis tronque avec `trim_history`.
6. Appelle l'API Jarvis avec `ask_jarvis`.
7. Ajoute la reponse assistant a l'historique puis tronque a nouveau.
8. Envoie la reponse en un ou plusieurs blocs avec `send_long_message`.

### Initialisation et securite de demarrage

- Le bot stoppe immediatement si `DISCORD_TOKEN` est vide (`RuntimeError`).
- `JARVIS_API_URL` est validee au demarrage via `validate_jarvis_api_url`.
- Les erreurs de communication API sont journalisees et renvoyees dans une reponse lisible cote Discord.

## Contrat requete/reponse (API)

Corps de requete attendu :

```json
{
  "message": "texte utilisateur",
  "history": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}],
  "temperature": 0.6,
  "client": "discord",
  "pending": null
}
```

Corps de réponse attendu :

```json
{
  "reply": "texte de réponse du bot",
  "pending": null,
  "data": null
}
```

- `pending` : présent quand Jarvis attend une confirmation ; le bot le renvoie tel quel avec le message suivant de l'utilisateur.
- `data.google_required` : vrai quand l'action demande un compte Google qui n'est pas relié.

La commande `/jarvis_status` vérifie `JARVIS_API_URL` en remplacent `/api/chat` par `/api/status`.

La commande `/google` utilise `POST /api/google/connect` pour demarrer OAuth Google et creer le token local (par exemple `Jarvis/API/.google-token.json` selon la configuration).

La commande `/description` appelle le meme endpoint chat (`/api/chat`) avec le message `que peux tu faire`.

Quand l'API repond que Google n'est pas relie (`data.google_required`), le bot affiche a la place:

`La liaison Google n'est pas établie. Lancez la commande /google pour connecter votre compte.`

## Dépannage

- **Bot hors ligne / ne répond pas**
  - Vérifiez le token dans `.env`
  - Vérifiez que le bot est lancé
  - Vérifiez que le bot est invité sur le serveur
- **`/jarvis_status` échoue**
  - Assurez-vous que l'API Jarvis est lancée
  - Vérifiez que `JARVIS_API_URL` pointe bien vers `:8001/api/chat` et pas vers Ollama `:11434`
- **`/google` échoue**
  - Vérifiez que l'API Jarvis est lancée
  - Vérifiez la configuration Google côté API (`GOOGLE_CLIENT_SECRET_FILE`)
  - Vérifiez que le consentement OAuth peut s'ouvrir sur la machine qui exécute l'API
- **Message `La liaison Google n'est pas établie...` pendant une commande mail/calendrier**
  - Lancez la commande `/google` depuis Discord pour créer le token OAuth
  - Puis relancez votre commande (`/mailresume`, etc.)
- **`/description` échoue**
  - Vérifiez que le modèle et l'API Jarvis sont en ligne (testez d'abord `/jarvis_status`)
- **Jarvis refuse d'ouvrir une application ou de régler le volume**
  - C'est voulu : depuis Discord, il ne pilote pas l'ordinateur. Pour l'autoriser, mettez `JARVIS_REMOTE_SYSTEM_CONTROL=1` dans le `.env` de l'API
- **Aucune réponse lors d'une mention**
  - Vérifiez que vous mentionnez explicitement le bot
  - Vérifiez que le message ne commence pas par `/` (les commandes slash sont géré à part)
- **API google non accessible**
  - Vérifiez votre connexion internet
  - Vérifiez que vous êtes connecté à Google (commande `/google` ou interface web Jarvis)
- **Time out**
    - Cela peut être dû aux composants de votre machine, vous pouvez augmenter le timeout