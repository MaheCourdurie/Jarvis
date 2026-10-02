"""Prépare l'accès à Jarvis depuis le téléphone (appelé par ./run_jarvis.sh phone).

Jarvis est publié en privé sur le réseau Tailscale, en HTTPS (le micro du téléphone
l'exige). L'API demande en plus un code d'accès aux appareils autres que le Mac :
ce script le crée dans .env, y autorise l'adresse Tailscale, puis affiche le lien
d'appairage sous forme de QR code.

Usage :
    python phone_setup.py settings <nom.tailnet.ts.net>   → écrit .env, affiche le code
    python phone_setup.py qr <lien>                       → affiche le QR code du lien
    tailscale status --json | python phone_setup.py check → dit si le téléphone est connecté
"""

from __future__ import annotations

import json
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def _read_env(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _value(lines: list[str], key: str) -> str:
    for line in lines:
        name, sep, value = line.partition("=")
        if sep and name.strip() == key:
            return value.split(" #", 1)[0].strip().strip('"')
    return ""


def _set(lines: list[str], key: str, value: str) -> list[str]:
    """Remplace la valeur d'une clé (en gardant sa place dans le fichier) ou l'ajoute à la fin."""
    updated, found = [], False
    for line in lines:
        name, sep, _ = line.partition("=")
        if sep and name.strip() == key and not name.strip().startswith("#"):
            if not found:
                updated.append(f"{key}={value}")
                found = True
            continue
        updated.append(line)
    if not found:
        updated.append(f"{key}={value}")
    return updated


def ensure_phone_settings(dns_name: str, env_file: Path = ENV_FILE) -> str:
    """Crée le code d'accès s'il manque et autorise l'adresse Tailscale ; renvoie le code."""
    lines = _read_env(env_file)
    token = _value(lines, "JARVIS_ACCESS_TOKEN") or secrets.token_urlsafe(9)

    origin = f"https://{dns_name.rstrip('.')}"
    origins = [item.strip() for item in _value(lines, "JARVIS_ALLOWED_ORIGINS").split(",") if item.strip()]
    if origin not in origins:
        origins.append(origin)

    if not any(line.startswith("# Accès depuis le téléphone") for line in lines):
        lines += ["", "# Accès depuis le téléphone (./run_jarvis.sh phone) — le code est secret"]
    lines = _set(lines, "JARVIS_ACCESS_TOKEN", token)
    lines = _set(lines, "JARVIS_ALLOWED_ORIGINS", ",".join(origins))
    _write(lines, env_file)
    return token


def set_env_values(values: dict[str, str], env_file: Path = ENV_FILE) -> None:
    """Écrit (ou remplace) des réglages dans .env, sans toucher au reste du fichier."""
    lines = _read_env(env_file)
    for key, value in values.items():
        lines = _set(lines, key, value)
    _write(lines, env_file)


def _write(lines: list[str], env_file: Path) -> None:
    env_file.write_text("\n".join(lines).strip("\n") + "\n", encoding="utf-8")


PHONE_SYSTEMS = {"iOS", "android"}


def phone_report(status: dict) -> str:
    """Dit si un téléphone est en ligne sur le réseau Tailscale : sans cela, il ne trouve pas le Mac."""
    me = status.get("Self") or {}
    account = ((status.get("User") or {}).get(str(me.get("UserID"))) or {}).get("LoginName", "")
    with_account = f" avec le compte {account}" if account else ""
    phones = [peer for peer in (status.get("Peer") or {}).values() if peer.get("OS") in PHONE_SYSTEMS]

    online = [peer.get("DNSName", "").split(".")[0] for peer in phones if peer.get("Online")]
    if online:
        return f"Téléphone connecté à Tailscale : {', '.join(online)}."
    if not phones:
        return (f"Aucun téléphone dans ton réseau Tailscale : installe l'app Tailscale sur le téléphone, "
                f"connecte-toi{with_account}, puis active-la.")

    last_seen = max(peer.get("LastSeen", "") for peer in phones)[:10]
    since = "" if not last_seen or last_seen.startswith("0001") else f" (hors ligne depuis le {'/'.join(reversed(last_seen.split('-')))})"
    return (f"Attention : ton téléphone n'est pas connecté à Tailscale{since}, "
            f"Safari y affichera « Safari ne peut pas ouvrir la page ». "
            f"Ouvre l'app Tailscale sur le téléphone, connecte-toi{with_account} et active-la "
            f"(l'icône VPN apparaît en haut de l'écran), puis scanne le QR code.")


def show_qr(link: str) -> None:
    """Affiche le lien en QR code : dans le terminal, et en grand à l'écran pour le scanner."""
    try:
        import segno
    except ImportError:
        print(link)
        return

    qr = segno.make(link, error="m")
    qr.terminal(compact=True)
    handle = tempfile.NamedTemporaryFile(prefix="jarvis-telephone-", suffix=".svg", delete=False)
    handle.close()
    qr.save(handle.name, scale=12, border=3)
    if sys.platform == "darwin":
        subprocess.run(["open", handle.name], check=False)


if __name__ == "__main__":
    command, args = sys.argv[1] if len(sys.argv) > 1 else "", sys.argv[2:]
    if command == "settings" and len(args) == 1:
        print(ensure_phone_settings(args[0]))
    elif command == "qr" and len(args) == 1:
        show_qr(args[0])
    elif command == "check" and not args:
        print(phone_report(json.load(sys.stdin)))
    else:
        print(__doc__)
        raise SystemExit(2)
