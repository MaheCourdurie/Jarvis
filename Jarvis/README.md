# Jarvis - Documentation technique

## But du dossier

Ce dossier contient le cœur technique du projet Jarvis:

- l'entraînement du modèle local
- la conversion vers le format GGUF
- le prompt système partagé
- l'API FastAPI qui orchestre les actions métier
- les scripts d'aide pour générer et tester le modèle Ollama

## Fichiers principaux

### `Modelfile`
- **Role**: base Ollama utilisée pour créer le modèle `jarvis`.
- **Contenu**: chemin vers le GGUF, prompt système, paramètres de génération.
- **Utilisation**: `ollama create jarvis -f Modelfile`. 

### `conversations.jsonl`
- **Role**: dataset conversationnel pour le fine-tuning MLX.
- **Utilisation**: lu directement par `train.py`.

### `system_prompt.txt`
- **Role**: prompt système de référence partagé entre entraînement et inférence.
- **Utilisation**: chargé par l'API et injecté dans le Modelfile final.

### `train.py`
- **Role**: lance le fine-tuning MLX LoRA, puis fusionne les adaptateurs avec le modèle de base.
- **Paramètres**: le script lit sa configuration dans les constantes en haut du fichier et dans `system_prompt.txt` / `conversations.jsonl`.

#### Fonctions principales

| Fonction | Paramètres | Rôle |
|---|---|---|
| `load_system_prompt()` | aucun | charge le prompt systeme partage depuis `system_prompt.txt` ou renvoie un prompt par defaut |
| `prepare_dataset()` | aucun | convertit `conversations.jsonl` au format MLX, remplace le système prompt si besoin et crée `mlx-data/train.jsonl` + `mlx-data/valid.jsonl` |
| `run_training()` | aucun | lance `python -m mlx_lm lora` avec les paramètres de configuration du script |
| `fuse_model()` | aucun | fusionne les adaptateurs LoRA avec le modèle de base et écrit le modèle final dans `jarvis-fused/` |
| `test_model()` | aucun | envoie quelques prompts de test au modèle fusionné pour vérifier le comportement |

#### Paramètres de configuration du script

| Constante | Rôle |
|---|---|
| `MODEL_NAME` | nom du modèle de base téléchargé depuis Hugging Face |
| `DATASET_PATH` | chemin vers le dataset JSONL d'entraînement |
| `MLX_DATA_DIR` | dossier de sortie pour les données train/valid |
| `ADAPTER_DIR` | dossier de sortie des adaptateurs LoRA |
| `FUSED_DIR` | dossier de sortie du modèle fusionné |
| `ITERS` | nombre d'itérations d'entraînement |
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

Points cles recents sur le flux mail naturel:

- les formulations indirectes sont interpretees (`pour lui dire que ...`, `dire qu'il ...`, `et lui dire ...`)
- si l'adresse a deja ete mentionnee, une reponse de suivi (`message ...`, `objet ...`, `sujet ...`) peut reutiliser ce destinataire
- si le message est absent, l'API demande des precisions et n'envoie rien
- l'objet auto-genere est force a 1-2 mots maximum, avec filtrage des sorties verbeuses du modele
- en mode `auto_polish`, si le modele recopie le brouillon brut, l'API force un fallback de corps formate (salutation + message + cloture)
- les contenus inappropries (insultes/grossieretes explicites) sont bloques avant l'appel au provider mail
- les contournements avec des lettres separees (`z i z i`, `sui ci der`, etc.) sont aussi detectes via une normalisation compacte
- les demandes de support `help` / `aide` / `commandes` renvoient directement la liste complete des commandes
- les demandes `que peux-tu faire` (et variantes proches) renvoient un resume des capacites (emails, calendrier, alarmes)
- ces deux reponses de support sont traitees avant le fallback strict/permissif (refus hors perimetre ou appel Ollama)

## Sous-dossier `Interface/`

Contient l'interface web de test du model:

- `test_interface.html`
- `test_interface.js`
- `test_interface.css`