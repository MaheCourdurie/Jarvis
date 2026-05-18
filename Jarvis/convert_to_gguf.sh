#!/usr/bin/env bash
set -euo pipefail

# Dossier racine du projet et chemins de sortie utilisés par le script.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FUSED_DIR="${FUSED_DIR:-$PROJECT_DIR/jarvis-fused}"
EXPORT_DIR="${EXPORT_DIR:-$PROJECT_DIR/export}"
F16_GGUF="${F16_GGUF:-$EXPORT_DIR/jarvis-f16.gguf}"
Q4_GGUF="${Q4_GGUF:-$EXPORT_DIR/jarvis-q4.gguf}"
GGUF_QUANT="${GGUF_QUANT:-Q4_K_M}"
LLAMA_CPP_DIR="${LLAMA_CPP_DIR:-$PROJECT_DIR/.tools/llama.cpp}"
DEQUANT_FUSED_DIR="${DEQUANT_FUSED_DIR:-$EXPORT_DIR/.jarvis-fused-fp16}"

# Affiche un message de progression avec un préfixe stable.
log() {
  echo "[convert] $*"
}

# Vérifie qu'une commande existe dans le PATH avant de continuer.
need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Error: '$1' is required but not found in PATH."
    exit 1
  fi
}

# Installe torch si le module Python n'est pas déjà disponible.
# torch permet de faire la conversion de quantized safetensors vers un format float16 compatible avec le convertisseur GGUF de llama.cpp.
ensure_torch() {
  if "$PYTHON_BIN" -c "import torch" >/dev/null 2>&1; then
    return
  fi

  log "Python package 'torch' is missing. Installing it for GGUF conversion..."
  "$PYTHON_BIN" -m pip install torch
}

# Convertit le modèle fusionné en float16 avant la conversion GGUF.
prepare_dequantized_model() {
  log "Dequantizing fused model to float16"
  rm -rf "$DEQUANT_FUSED_DIR"
  "$PYTHON_BIN" -m mlx_lm convert \
    --hf-path "$FUSED_DIR" \
    --mlx-path "$DEQUANT_FUSED_DIR" \
    --dequantize \
    --dtype float16
}

# Recherche le script de conversion GGUF dans les emplacements connus.
resolve_converter() {
  local candidates=(
    "$LLAMA_CPP_DIR/convert_hf_to_gguf.py"
    "$HOME/llama.cpp/convert_hf_to_gguf.py"
    "$PROJECT_DIR/llama.cpp/convert_hf_to_gguf.py"
  )
  local item
  for item in "${candidates[@]}"; do
    if [[ -f "$item" ]]; then
      echo "$item"
      return 0
    fi
  done
  return 1
}

# Recherche le binaire de quantification llama-quantize dans les emplacements connus.
# llama-quantize est utilisé pour quantifier le modèle GGUF float16 dans le format plus compact choisi (Q4_K_M par défaut).
resolve_quantize() {
  local candidates=(
    "$LLAMA_CPP_DIR/build/bin/llama-quantize"
    "$LLAMA_CPP_DIR/llama-quantize"
    "$HOME/llama.cpp/build/bin/llama-quantize"
    "$PROJECT_DIR/llama.cpp/build/bin/llama-quantize"
  )
  local item
  for item in "${candidates[@]}"; do
    if [[ -x "$item" ]]; then
      echo "$item"
      return 0
    fi
  done
  return 1
}

# Clone et compile llama.cpp si les outils nécessaires ne sont pas encore présents.
bootstrap_llama_cpp() {
  need_cmd git
  need_cmd cmake

  mkdir -p "$PROJECT_DIR/.tools"
  if [[ ! -d "$LLAMA_CPP_DIR/.git" ]]; then
    log "Cloning llama.cpp into $LLAMA_CPP_DIR"
    git clone https://github.com/ggerganov/llama.cpp "$LLAMA_CPP_DIR"
  fi

  log "Building llama.cpp tools (this can take a few minutes on first run)"
  cmake -S "$LLAMA_CPP_DIR" -B "$LLAMA_CPP_DIR/build" -DGGML_METAL=ON
  cmake --build "$LLAMA_CPP_DIR/build" --config Release -j "$(sysctl -n hw.ncpu 2>/dev/null || echo 4)"
}

# Vérifie que le modèle fusionné existe avant toute conversion.
if [[ -d "$FUSED_DIR" ]]; then
  :
else
  echo "Error: fused model directory not found: $FUSED_DIR"
  echo "Run training and fuse first (./run_jarvis.sh train)."
  exit 1
fi

# Choisit l'interpréteur Python disponible sur la machine.
if command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  echo "Error: python/python3 not found in PATH."
  exit 1
fi

# Prépare le dossier d'export final.
mkdir -p "$EXPORT_DIR"

# Récupère les outils llama.cpp ; si besoin, les installe automatiquement.
CONVERTER="$(resolve_converter || true)"
QUANTIZE_BIN="$(resolve_quantize || true)"
if [[ -z "$CONVERTER" || -z "$QUANTIZE_BIN" ]]; then
  bootstrap_llama_cpp
  CONVERTER="$(resolve_converter || true)"
  QUANTIZE_BIN="$(resolve_quantize || true)"
fi

# Stoppe immédiatement si les outils attendus restent introuvables.
if [[ -z "$CONVERTER" ]]; then
  echo "Error: convert_hf_to_gguf.py not found after bootstrap."
  exit 1
fi

if [[ -z "$QUANTIZE_BIN" ]]; then
  echo "Error: llama-quantize binary not found after bootstrap."
  exit 1
fi

# Installe torch si nécessaire, puis prépare le modèle float16 de base.
ensure_torch
prepare_dequantized_model

# Convertit le modèle float16 en GGUF non quantifié.
log "Converting fused safetensors -> GGUF f16"
"$PYTHON_BIN" "$CONVERTER" "$DEQUANT_FUSED_DIR" --outfile "$F16_GGUF" --outtype f16

# Quantifie ensuite le GGUF f16 dans le format choisi par défaut.
log "Quantizing GGUF to $GGUF_QUANT"
"$QUANTIZE_BIN" "$F16_GGUF" "$Q4_GGUF" "$GGUF_QUANT"

# Résume les fichiers produits à la fin du pipeline.
log "Done"
log "f16: $F16_GGUF"
log "q4 : $Q4_GGUF"
