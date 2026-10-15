"""Exporter une page HTML en PDF avec un navigateur du poste (Chrome, Edge, Brave, Chromium), sans dépendance."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from config import env_str

# Navigateurs capables d'imprimer une page en PDF sans fenêtre (mode « headless »).
MAC_BROWSERS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)
COMMANDS = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "brave-browser")


def find_browser() -> Optional[str]:
    """Le navigateur à utiliser : JARVIS_CHROME s'il est réglé, sinon le premier trouvé."""
    chosen = env_str("JARVIS_CHROME", "")
    if chosen:
        return chosen if Path(chosen).exists() else None
    for path in MAC_BROWSERS:
        if Path(path).exists():
            return path
    return next((found for name in COMMANDS if (found := shutil.which(name))), None)


def html_to_pdf(source: Path, target: Optional[Path] = None, timeout: int = 60) -> Optional[Path]:
    """Imprime la page en PDF (à côté d'elle par défaut) ; None si aucun navigateur ne sait le faire."""
    browser = find_browser()
    if browser is None:
        return None
    target = target or Path(source).with_suffix(".pdf")
    command = [
        browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--hide-scrollbars",
        f"--print-to-pdf={target}", Path(source).resolve().as_uri(),
    ]
    # Chromium refuse de tourner en administrateur sans cette option (serveurs, conteneurs).
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        command.insert(1, "--no-sandbox")
    try:
        subprocess.run(command, capture_output=True, timeout=timeout, check=False)
    except Exception as exc:
        print(f"[PDF] Export impossible: {exc}", flush=True)
        return None
    if target.exists() and target.stat().st_size > 0:
        return target
    print(f"[PDF] Le navigateur n'a pas produit de PDF ({browser})", flush=True)
    return None
