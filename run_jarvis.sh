#!/usr/bin/env bash
set -euo pipefail

# On definit les chemins relatifs aux différents composants du projet pour faciliter les commandes ultérieures. Le script doit être lancé depuis la racine du projet (où il se trouve) pour que les chemins soient corrects.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$ROOT_DIR/Jarvis"
API_DIR="$PROJECT_DIR/API"
INTERFACE_DIR="$PROJECT_DIR/Interface"
VENV_DIR="$ROOT_DIR/.venv"
TRAIN_SCRIPT="$PROJECT_DIR/train.py"
MODELFILE="$PROJECT_DIR/Modelfile"
CONVERT_SCRIPT="$PROJECT_DIR/convert_to_gguf.sh"
PROMPT_FILE="$PROJECT_DIR/system_prompt.txt"
GENERATED_MODELFILE="$PROJECT_DIR/.Modelfile.generated"

MODEL_NAME="jarvis"
TEST_PROMPT="Bonjour Jarvis, fais un resume de mes emails non lus."

print_usage() {
  # Affiche l'aide d'utilisation du script et la liste des commandes disponibles.
  cat <<'EOF'
Usage: ./run_jarvis.sh <command>

Commands:
  setup    Installer les dépendances Python depuis requirements.txt
  api      Lancer l'API Jarvis sur http://localhost:8001
  web      Lancer l'interface web statique sur http://localhost:8000
  train    Lancer le script de fine-tuning (Jarvis/train.py)
  convert  Lancer le script de conversion GGUF (Jarvis/convert_to_gguf.sh)
  create   Créer ou mettre à jour le modèle Ollama avec Jarvis/Modelfile
  test     Lancer un prompt de test rapide sur Ollama
  all      Enchaîner train -> convert -> create -> test
EOF
}

need_cmd() {
  # Vérifie qu'une commande externe est disponible dans le PATH. Pour les outils essentiels comme Ollama, Python, etc.
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Error: '$1' is required but not found in PATH."
    exit 1
  fi
}

activate_venv() {
  # Active l'environnement virtuel Python local du projet.
  if [[ ! -d "$VENV_DIR" ]]; then
    echo "Error: virtual environment not found at $VENV_DIR"
    echo "Create it with: python3 -m venv .venv"
    exit 1
  fi

  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
}

setup_deps() {
  # Installe ou met à jour les dépendances Python du projet.
  activate_venv
  python -m pip install --upgrade pip
  pip install -r "$ROOT_DIR/requirements.txt"
}

run_train() {
  # Lance le script d'entraînement / fine-tuning MLX.
  activate_venv

  if [[ ! -f "$TRAIN_SCRIPT" ]]; then
    echo "Error: train script not found: $TRAIN_SCRIPT"
    exit 1
  fi

  (cd "$PROJECT_DIR" && python train.py)
}

run_api() {
  # Démarre l'API FastAPI/Jarvis sur le port 8001.
  activate_venv

  if [[ ! -f "$API_DIR/main.py" ]]; then
    echo "Error: API entrypoint not found: $API_DIR/main.py"
    exit 1
  fi

  (cd "$API_DIR" && uvicorn main:app --host 0.0.0.0 --port 8001)
}

run_web() {
  # Sert l'interface web statique sur le port 8000.
  if [[ ! -f "$INTERFACE_DIR/test_interface.html" ]]; then
    echo "Error: interface file not found: $INTERFACE_DIR/test_interface.html"
    exit 1
  fi

  (cd "$INTERFACE_DIR" && python3 -m http.server 8000)
}

run_convert() {
  # Lance la conversion du modèle vers le format GGUF.
  activate_venv

  if [[ -x "$CONVERT_SCRIPT" ]]; then
    (cd "$PROJECT_DIR" && "$CONVERT_SCRIPT")
    return
  fi

  if [[ -f "$CONVERT_SCRIPT" ]]; then
    (cd "$PROJECT_DIR" && bash "$CONVERT_SCRIPT")
    return
  fi

  echo "Error: conversion script not found: $CONVERT_SCRIPT"
  exit 1
}

build_generated_modelfile() {
  # Reconstruit un Modelfile temporaire en injectant le prompt partagé.
  if [[ ! -f "$PROMPT_FILE" ]]; then
    echo "Error: shared prompt file not found: $PROMPT_FILE"
    exit 1
  fi

  if [[ ! -s "$PROMPT_FILE" ]]; then
    echo "Error: shared prompt file is empty: $PROMPT_FILE"
    exit 1
  fi

  awk -v prompt_file="$PROMPT_FILE" '
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
  ' "$MODELFILE" > "$GENERATED_MODELFILE"
}

check_modelfile_from_target() {
  # Vérifie que la cible du FROM dans le Modelfile existe bien avant la création Ollama.
  if [[ ! -f "$MODELFILE" ]]; then
    echo "Error: Modelfile not found: $MODELFILE"
    exit 1
  fi

  local from_value
  from_value="$(awk '/^FROM /{print $2; exit}' "$MODELFILE")"

  if [[ -z "$from_value" ]]; then
    echo "Error: no FROM value found in $MODELFILE"
    exit 1
  fi

  if [[ "$from_value" == /* || "$from_value" == ./* || "$from_value" == ../* ]]; then
    local target="$from_value"
    if [[ "$from_value" != /* ]]; then
      target="$PROJECT_DIR/$from_value"
    fi

    if [[ ! -f "$target" && ! -d "$target" ]]; then
      echo "Error: FROM target does not exist: $target"
      echo "Generate or place the GGUF/adapter file, then retry."
      exit 1
    fi
  fi
}

create_model() {
  # Construit le Modelfile généré puis crée ou met à jour le modèle Ollama Jarvis.
  need_cmd ollama
  check_modelfile_from_target

  build_generated_modelfile
  (cd "$PROJECT_DIR" && ollama create "$MODEL_NAME" -f "$GENERATED_MODELFILE")
}

test_model() {
  # Envoie un prompt de validation rapide au modèle Ollama.
  need_cmd ollama
  ollama run "$MODEL_NAME" "$TEST_PROMPT"
}

main() {
  # Point d'entrée du script: route la commande demandée vers la bonne action.
  local cmd="${1:-}"

  case "$cmd" in
    setup)
      setup_deps
      ;;
    api)
      run_api
      ;;
    web)
      run_web
      ;;
    train)
      run_train
      ;;
    convert)
      run_convert
      ;;
    create)
      create_model
      ;;
    test)
      test_model
      ;;
    all)
      run_train
      run_convert
      create_model
      test_model
      ;;
    ""|-h|--help|help)
      print_usage
      ;;
    *)
      echo "Unknown command: $cmd"
      print_usage
      exit 1
      ;;
  esac
}

main "$@"