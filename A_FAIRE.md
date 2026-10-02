# À faire, à lancer, à savoir

Mémo de suivi après la refonte « Iron Man » de Jarvis (30 septembre 2026).
Le mode d'emploi complet est dans le [README](README.md) ; ici, seulement ce qu'il te reste à faire.

## 1. Lancer Jarvis

Sur ce Mac, Jarvis est installé **à la demande** (voir [section 6](#6-déjà-fait-sur-ce-mac)) : rien ne tourne tant que tu ne t'en sers pas. Ouvre simplement `http://localhost:8001/` (ou l'app sur l'iPhone) et il démarre en moins d'une seconde ; il s'arrête seul après 20 min sans demande. Ou lance :

```bash
./run_jarvis.sh start    # ouvre l'interface (et démarre Jarvis s'il ne tourne pas)
```

1. Le HUD s'ouvre sur `http://localhost:8001/`.
2. Clique sur **Initialiser**.
3. Autorise le micro quand le navigateur le demande.
4. Dis : « Jarvis, tu es là ? »

Le projet a été rangé dans `~/Developer/Jarvis` (un lien est resté à l'ancien emplacement, sur le Bureau) : macOS interdit aux services d'arrière-plan de lire le Bureau.

- Après une mise à jour du code ou du `.env` : `./run_jarvis.sh service restart`
- Pour arrêter Jarvis : `./run_jarvis.sh service stop` (il le reste jusqu'à `./run_jarvis.sh service start`, même après un redémarrage) ; pour le désinstaller : `./run_jarvis.sh service remove`
- Journal du service : `~/Library/Logs/Jarvis.log`

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

- [x] **Ta voix, dans ta pièce.** Essayé le 30/09 : Jarvis t'entend et te répond. Il écorchait les noms propres (« Colomiers » devenait « colombier ») : corrigé par un vocabulaire fourni à la reconnaissance.
- [ ] **Les noms propres, avec ta voix.** Le correctif n'a été vérifié qu'avec une voix de synthèse. Essaie « Jarvis, quel temps fait-il à Colomiers ? ». S'il en écorche d'autres, ajoute-les à `JARVIS_STT_VOCABULARY` dans `.env`.
- [ ] **La réactivité.** Mesurée avec une voix de synthèse : environ 1 s pour une action, 2 s pour une question libre. Dis-moi si tu la sens encore lente, et sur quel type de demande.
- [x] **Le téléphone.** Essayé le 01/10 sur l'iPhone, à travers Tailscale : Jarvis entend, comprend et répond à voix haute (voir section 3).
- [ ] **La recherche web, avec ta voix.** « Jarvis, quels sont les horaires du Leclerc de Blagnac ? » : il doit prévenir, chercher, puis donner les horaires, avec les sources en liens sous la réponse.
- [ ] **La voix de Jarvis.** Je n'ai pas pu l'écouter. Si elle ne te plaît pas, voir [section 4](#4-réglages-utiles).
- [ ] **L'autorisation du micro.** Si le HUD affiche « Micro inaccessible » : Réglages Système → Confidentialité et sécurité → Microphone → autorise ton navigateur, puis recharge la page.
- [ ] **Une alarme avec le son.** Dis « Jarvis, minuteur de 10 secondes » : tu dois entendre le carillon et l'annonce. Mes essais ont été faits son coupé.
- [ ] **HUD fermé.** Programme un minuteur de 30 secondes, ferme l'onglet aussitôt : Jarvis doit parler directement sur les haut-parleurs du Mac.
- [ ] **Les notifications d'alarme.** Au premier déclenchement, macOS peut demander d'autoriser les notifications.
- [ ] **« Mets l'écran en veille ».** Jamais exécuté pour de vrai (ça aurait éteint ton écran).
- [ ] **Safari sur le Mac.** Le micro marche dans Safari sur l'iPhone (essayé le 01/10), pas encore essayé dans Safari sur le Mac. Arc repose sur Chromium, le moteur des essais vocaux.

## 3. À configurer

- [x] **Ton `.env`** est créé, avec ta ville (`JARVIS_CITY=Colomiers`) et quelques noms propres à reconnaître (`JARVIS_STT_VOCABULARY=Blagnac, Toulouse, Leclerc`). Les autres options sont dans `.env.example`, dont `JARVIS_USER_TITLE` (« Monsieur » par défaut ; après l'avoir changé : `./run_jarvis.sh create`).
- [ ] **Relier Google** (mails et agenda). Rien n'a été testé sur un vrai compte : il n'y avait pas d'identifiants sur cette machine.
  1. Suis « Configuration Google » dans le README (projet Google Cloud, API Gmail et Calendar, client OAuth « Desktop app »).
  2. Mets le chemin du JSON dans `.env` : `GOOGLE_CLIENT_SECRET_FILE=...`
  3. Relance Jarvis, puis HUD → panneau **Liaisons** → **Connecter**.
  4. Essaie : « Jarvis, résume mes mails », « qu'est-ce que j'ai de prévu demain ? », puis un envoi de mail vers ta propre adresse (il doit te montrer le message et demander « Dois-je l'envoyer ? »).
  5. Pour rester connecté entre deux lancements : `GOOGLE_FORGET_TOKEN_ON_EXIT=0`.
- [x] **Accès depuis l'iPhone** (Tailscale) : fait le 1er octobre. Publication « Serve » autorisée, iPhone appairé par le QR code, conversation à la voix vérifiée depuis le téléphone. Pour t'en servir :
  1. Tailscale allumé sur l'iPhone (app Tailscale, même compte que sur le Mac, interrupteur activé : l'icône VPN apparaît en haut de l'écran). Sans lui, Safari affiche « ne peut pas ouvrir la page ».
  2. Ouvre dans Safari l'adresse Tailscale de ton Mac (affichée par `./run_jarvis.sh phone`, et notée dans `.env`, `JARVIS_ALLOWED_ORIGINS`) (ajoute-la à tes favoris) ; le code d'accès est déjà mémorisé. Safari l'efface après 7 jours sans visite : si Jarvis redemande le code, ou sur un nouvel appareil, rescanne le QR code de `./run_jarvis.sh phone`.
  3. Touche **Initialiser**, puis parle.
  4. Le Mac doit être allumé et éveillé : un MacBook capot fermé est en veille, Jarvis ne répond plus.
- [ ] **Installer l'app Jarvis sur l'iPhone** (prête depuis le 1er octobre ; vérifiée avec le moteur de Safari, pas encore sur ton téléphone) :
  1. Dans Safari, sur Jarvis : bouton **App** en haut, puis **Copier le code**.
  2. **Partager** → **Sur l'écran d'accueil**.
  3. Ouvre l'app depuis l'écran d'accueil : **Coller**, **Valider**, **Initialiser**. Le code n'est demandé qu'une fois (l'app installée ne partage pas les données de Safari).
- [ ] **Joignable à tout moment** :
  - App Tailscale de l'iPhone → ta photo de profil → **VPN On Demand** → **Always** (Wi-Fi et réseau mobile).
  - Laisse le Mac branché et le capot ouvert : tant que Jarvis tourne, il empêche le Mac branché de s'endormir (`JARVIS_KEEP_AWAKE`, section 4). Sur batterie, ton Mac s'endort une minute après l'extinction de l'écran, et Jarvis ne répond plus.
- [x] **Bot Telegram** : `@Jarvis_TelOrdi_Bot`, appairé avec ton compte le 2 octobre, en service sur le Mac. `/aide` donne les commandes ; « Arrêter » essayé depuis ton téléphone.
- [ ] **Régénérer le token du bot** : il a été collé dans une conversation. Dans @BotFather : `/revoke` → choisis le bot → copie le nouveau token → `./run_jarvis.sh telegram` (l'appairage est conservé).
- [x] **Sortir le projet du Bureau** et installer le service : fait (`~/Developer/Jarvis`, environnement Python recréé).
- [ ] **Carnet d'adresses** : `cp Jarvis/API/contacts.example.json Jarvis/API/contacts.json`, puis mets-y tes contacts. Tu pourras dire « envoie un mail à Paul… ».
- [ ] **Bot Discord** : son code a été adapté (confirmations, pas de pilotage du Mac à distance) mais pas relancé, faute de token. À tester avec `python3 Discord/main.py`.

## 4. Réglages utiles

| Si… | Alors… |
|---|---|
| la voix ne te plaît pas | `JARVIS_TTS_ENGINE=say` (voix macOS). Pour mieux : télécharge une voix « Premium » dans Réglages Système → Accessibilité → Contenu énoncé, puis mets son nom exact (donné par `say -v '?'`) dans `JARVIS_TTS_VOICE` |
| tu veux une autre voix Piper | `JARVIS_PIPER_VOICE=fr_FR-upmc-medium` et `JARVIS_PIPER_SPEAKER=1`, puis `./run_jarvis.sh voice` |
| il parle trop vite ou trop lentement | `JARVIS_TTS_RATE=0.9` ou `1.1` |
| il écorche un nom propre (ville, enseigne, prénom) | ajoute-le à `JARVIS_STT_VOCABULARY` dans `.env` |
| il comprend mal en général | sur ce Mac, il utilise déjà le plus précis (large-v3-turbo, sur la puce graphique) ; vérifie le micro et le bruit ambiant |
| il réagit aux bruits, ou coupe tes phrases | `MIN_THRESHOLD` et `SILENCE_MS` (600 ms de silence clôt une phrase) en haut de `Jarvis/Interface/voice.js` |
| il repasse en veille trop vite | `ATTENTIVE_MS` en haut de `Jarvis/Interface/hud.js` |
| il répond lentement | vérifie `ollama ps` (un autre modèle chargé ralentit tout) ; ou modèle plus léger : `JARVIS_BASE_MODEL=gemma3:4b` puis `./run_jarvis.sh create` |
| tu veux l'ancien comportement strict | `JARVIS_STRICT_ACTIONS_ONLY=1` |
| tu ne veux plus de confirmation avant envoi | `JARVIS_CONFIRM_ACTIONS=0` |
| tu ne veux pas qu'il aille sur le web tout seul | `JARVIS_WEB_SEARCH=0` (il ouvrira la recherche dans le navigateur) |
| tu ne veux pas que Jarvis empêche la veille du Mac branché | `JARVIS_KEEP_AWAKE=0` ; ou `toujours` pour qu'il réponde aussi sur batterie (elle se videra plus vite) |

Après un changement dans `.env`, relance Jarvis : `./run_jarvis.sh service restart`.

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
- voix Piper dans `Jarvis/API/voices/` ; reconnaissance Whisper large-v3-turbo (puce graphique) et small (repli) dans `~/.cache/huggingface/`
- modèle Ollama `jarvis` créé à partir de `gemma4:e4b`
- `.env` avec ta ville, ton vocabulaire, le code d'accès du téléphone et l'adresse Tailscale
- service Jarvis **à la demande** (`fr.jarvis.assistant`) : seul le bot Telegram (`fr.jarvis.telegram`, 28 Mo) tourne en permanence
- 200 tests automatiques qui passent : `./run_jarvis.sh pytest`

Rien de tout cela n'est versionné (voir `.gitignore`).

## 7. Limites connues

- **Pas d'interruption à la voix** : pendant qu'il parle, le micro est coupé pour qu'il ne s'entende pas. Pour le faire taire : `Échap` ou un clic sur le réacteur.
- **Les actions passent par des formulations reconnues** (`Jarvis/API/intents.py`). Le modèle de langage ne déclenche rien lui-même : si une phrase n'est pas comprise, Jarvis demande de reformuler. Pour lui apprendre une tournure, ajoute-la au parseur concerné, avec un test dans `tests/test_intents.py`.
- **Mails** : lecture des non lus et du dernier reçu, envoi. Pas de réponse, de transfert ni de suppression.
- **Météo** : aujourd'hui et demain seulement.
- **Recherche web** : elle passe par DuckDuckGo, sans clé, et prend 4 à 6 secondes, dont 2,5 à 3,5 pour que le modèle lise les pages et commence sa réponse. Pour aller plus vite, il faudrait un modèle plus petit (moins juste). Certains sites ne se laissent pas lire (pages construites en JavaScript, blocages) : Jarvis dit alors ce qu'il a trouvé et ce qui manque. La réponse vaut ce que valent les pages consultées, d'où les sources affichées.
- **Calcul** : c'est le modèle qui calcule, et il se trompe parfois sur une multiplication.
- **Mémoire** : la conversation en cours, rien d'un lancement à l'autre.
- **Pilotage du poste** : complet sur macOS ; Linux et Windows sont prévus dans le code mais jamais essayés.
- **Reconnaissance du navigateur** (repli si Whisper n'est pas installé) : écrite mais jamais essayée.
- **Téléphone** : l'écoute s'arrête quand l'écran se verrouille ou que Safari passe en arrière-plan. Si le HUD est ouvert à la fois sur le Mac et sur le téléphone, les deux annoncent les alarmes.

## 8. Dépannage

| Symptôme | Piste |
|---|---|
| « Noyau injoignable » à l'ouverture | l'API ne tourne pas : `./run_jarvis.sh start` |
| « address already in use » | une autre instance tourne : `kill $(lsof -nP -t -iTCP:8001 -sTCP:LISTEN)` |
| « Mes fonctions conversationnelles sont hors ligne » | Ollama est fermé, ou le modèle manque : `ollama list`, puis `./run_jarvis.sh create` |
| pas de son | bouton **Voix** du HUD ; sinon `./run_jarvis.sh voice` |
| il n'entend rien | bouton **Micro** du HUD ; autorisation du micro (section 2) |
| « La liaison Google n'est pas établie » | section 3 |
| le téléphone demande un code d'accès | rescanne le QR code : `./run_jarvis.sh phone` (le code est dans `.env`, `JARVIS_ACCESS_TOKEN`) |
| « Serve is not enabled on your tailnet » | ouvre le lien affiché par Tailscale et accepte : la commande reprend d'elle-même |
| « Safari ne peut pas ouvrir la page » | Tailscale n'est pas activé sur l'iPhone : app Tailscale, même compte que sur le Mac, interrupteur activé, puis rescanne. `./run_jarvis.sh phone` le signale |
| le téléphone n'affiche rien | Tailscale allumé sur le téléphone ? Jarvis lancé sur le Mac (`./run_jarvis.sh service status`) ? |
| l'app dit « Jarvis est injoignable » | le Mac dort (capot fermé, ou sur batterie), Tailscale est coupé sur l'iPhone, ou Jarvis est arrêté : l'app se reconnecte seule dès que c'est réglé |
| le bot Telegram ne répond pas | le Mac dort ou est éteint ; sinon `./run_jarvis.sh telegram status` et `~/Library/Logs/Jarvis-Telegram.log` |
| le bot dit « message reçu en retard » | la commande a attendu plus de 5 min (Mac en veille) : renvoie-la |
| l'app installée redemande le code | normal la première fois : bouton **App** dans Safari → **Copier le code**, puis **Coller** dans l'app |

## 9. Publier

Le travail est sur la branche `feat/jarvis-iron-man`, pas sur `main`. Commence par `git status` : tout ce qui n'est pas encore commité doit l'être avant la fusion.

```bash
git checkout main
git merge feat/jarvis-iron-man
git push
```

Avant de pousser, vérifie avec `git status` qu'aucun fichier secret n'apparaît. `.env`, le secret client Google, le token et `contacts.json` sont déjà exclus par `.gitignore`.
