"""
train.py — Entraînement fin de Jarvis avec MLX LoRA (Apple Silicon)
Le modèle de base (~5 Go) se télécharge automatiquement depuis HuggingFace.
"""

import subprocess
import json
from pathlib import Path

# ─── CONFIGURATION — modifie ces valeurs selon les besoins ─────────────────
MODEL_NAME     = "mlx-community/Meta-Llama-3.1-8B-Instruct-4bit"
DATASET_PATH   = "./conversations.jsonl"
MLX_DATA_DIR   = "./mlx-data"
ADAPTER_DIR    = "./jarvis-mlx"
FUSED_DIR      = "./jarvis-fused"

ITERS          = 800    # recommande à 1200 si pour 50+ exemples mais trop lourd ducoup 800 pour 4h de training sur M1 Pro (16 Go RAM) avec 100% de GPU utilisé. Ajuste selon ton matériel et dataset. 400-800 iters pour ~100 exemples, 1200+ pour 500+ exemples.
BATCH_SIZE     = 4      # 2-4 pour 8 Go de RAM, 4-8 pour 16 Go. Ici 2 pour evite bug
LEARNING_RATE  = 5e-5   # taux d'apprentissage ici assez bas pour éviter d'écraser les connaissances du modèle de base, surtout avec peu d'itérations.
LORA_LAYERS    = 8      # couches à adapter (8 = bon équilibre perf/mémoire)
STEPS_PER_EVAL = 50
SAVE_EVERY     = 100
# ──────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT_FILE = Path(__file__).resolve().parent / "system_prompt.txt"


def load_system_prompt() -> str:
    """Charge le prompt système commun utilisé pendant l'entraînement."""
    if SYSTEM_PROMPT_FILE.exists():
        text = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()
        if text:
            return text
    return "Tu es Jarvis, un assistant personnel professionnel."


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
        filtered = [m for m in messages if m["role"] != "system"]
        full = [{"role": "system", "content": SYSTEM_PROMPT}] + filtered

        # Conversion au format ChatML
        text = ""
        for msg in full:
            text += f"<|im_start|>{msg['role']}\n{msg['content']}<|im_end|>\n"
        converted.append({"text": text})

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
    print(f"    Sauvegardé dans {MLX_DATA_DIR}/\n")


def run_training():
    """Lance le fine-tuning LoRA avec mlx_lm."""
    print("[2/3] Fine-tuning MLX LoRA...")
    print(f"    Modèle  : {MODEL_NAME}")
    print(f"    Iters   : {ITERS}")
    print(f"    Output  : {ADAPTER_DIR}/\n")

    cmd = [
        "python", "-m", "mlx_lm", "lora",
        "--model",           MODEL_NAME,
        "--train",
        "--data",            MLX_DATA_DIR,
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


def fuse_model():
    """Fusionne les adaptateurs LoRA avec le modèle de base."""
    print("[3/3] Fusion LoRA + modèle de base...")
    print(f"    Output : {FUSED_DIR}/\n")

    cmd = [
        "python", "-m", "mlx_lm", "fuse",
        "--model",        MODEL_NAME,
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
        "Résume mes emails non lus",
        "Réveille-moi demain à 7h30",
        "Quand suis-je disponible cette semaine ?",
        "Cherche les dernières news sur l'IA",
    ]

    for prompt in test_prompts:
        cmd = [
            "python", "-m", "mlx_lm", "generate",
            "--model",        FUSED_DIR,
            "--max-tokens",   "150",
            "--prompt",       f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
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
