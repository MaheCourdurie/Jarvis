#!/usr/bin/env bash
set -euo pipefail

# On definit les chemins relatifs aux différents composants du projet pour faciliter les commandes ultérieures. Le script doit être lancé depuis la racine du projet (où il se trouve) pour que les chemins soient corrects.
# Chemin physique (pwd -P) : le service ne doit jamais passer par un lien posé sur le Bureau.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
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
TEST_PROMPT="Bonjour Jarvis. Présente-toi en une phrase."
# Modèle de base utilisé quand aucun GGUF fine-tuné n'est présent (surchargeable dans .env).
DEFAULT_BASE_MODEL="gemma4:e4b"
DEFAULT_PIPER_VOICE="fr_FR-tom-medium"
SERVICE_LABEL="fr.jarvis.assistant"
SERVICE_PLIST="$HOME/Library/LaunchAgents/$SERVICE_LABEL.plist"
SERVICE_LOG="$HOME/Library/Logs/Jarvis.log"

print_usage() {
  # Affiche l'aide d'utilisation du script et la liste des commandes disponibles.
  cat <<'EOF'
Usage: ./run_jarvis.sh <command>

Commands:
  setup    Installer les dépendances Python et les modèles de voix
  start    Lancer Jarvis (API + HUD) et ouvrir l'interface dans le navigateur
  api      Lancer l'API Jarvis (elle sert aussi le HUD) sur http://localhost:8001
  web      Servir le HUD seul sur http://localhost:8000 (l'API doit tourner à part)
  create   Créer ou mettre à jour le modèle Ollama "jarvis"
           (GGUF fine-tuné s'il existe, sinon modèle de base JARVIS_BASE_MODEL)
  voice    Télécharger les modèles de voix (Piper + Whisper)
  phone    Rendre Jarvis accessible depuis le téléphone (Tailscale, HTTPS, code d'accès)
  service  Faire tourner Jarvis en permanence : service install | restart | remove | status (macOS)
  test     Lancer un prompt de test rapide sur Ollama
  pytest   Lancer les tests automatiques
  train    Lancer le script de fine-tuning (Jarvis/train.py)
  convert  Lancer le script de conversion GGUF (Jarvis/convert_to_gguf.sh)
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

env_value() {
  # Lit une variable de configuration : environnement, puis fichier .env, puis valeur par défaut.
  local key="$1" default="$2" value="${!1:-}"
  if [[ -z "$value" && -f "$ROOT_DIR/.env" ]]; then
    value="$(sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" "$ROOT_DIR/.env" | tail -n 1 | sed 's/[[:space:]]#.*$//; s/^"//; s/"$//; s/[[:space:]]*$//')"
  fi
  echo "${value:-$default}"
}

setup_voice() {
  # Télécharge la voix Piper et le modèle Whisper (une seule fois, ~550 Mo).
  activate_venv
  local voice voices_dir
  voice="$(env_value JARVIS_PIPER_VOICE "$DEFAULT_PIPER_VOICE")"
  voices_dir="$(env_value JARVIS_VOICES_DIR "$API_DIR/voices")"

  if [[ -f "$voices_dir/$voice.onnx" ]]; then
    echo "[voice] Voix Piper déjà présente: $voice"
  else
    echo "[voice] Téléchargement de la voix Piper: $voice"
    mkdir -p "$voices_dir"
    python -m piper.download_voices --download-dir "$voices_dir" "$voice" \
      || echo "[voice] Voix Piper indisponible: Jarvis utilisera la voix du système."
  fi

  echo "[voice] Préparation de la reconnaissance vocale (téléchargement au premier lancement)"
  (cd "$API_DIR" && python -c "import voice; voice.prepare_stt()") \
    || echo "[voice] Reconnaissance locale indisponible: Jarvis utilisera celle du navigateur."
}

setup_deps() {
  # Installe ou met à jour les dépendances Python du projet.
  activate_venv
  python -m pip install --upgrade pip
  pip install -r "$ROOT_DIR/requirements.txt"

  # La voix est facultative : sans elle, Jarvis se rabat sur celle du système ou du navigateur.
  if pip install -r "$ROOT_DIR/requirements-voice.txt"; then
    setup_voice
  else
    echo "[setup] Voix locale non installée (dépendances indisponibles sur cette plateforme)."
  fi

  # Le fine-tuning MLX n'existe que sur macOS Apple Silicon.
  if [[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]]; then
    pip install -r "$ROOT_DIR/requirements-train.txt" \
      || echo "[setup] mlx-lm non installé: l'entraînement sera indisponible."
  fi
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

  # L'hôte et le port se règlent dans .env (JARVIS_HOST, JARVIS_PORT).
  (cd "$API_DIR" && python main.py)
}

run_start() {
  # Lance Jarvis et ouvre le HUD dans le navigateur une fois l'API prête.
  local port url opener=""
  port="$(env_value JARVIS_PORT 8001)"
  url="http://localhost:$port/"
  if command -v open >/dev/null 2>&1; then
    opener="open"
  elif command -v xdg-open >/dev/null 2>&1; then
    opener="xdg-open"
  fi

  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Jarvis tourne déjà (service ?) : ouverture de $url"
    if [[ -n "$opener" ]]; then
      "$opener" "$url"
    fi
    return
  fi

  if [[ -n "$opener" ]]; then
    (
      for _ in $(seq 1 60); do
        if curl -s -o /dev/null "${url}api/status" 2>/dev/null; then
          "$opener" "$url"
          break
        fi
        sleep 0.5
      done
    ) &
  else
    echo "Ouvre $url dans ton navigateur."
  fi

  run_api
}

run_web() {
  # Sert l'interface web statique sur le port 8000.
  if [[ ! -f "$INTERFACE_DIR/index.html" ]]; then
    echo "Error: interface file not found: $INTERFACE_DIR/index.html"
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
  # $1 (optionnel) : modèle de base qui remplace la ligne FROM du Modelfile.
  local from_override="${1:-}" title
  title="$(env_value JARVIS_USER_TITLE "Monsieur")"

  if [[ ! -f "$PROMPT_FILE" ]]; then
    echo "Error: shared prompt file not found: $PROMPT_FILE"
    exit 1
  fi

  if [[ ! -s "$PROMPT_FILE" ]]; then
    echo "Error: shared prompt file is empty: $PROMPT_FILE"
    exit 1
  fi

  awk -v prompt_file="$PROMPT_FILE" -v title="$title" -v from_override="$from_override" '
    function print_system(    line) {
      print ""
      print "SYSTEM \"\"\""
      while ((getline line < prompt_file) > 0) {
        gsub(/\{titre\}/, title, line)
        print line
      }
      close(prompt_file)
      print "\"\"\""
    }

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

    # Les jetons d arret du Modelfile sont propres au modele fine-tune.
    from_override != "" && /^[[:space:]]*PARAMETER[[:space:]]+stop/ {
      next
    }

    {
      if (!inserted && $1 == "FROM") {
        if (from_override != "") {
          print "FROM " from_override
        } else {
          print $0
        }
        print_system()
        inserted = 1
      } else {
        print $0
      }
    }

    END {
      if (!inserted) {
        print_system()
      }
    }
  ' "$MODELFILE" > "$GENERATED_MODELFILE"
}

modelfile_from_target() {
  # Retourne le chemin du GGUF désigné par le FROM du Modelfile s'il existe, sinon rien.
  local from_value target
  from_value="$(awk '/^FROM /{print $2; exit}' "$MODELFILE")"

  if [[ "$from_value" == /* || "$from_value" == ./* || "$from_value" == ../* ]]; then
    target="$from_value"
    if [[ "$from_value" != /* ]]; then
      target="$PROJECT_DIR/$from_value"
    fi
    if [[ -f "$target" || -d "$target" ]]; then
      echo "$target"
    fi
  fi
}

create_model() {
  # Construit le Modelfile généré puis crée ou met à jour le modèle Ollama Jarvis.
  need_cmd ollama

  if [[ ! -f "$MODELFILE" ]]; then
    echo "Error: Modelfile not found: $MODELFILE"
    exit 1
  fi

  local gguf base_model
  gguf="$(modelfile_from_target)"

  if [[ -n "$gguf" ]]; then
    echo "[create] Modèle fine-tuné détecté: $gguf"
    build_generated_modelfile
  else
    base_model="$(env_value JARVIS_BASE_MODEL "$DEFAULT_BASE_MODEL")"
    echo "[create] Aucun GGUF fine-tuné: Jarvis repose sur le modèle de base '$base_model'."
    ollama pull "$base_model"
    build_generated_modelfile "$base_model"
  fi

  (cd "$PROJECT_DIR" && ollama create "$MODEL_NAME" -f "$GENERATED_MODELFILE")
}

run_phone() {
  # Publie Jarvis en privé sur le réseau Tailscale, en HTTPS (exigé par le micro du téléphone).
  activate_venv
  local ts dns port token link
  ts="$(command -v tailscale || true)"
  if [[ -z "$ts" && -x "/Applications/Tailscale.app/Contents/MacOS/Tailscale" ]]; then
    ts="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
  fi
  if [[ -z "$ts" ]]; then
    echo "Tailscale n'est pas installé. Installe-le sur le Mac et sur le téléphone : https://tailscale.com/download"
    exit 1
  fi

  dns="$("$ts" status --json 2>/dev/null | python -c 'import json, sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || true)"
  if [[ -z "$dns" ]]; then
    echo "Tailscale n'est pas connecté : ouvre l'application Tailscale sur le Mac et connecte-toi."
    exit 1
  fi

  port="$(env_value JARVIS_PORT 8001)"
  token="$(cd "$API_DIR" && python phone_setup.py settings "$dns")"

  echo "[phone] Publication privée de Jarvis sur https://$dns (réseau Tailscale uniquement)"
  echo "[phone] Si Tailscale demande d'activer HTTPS, ouvre le lien qu'il affiche puis relance la commande."
  "$ts" serve --bg --https=443 "http://127.0.0.1:$port"

  link="https://$dns/#code=$token"
  python -c "import segno" >/dev/null 2>&1 || pip install --quiet segno || true
  echo
  echo "Sur le téléphone : active Tailscale, puis scanne ce QR code (ou ouvre le lien) :"
  (cd "$API_DIR" && python phone_setup.py qr "$link")
  echo "$link"
  echo
  echo "Si le code d'accès vient d'être créé, relance Jarvis : ./run_jarvis.sh service restart (ou ./run_jarvis.sh start)"
  echo "Pour couper l'accès depuis le téléphone : $ts serve --https=443 off"
}

run_service() {
  # Fait tourner Jarvis en arrière-plan, relancé à chaque ouverture de session (agent launchd).
  local action="${1:-status}" domain
  domain="gui/$(id -u)"
  if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "La commande service n'existe que sur macOS."
    exit 1
  fi

  case "$action" in
    install)
      # macOS interdit aux services d'arrière-plan de lire le Bureau, les Documents et les
      # Téléchargements : le service échouerait en boucle (« Operation not permitted »).
      case "$ROOT_DIR/" in
        "$HOME/Desktop/"*|"$HOME/Documents/"*|"$HOME/Downloads/"*|"$HOME/Library/Mobile Documents/"*)
          echo "Le projet est dans un dossier protégé par macOS ($ROOT_DIR)."
          echo "Un service d'arrière-plan ne peut pas y accéder. Deux solutions :"
          echo "  - déplacer le projet ailleurs (par exemple ~/Developer/Jarvis), puis relancer cette commande ;"
          echo "  - ou lancer Jarvis à la main quand tu en as besoin : ./run_jarvis.sh start"
          exit 1
          ;;
      esac
      if lsof -nP -iTCP:"$(env_value JARVIS_PORT 8001)" -sTCP:LISTEN >/dev/null 2>&1; then
        echo "Jarvis tourne déjà sur ce port : arrête-le d'abord (Ctrl+C dans son terminal)."
        exit 1
      fi
      mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
      cat > "$SERVICE_PLIST" <<PLIST_END
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$SERVICE_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$ROOT_DIR/run_jarvis.sh</string>
    <string>api</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$ROOT_DIR</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>StandardOutPath</key>
  <string>$SERVICE_LOG</string>
  <key>StandardErrorPath</key>
  <string>$SERVICE_LOG</string>
</dict>
</plist>
PLIST_END
      launchctl bootout "$domain/$SERVICE_LABEL" >/dev/null 2>&1 || true
      launchctl bootstrap "$domain" "$SERVICE_PLIST"
      echo "Jarvis tourne désormais en permanence, et redémarre avec ta session."
      echo "Interface : http://localhost:$(env_value JARVIS_PORT 8001)/ · Journal : $SERVICE_LOG"
      ;;
    restart)
      # Après une mise à jour du code ou du .env.
      launchctl kickstart -k "$domain/$SERVICE_LABEL"
      echo "Jarvis relancé."
      ;;
    remove|uninstall)
      launchctl bootout "$domain/$SERVICE_LABEL" >/dev/null 2>&1 || true
      rm -f "$SERVICE_PLIST"
      echo "Service Jarvis retiré."
      ;;
    status)
      if launchctl print "$domain/$SERVICE_LABEL" >/dev/null 2>&1; then
        echo "Service Jarvis actif. Journal : $SERVICE_LOG"
      else
        echo "Service Jarvis non installé (./run_jarvis.sh service install)."
      fi
      ;;
    *)
      echo "Usage: ./run_jarvis.sh service install|restart|remove|status"
      exit 1
      ;;
  esac
}

run_pytest() {
  # Lance les tests automatiques (intentions, persona, pilotage du poste, API).
  activate_venv
  python -m pytest --version >/dev/null 2>&1 || pip install -r "$ROOT_DIR/requirements-dev.txt"
  (cd "$ROOT_DIR" && python -m pytest tests -q)
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
    start)
      run_start
      ;;
    voice)
      setup_voice
      ;;
    phone)
      run_phone
      ;;
    service)
      run_service "${2:-status}"
      ;;
    pytest)
      run_pytest
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