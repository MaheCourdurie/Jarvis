# Jarvis - Documentation technique

## But du dossier

Ce dossier contient le cœur technique du projet Jarvis:

- l'entraînement du modèle local
- la conversion vers le format GGUF
- le prompt système partagé (la personnalité de Jarvis)
- l'API FastAPI qui orchestre les actions métier, la voix et la conversation
- le HUD, l'interface holographique servie par l'API
- les scripts d'aide pour générer et tester le modèle Ollama

## Fichiers principaux

### `Modelfile`
- **Role**: base Ollama utilisée pour créer le modèle `jarvis`.
- **Contenu**: chemin vers le GGUF fine-tuné, paramètres de génération.
- **Utilisation**: `./run_jarvis.sh create`. Si le GGUF fine-tuné existe, il est utilisé ; sinon la ligne `FROM` est remplacée par le modèle de base `JARVIS_BASE_MODEL` (`gemma4:e4b` par défaut) et les jetons d'arrêt propres au modèle fine-tuné sont retirés. Dans les deux cas, le prompt système est injecté.

### `conversations.jsonl`
- **Role**: dataset conversationnel pour le fine-tuning MLX.
- **Contenu**: une centaine d'échanges dans le ton de Jarvis : vouvoiement, « Monsieur », flegme et humour discret, réponses courtes faites pour être dites, culture générale, et refus de prétendre avoir exécuté une action. Les exemples ne contiennent pas de prompt système : `train.py` l'ajoute.
- **Utilisation**: lu directement par `train.py`.

### `system_prompt.txt`
- **Role**: prompt système de référence partagé entre entraînement et inférence. Il définit la personnalité (majordome britannique, vouvoiement), le style (phrases courtes, sans markdown, faites pour la voix) et les règles absolues (ne jamais affirmer avoir agi, ne jamais inventer de données).
- **Utilisation**: chargé par l'API et injecté dans le Modelfile final. Le marqueur `{titre}` est remplacé par la formule d'appel (`JARVIS_USER_TITLE`, « Monsieur » par défaut).

### `train.py`
- **Role**: lance le fine-tuning MLX LoRA, puis fusionne les adaptateurs avec le modèle de base.
- **Paramètres**: le script lit sa configuration dans les constantes en haut du fichier et dans `system_prompt.txt` / `conversations.jsonl`.

#### Fonctions principales

| Fonction | Paramètres | Rôle |
|---|---|---|
| `load_user_title()` | aucun | lit la formule d'appel (`JARVIS_USER_TITLE`) dans l'environnement ou le `.env` |
| `load_system_prompt()` | aucun | charge le prompt systeme partage depuis `system_prompt.txt` et y inscrit la formule d'appel |
| `prepare_dataset()` | aucun | convertit `conversations.jsonl` au format « chat » de MLX (`{"messages": [...]}`), ajoute le prompt système, mélange et crée `mlx-data/train.jsonl` + `mlx-data/valid.jsonl` |
| `run_training()` | aucun | lance `python -m mlx_lm lora` avec `--mask-prompt` : l'apprentissage porte sur les réponses de Jarvis, pas sur le prompt système répété |
| `local_model_path()` | aucun | complète la copie locale du modèle de base, exigée par `mlx_lm fuse` |
| `fuse_model()` | aucun | fusionne les adaptateurs LoRA avec le modèle de base et écrit le modèle final dans `jarvis-fused/` |
| `test_model()` | aucun | envoie quelques prompts de test au modèle fusionné pour vérifier le comportement |

Le format « chat » laisse `mlx_lm` appliquer le gabarit de conversation du modèle : l'entraînement voit donc exactement la mise en forme qu'Ollama utilisera à l'inférence.

#### Paramètres de configuration du script

| Constante | Rôle |
|---|---|
| `MODEL_NAME` | nom du modèle de base téléchargé depuis Hugging Face (surchargeable par `JARVIS_TRAIN_MODEL`) |
| `DATASET_PATH` | chemin vers le dataset JSONL d'entraînement |
| `MLX_DATA_DIR` | dossier de sortie pour les données train/valid |
| `ADAPTER_DIR` | dossier de sortie des adaptateurs LoRA |
| `FUSED_DIR` | dossier de sortie du modèle fusionné |
| `ITERS` | nombre d'itérations d'entraînement (surchargeable par `JARVIS_TRAIN_ITERS`) |
| `BATCH_SIZE` | taille de lot |
| `LEARNING_RATE` | taux d'apprentissage |
| `LORA_LAYERS` | nombre de couches adaptées |
| `STEPS_PER_EVAL` | fréquence d'évaluation |
| `SAVE_EVERY` | fréquence de sauvegarde |

### `convert_to_gguf.sh`
- **Role**: convertit le modèle fusionné en GGUF puis le quantifie pour Ollama.
- **Paramètres**: utilise des variables d'environnement optionnelles comme `FUSED_DIR`, `EXPORT_DIR`, `F16_GGUF`, `Q4_GGUF`, `GGUF_QUANT`, `LLAMA_CPP_DIR`, `DEQUANT_FUSED_DIR`.
- **Résultat**: génère un GGUF FP16 puis un GGUF quantifié.

#### Fonctions principales

| Fonction | Paramètres | Rôle |
|---|---|---|
| `log()` | message implicite via `$*` | affiche un message de progression avec préfixe `convert` |
| `need_cmd()` | nom de commande | vérifie qu'une commande existe dans le PATH |
| `ensure_torch()` | aucun | installe `torch` si le module n'est pas disponible |
| `prepare_dequantized_model()` | aucun | déquantifie le modèle fusionné vers un dossier FP16 temporaire |
| `resolve_converter()` | aucun | cherche `convert_hf_to_gguf.py` dans les emplacements connus |
| `resolve_quantize()` | aucun | cherche le binaire `llama-quantize` dans les emplacements connus |
| `bootstrap_llama_cpp()` | aucun | clone et compile `llama.cpp` si les outils manquent |

#### Étapes du script

| Étape | Rôle |
|---|---|
| verification du modèle fusionné | stoppe si `FUSED_DIR` n'existe pas |
| selection de Python | choisit `python` ou `python3` |
| préparation de l'export | crée `EXPORT_DIR` |
| résolution des outils llama.cpp | récupère le convertisseur et le quantizer |
| conversion FP16 | transforme le modèle fusionné en GGUF non quantifié |
| quantification | génère le GGUF final au format `GGUF_QUANT` |

## Sous-dossier `API/`

Ce sous-dossier contient l'API applicative. La documentation detaillee de chaque fichier se trouve dans [API/README.md](API/README.md).

Points cles:

- le routeur d'intentions (`intents.py`) reconnaît les actions ; tout le reste est une conversation, confiée au modèle
- chaque module renvoie un texte affiché et une version orale, dans le ton de Jarvis (`persona.py`)
- le modèle ne déclenche jamais d'action : s'il prétend en avoir exécuté une, sa réponse est remplacée (`llm.py`)
- les envois de mail et les suppressions en masse demandés en langage naturel passent par une confirmation
- la voix est locale : synthèse Piper (ou `say` sur macOS), reconnaissance Whisper (`voice.py`)
- les alarmes sont annoncées à voix haute, par le HUD s'il est ouvert, sinon par l'API (`alarm_actions.py`, `events.py`)
- l'API n'accepte que les requêtes de ce poste (`main.py`)

## Sous-dossier `Interface/`

Contient le HUD, l'interface de Jarvis (servie par l'API sur `http://localhost:8001/`):

- `index.html` : structure (séquence de démarrage, réacteur, panneaux, journal)
- `hud.css` : thème holographique
- `hud.js` : dialogue avec l'API, panneaux, états du HUD
- `core.js` : réacteur central animé
- `voice.js` : micro, détection de parole, lecture de la voix
- `mic-worklet.js` : capture audio

Le détail est dans [Doc_Technique_Train.md](Doc_Technique_Train.md).
