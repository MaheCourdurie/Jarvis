# À faire, à lancer, à savoir

Mémo de suivi après la refonte « Iron Man » de Jarvis (30 septembre 2026).
Le mode d'emploi complet est dans le [README](README.md) ; ici, seulement ce qu'il te reste à faire.

## 1. Lancer Jarvis

Sur ce Mac, tout est déjà installé (voir [section 6](#6-déjà-fait-sur-ce-mac)). Il suffit de :

```bash
./run_jarvis.sh start
```

1. Le HUD s'ouvre sur `http://localhost:8001/`.
2. Clique sur **Initialiser**.
3. Autorise le micro quand le navigateur le demande.
4. Dis : « Jarvis, tu es là ? »

Pour l'arrêter : `Ctrl+C` dans le terminal.

Ollama doit tourner (l'application Ollama ouverte suffit ; sinon `ollama serve` dans un autre terminal).

Sur une autre machine, il faut d'abord installer :

```bash
python3 -m venv .venv
./run_jarvis.sh setup      # dépendances + voix + reconnaissance (~550 Mo)
./run_jarvis.sh create     # modèle Ollama "jarvis" (~6,6 Go)
./run_jarvis.sh start
```

## 2. À vérifier toi-même

Ces points n'ont pas pu être testés sans toi : ils demandent tes oreilles, ta voix ou tes comptes.

- [ ] **Ta voix, dans ta pièce.** La reconnaissance n'a été essayée qu'avec une voix de synthèse. Essaie « Jarvis, quelle heure est-il ? », « Jarvis, lance un diagnostic », puis une question libre.
- [ ] **La voix de Jarvis.** Je n'ai pas pu l'écouter. Si elle ne te plaît pas, voir [section 4](#4-réglages-utiles).
- [ ] **L'autorisation du micro.** Si le HUD affiche « Micro inaccessible » : Réglages Système → Confidentialité et sécurité → Microphone → autorise ton navigateur, puis recharge la page.
- [ ] **Une alarme avec le son.** Dis « Jarvis, minuteur de 10 secondes » : tu dois entendre le carillon et l'annonce. Mes essais ont été faits son coupé.
- [ ] **HUD fermé.** Programme un minuteur de 30 secondes, ferme l'onglet aussitôt : Jarvis doit parler directement sur les haut-parleurs du Mac.
- [ ] **Les notifications d'alarme.** Au premier déclenchement, macOS peut demander d'autoriser les notifications.
- [ ] **« Mets l'écran en veille ».** Jamais exécuté pour de vrai (ça aurait éteint ton écran).
- [ ] **Safari.** L'interface a été vérifiée avec son moteur (WebKit), mais pas le micro. Arc repose sur Chromium, le moteur des essais vocaux.

## 3. À configurer

- [ ] **Créer ton `.env`** : `cp .env.example .env`, puis règle au moins `JARVIS_USER_TITLE` (« Monsieur » par défaut) et `JARVIS_CITY`. Après avoir changé la formule d'appel : `./run_jarvis.sh create`.
- [ ] **Relier Google** (mails et agenda). Rien n'a été testé sur un vrai compte : il n'y avait pas d'identifiants sur cette machine.
  1. Suis « Configuration Google » dans le README (projet Google Cloud, API Gmail et Calendar, client OAuth « Desktop app »).
  2. Mets le chemin du JSON dans `.env` : `GOOGLE_CLIENT_SECRET_FILE=...`
  3. Relance Jarvis, puis HUD → panneau **Liaisons** → **Connecter**.
  4. Essaie : « Jarvis, résume mes mails », « qu'est-ce que j'ai de prévu demain ? », puis un envoi de mail vers ta propre adresse (il doit te montrer le message et demander « Dois-je l'envoyer ? »).
  5. Pour rester connecté entre deux lancements : `GOOGLE_FORGET_TOKEN_ON_EXIT=0`.
- [ ] **Carnet d'adresses** : `cp Jarvis/API/contacts.example.json Jarvis/API/contacts.json`, puis mets-y tes contacts. Tu pourras dire « envoie un mail à Paul… ».
- [ ] **Bot Discord** : son code a été adapté (confirmations, pas de pilotage du Mac à distance) mais pas relancé, faute de token. À tester avec `python3 Discord/main.py`.

## 4. Réglages utiles

| Si… | Alors… |
|---|---|
| la voix ne te plaît pas | `JARVIS_TTS_ENGINE=say` (voix macOS). Pour mieux : télécharge une voix « Premium » dans Réglages Système → Accessibilité → Contenu énoncé, puis mets son nom exact (donné par `say -v '?'`) dans `JARVIS_TTS_VOICE` |
| tu veux une autre voix Piper | `JARVIS_PIPER_VOICE=fr_FR-upmc-medium` et `JARVIS_PIPER_SPEAKER=1`, puis `./run_jarvis.sh voice` |
| il parle trop vite ou trop lentement | `JARVIS_TTS_RATE=0.9` ou `1.1` |
| il comprend mal | `JARVIS_WHISPER_MODEL=medium` puis `./run_jarvis.sh voice` (plus précis, plus lent) |
| il réagit aux bruits, ou coupe tes phrases | `MIN_THRESHOLD` et `SILENCE_MS` en haut de `Jarvis/Interface/voice.js` |
| il repasse en veille trop vite | `ATTENTIVE_MS` en haut de `Jarvis/Interface/hud.js` |
| il répond lentement | vérifie `ollama ps` (un autre modèle chargé ralentit tout) ; ou modèle plus léger : `JARVIS_BASE_MODEL=gemma3:4b` puis `./run_jarvis.sh create` |
| tu veux l'ancien comportement strict | `JARVIS_STRICT_ACTIONS_ONLY=1` |
| tu ne veux plus de confirmation avant envoi | `JARVIS_CONFIRM_ACTIONS=0` |

Après un changement dans `.env`, relance `./run_jarvis.sh start`.

## 5. Facultatif

- [ ] **Entraîner ton propre modèle** : `./run_jarvis.sh all` (plusieurs heures, il faut `git` et `cmake`).
  - Le jeu de données est réécrit dans le nouveau ton et le script a été vérifié de bout en bout, mais seulement sur un petit modèle et 6 itérations. Le vrai entraînement sur Llama 3.1 8B n'a pas été lancé, ni la conversion GGUF.
  - Dès que `Jarvis/export/jarvis-q4.gguf` existe, `./run_jarvis.sh create` l'utilise à la place de `gemma4:e4b`.
  - Compare avant d'adopter. Si le résultat est moins bon, supprime le GGUF et relance `create`.
- [ ] **Le GGUF sur Drive** porte l'ancienne personnalité. Remplace-le après un nouvel entraînement, ou retire le lien du README.
- [ ] **`Marketing/report.md`** n'a pas été touché : il décrit encore l'ancien périmètre (mails, agenda, alarmes), sans la voix ni le HUD.
- [ ] **Une capture du HUD dans le README**, pour le portfolio.

## 6. Déjà fait sur ce Mac

- `.venv` créé, avec toutes les dépendances (API, voix, entraînement, tests)
- voix Piper dans `Jarvis/API/voices/` et modèle Whisper `small` dans `~/.cache/huggingface/`
- modèle Ollama `jarvis` créé à partir de `gemma4:e4b`
- 124 tests automatiques qui passent : `./run_jarvis.sh pytest`

Rien de tout cela n'est versionné (voir `.gitignore`).

## 7. Limites connues

- **Pas d'interruption à la voix** : pendant qu'il parle, le micro est coupé pour qu'il ne s'entende pas. Pour le faire taire : `Échap` ou un clic sur le réacteur.
- **Les actions passent par des formulations reconnues** (`Jarvis/API/intents.py`). Le modèle de langage ne déclenche rien lui-même : si une phrase n'est pas comprise, Jarvis demande de reformuler. Pour lui apprendre une tournure, ajoute-la au parseur concerné, avec un test dans `tests/test_intents.py`.
- **Mails** : lecture des non lus et du dernier reçu, envoi. Pas de réponse, de transfert ni de suppression.
- **Météo** : aujourd'hui et demain seulement.
- **Mémoire** : la conversation en cours, rien d'un lancement à l'autre.
- **Pilotage du poste** : complet sur macOS ; Linux et Windows sont prévus dans le code mais jamais essayés.
- **Reconnaissance du navigateur** (repli si Whisper n'est pas installé) : écrite mais jamais essayée.

## 8. Dépannage

| Symptôme | Piste |
|---|---|
| « Noyau injoignable » à l'ouverture | l'API ne tourne pas : `./run_jarvis.sh start` |
| « address already in use » | une autre instance tourne : `kill $(lsof -nP -t -iTCP:8001 -sTCP:LISTEN)` |
| « Mes fonctions conversationnelles sont hors ligne » | Ollama est fermé, ou le modèle manque : `ollama list`, puis `./run_jarvis.sh create` |
| pas de son | bouton **Voix** du HUD ; sinon `./run_jarvis.sh voice` |
| il n'entend rien | bouton **Micro** du HUD ; autorisation du micro (section 2) |
| « La liaison Google n'est pas établie » | section 3 |

## 9. Publier

Le travail est commité sur la branche `feat/jarvis-iron-man`, pas sur `main`.

```bash
git checkout main
git merge feat/jarvis-iron-man
git push
```

Avant de pousser, vérifie avec `git status` qu'aucun fichier secret n'apparaît. `.env`, le secret client Google, le token et `contacts.json` sont déjà exclus par `.gitignore`.
