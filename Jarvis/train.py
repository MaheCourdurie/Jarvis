"""
train.py — Entraînement fin de Jarvis avec MLX LoRA (Apple Silicon)
Le modèle de base (~5 Go) se télécharge automatiquement depuis HuggingFace.
"""

import os
import random
import subprocess
import sys
import json
from pathlib import Path

# ─── CONFIGURATION — modifie ces valeurs selon les besoins ─────────────────
# JARVIS_TRAIN_MODEL et JARVIS_TRAIN_ITERS permettent un essai rapide sans toucher au script.
MODEL_NAME     = os.getenv("JARVIS_TRAIN_MODEL", "mlx-community/Meta-Llama-3.1-8B-Instruct-4bit")
DATASET_PATH   = "./conversations.jsonl"
MLX_DATA_DIR   = "./mlx-data"
ADAPTER_DIR    = "./jarvis-mlx"
FUSED_DIR      = "./jarvis-fused"

ITERS          = int(os.getenv("JARVIS_TRAIN_ITERS", "800"))    # recommande à 1200 si pour 50+ exemples mais trop lourd ducoup 800 pour 4h de training sur M1 Pro (16 Go RAM) avec 100% de GPU utilisé. Ajuste selon ton matériel et dataset. 400-800 iters pour ~100 exemples, 1200+ pour 500+ exemples.
BATCH_SIZE     = 4      # 2-4 pour 8 Go de RAM, 4-8 pour 16 Go. Ici 2 pour evite bug
LEARNING_RATE  = 5e-5   # taux d'apprentissage ici assez bas pour éviter d'écraser les connaissances du modèle de base, surtout avec peu d'itérations.
LORA_LAYERS    = 8      # couches à adapter (8 = bon équilibre perf/mémoire)
STEPS_PER_EVAL = 50
SAVE_EVERY     = 100
# ──────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT_FILE = Path(__file__).resolve().parent / "system_prompt.txt"
ROOT_ENV = Path(__file__).resolve().parents[1] / ".env"
# Formule d'appel par défaut, telle qu'elle est écrite dans conversations.jsonl.
DATASET_TITLE = "Monsieur"


def load_user_title() -> str:
    """Lit la formule d'appel (JARVIS_USER_TITLE) dans l'environnement ou le fichier .env."""
    title = os.getenv("JARVIS_USER_TITLE", "").strip()
    if not title and ROOT_ENV.exists():
        for line in ROOT_ENV.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "JARVIS_USER_TITLE":
                title = value.split(" #")[0].strip().strip('"')
    return title or DATASET_TITLE


USER_TITLE = load_user_title()


def load_system_prompt() -> str:
    """Charge le prompt système commun utilisé pendant l'entraînement."""
    text = ""
    if SYSTEM_PROMPT_FILE.exists():
        text = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()
    if not text:
        text = "Tu es J.A.R.V.I.S., l'assistant personnel de {titre}. Tu le vouvoies et tu réponds brièvement."
    return text.replace("{titre}", USER_TITLE)


SYSTEM_PROMPT = load_system_prompt()


def prepare_dataset():
    """Convertit conversations.jsonl au format MLX train/valid."""
    print("[1/3] Préparation du dataset...")
    Path(MLX_DATA_DIR).mkdir(exist_ok=True)

    records = []
    with open(DATASET_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    # Injecter le system prompt si absent ou le remplacer par le nôtre
    converted = []
    for rec in records:
        messages = rec.get("messages", [])
        # Remplacer le system prompt par le nôtre (de référence)
        filtered = [
            # Le dataset est écrit avec « Monsieur » : on y inscrit la formule d'appel choisie.
            {"role": m["role"], "content": m["content"].replace(DATASET_TITLE, USER_TITLE)}
            for m in messages
            if m["role"] != "system"
        ]
        full = [{"role": "system", "content": SYSTEM_PROMPT}] + filtered

        # Format « chat » de MLX : le gabarit de conversation du modèle (celui qu'Ollama
        # utilisera à l'inférence) est appliqué automatiquement par mlx_lm.
        converted.append({"messages": full})

    # Mélange reproductible, pour que la validation ne contienne pas que la fin du fichier.
    random.Random(42).shuffle(converted)

    # Découpage 90/10 pour entraînement/validation
    split      = max(1, int(len(converted) * 0.9))
    train_data = converted[:split]
    valid_data = converted[split:] or converted[:1]

    for name, data in [("train", train_data), ("valid", valid_data)]:
        with open(f"{MLX_DATA_DIR}/{name}.jsonl", "w", encoding="utf-8") as f:
            for item in data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"    {len(train_data)} exemples d'entraînement")
    print(f"    {len(valid_data)} exemples de validation")
    print(f"    Formule d'appel : {USER_TITLE}")
    print(f"    Sauvegardé dans {MLX_DATA_DIR}/\n")


def run_training():
    """Lance le fine-tuning LoRA avec mlx_lm."""
    print("[2/3] Fine-tuning MLX LoRA...")
    print(f"    Modèle  : {MODEL_NAME}")
    print(f"    Iters   : {ITERS}")
    print(f"    Output  : {ADAPTER_DIR}/\n")

    cmd = [
        sys.executable, "-m", "mlx_lm", "lora",
        "--model",           MODEL_NAME,
        "--train",
        "--data",            MLX_DATA_DIR,
        # L'apprentissage porte sur les réponses de Jarvis, pas sur le prompt système répété.
        "--mask-prompt",
        "--batch-size",      str(BATCH_SIZE),
        "--num-layers",      str(LORA_LAYERS),
        "--iters",           str(ITERS),
        "--learning-rate",   str(LEARNING_RATE),
        "--steps-per-eval",  str(STEPS_PER_EVAL),
        "--save-every",      str(SAVE_EVERY),
        "--adapter-path",    ADAPTER_DIR,
    ]
    subprocess.run(cmd, check=True)
    print(f"\n    Adaptateurs LoRA → {ADAPTER_DIR}/\n")


def local_model_path() -> str:
    """Retourne le dossier local du modèle de base.

    mlx_lm fuse exige une copie locale complète du dépôt : on la complète ici
    (seuls quelques petits fichiers manquent après l'entraînement).
    """
    if Path(MODEL_NAME).exists():
        return MODEL_NAME
    from huggingface_hub import snapshot_download

    return snapshot_download(MODEL_NAME)


def fuse_model():
    """Fusionne les adaptateurs LoRA avec le modèle de base."""
    print("[3/3] Fusion LoRA + modèle de base...")
    print(f"    Output : {FUSED_DIR}/\n")

    cmd = [
        sys.executable, "-m", "mlx_lm", "fuse",
        "--model",        local_model_path(),
        "--adapter-path", ADAPTER_DIR,
        "--save-path",    FUSED_DIR,
    ]
    subprocess.run(cmd, check=True)
    print(f"\n    Modèle fusionné → {FUSED_DIR}/")
    print("\n Fine-tuning terminé !")
    print("   Prochaine étape : bash convert_to_gguf.sh")


def test_model():
    """Test rapide du modèle après fine-tuning."""
    print("\n[TEST] Vérification rapide du modèle fine-tuné...")
    test_prompts = [
        "Bonjour Jarvis",
        "Qui es-tu ?",
        "Je vais coder toute la nuit",
        "Envoie un message à Paul pour dire que je serai en retard",
        "C'est quoi un trou noir ?",
    ]

    for prompt in test_prompts:
        cmd = [
            sys.executable, "-m", "mlx_lm", "generate",
            "--model",         FUSED_DIR,
            "--max-tokens",    "150",
            "--system-prompt", SYSTEM_PROMPT,
            "--prompt",        prompt,
        ]
        print(f"\n  >> {prompt}")
        subprocess.run(cmd, check=True)


if __name__ == "__main__":
    print("=" * 56)
    print("  Jarvis — Fine-tuning MLX (Apple Silicon)")
    print("=" * 56 + "\n")

    try:
        import mlx_lm
    except ImportError:
        print(" mlx-lm non installé. Lance : pip install mlx-lm")
        exit(1)

    prepare_dataset()
    run_training()
    fuse_model()

    answer = input("\nLancer le test rapide ? (o/n) : ").strip().lower()
    if answer == "o":
        test_model()
