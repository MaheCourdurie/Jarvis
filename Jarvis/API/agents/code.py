"""Agent code : écrit des scripts et de petites applications complètes, vérifiées avant livraison."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from agents.atelier import Creation, CreativeAgent, Draft, draft_until_valid, slugify
from config import CODE_TRIAL_RUN
from core.agent import Handler
from persona import Reply, TITLE

EXTENSIONS = {
    "python": "py", "py": "py", "python3": "py",
    "javascript": "js", "js": "js", "node": "js", "typescript": "ts", "ts": "ts",
    "html": "html", "css": "css",
    "bash": "sh", "sh": "sh", "shell": "sh", "zsh": "sh",
    "swift": "swift", "java": "java", "kotlin": "kt", "c": "c", "cpp": "cpp", "c++": "cpp", "csharp": "cs", "cs": "cs",
    "rust": "rs", "go": "go", "golang": "go", "php": "php", "ruby": "rb", "lua": "lua", "sql": "sql", "json": "json",
    "applescript": "applescript", "r": "r",
}

SYSTEM_PROMPT = """Tu es l'agent de programmation de J.A.R.V.I.S., un développeur senior méticuleux.
Tu livres un seul fichier, complet, correct et prêt à l'emploi sur un Mac (macOS, Apple Silicon).

Règles de métier :
- Langage : celui demandé. Sinon, Python 3 pour un script ou un outil en ligne de commande ;
  une page HTML unique (HTML, CSS et JavaScript dans le même fichier) pour une application
  avec interface ou un jeu.
- Le fichier est entier : jamais de « ... », de « TODO », de partie à compléter ni de pseudo-code.
- Bibliothèque standard en priorité. Si une dépendance est indispensable, écris en tête du
  fichier, en commentaire, la commande pour l'installer (pip install …).
- Code lisible : fonctions courtes, noms explicites en anglais, commentaires utiles en français.
- Robuste : les entrées de l'utilisateur, les fichiers et le réseau peuvent faire défaut ;
  gère ces cas avec un message clair en français plutôt qu'un plantage.
- Python : un point d'entrée `if __name__ == "__main__":`, argparse si le script prend des
  paramètres, pathlib pour les chemins.
- Interface HTML : moderne, responsive, utilisable au clavier, sans ressource externe obligatoire.
- Jamais rien de destructeur sans confirmation (suppression, écrasement de fichiers).

Format de réponse, strictement :
TITRE: <nom court du programme, 2 à 5 mots>
RÉSUMÉ: <une phrase en français : ce que fait le programme et comment le lancer>
```<langage>
<le fichier complet>
```"""

REVISE_PROMPT = """Voici le fichier actuel « {title} » ({language}) :
```{language}
{content}```

Modification demandée : {request}

Applique la modification sans rien casser de ce qui marche, et renvoie le fichier COMPLET,
dans le même format (TITRE identique, RÉSUMÉ décrivant ce qui a changé)."""

_PLACEHOLDER = re.compile(r"^\s*(?:#|//)?\s*(?:\.\.\.|…)\s*$|\bTODO\b|\bà compléter\b|\bvotre code ici\b", re.IGNORECASE | re.MULTILINE)


def _check_with(command: list[str], content: str, suffix: str) -> Optional[str]:
    """Fait vérifier la syntaxe par l'outil du langage, s'il est installé."""
    if not shutil.which(command[0]):
        return None
    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as handle:
        handle.write(content)
    try:
        proc = subprocess.run(command + [handle.name], capture_output=True, text=True, timeout=20)
    except Exception:
        return None
    finally:
        Path(handle.name).unlink(missing_ok=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().replace(handle.name, "fichier")
        return f"erreur de syntaxe : {detail[-400:]}"
    return None


# Programmes qu'on ne lance pas à l'essai : ils ouvriraient une fenêtre sur l'écran.
_GRAPHICAL = re.compile(r"^\s*(?:import|from)\s+(?:tkinter|turtle|pygame|PyQt\d|PySide\d|kivy|wx)\b", re.MULTILINE)
# Échecs normaux dans le bac à sable : pas de réseau, pas d'arguments, pas de clavier, dépendance absente.
_EXPECTED_FAILURE = re.compile(
    r"EOFError|KeyboardInterrupt|ModuleNotFoundError|ImportError|URLError|ConnectionError|socket\.|gaierror"
    r"|PermissionError|Operation not permitted|usage:|FileNotFoundError|NotADirectoryError|SystemExit"
)
TRIAL_SECONDS = 10


def user_python() -> str:
    """Le Python que l'utilisateur lancerait lui-même (Homebrew avant celui, ancien, de macOS)."""
    return shutil.which("python3", path="/opt/homebrew/bin:/usr/local/bin:/usr/bin") or "/usr/bin/python3"


def trial_run(code: str) -> Optional[str]:
    """Lance le script Python dans un bac à sable macOS ; renvoie le plantage s'il y en a un.

    Le bac à sable n'a pas de réseau et ne peut écrire que dans un dossier temporaire, qui
    lui sert aussi de dossier personnel : un script qui range « ~/Téléchargements » y range
    un dossier vide, jamais les vrais fichiers.
    """
    if not CODE_TRIAL_RUN or not shutil.which("sandbox-exec") or _GRAPHICAL.search(code):
        return None
    with tempfile.TemporaryDirectory(prefix="jarvis-essai-") as home:
        home = str(Path(home).resolve())
        script = Path(home) / "script.py"
        script.write_text(code, encoding="utf-8")
        profile = (
            "(version 1)(allow default)(deny network*)(deny file-write*)"
            f'(allow file-write* (subpath "{home}") (subpath "/private/var/folders") (subpath "/dev"))'
        )
        try:
            proc = subprocess.run(
                ["sandbox-exec", "-p", profile, user_python(), "-I", "-B", str(script)],
                cwd=home, env={"HOME": home, "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "LANG": "fr_FR.UTF-8"},
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TRIAL_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return None  # il attend sans doute quelque chose (un serveur, une boucle) : rien d'anormal
        except Exception:
            return None
    if proc.returncode == 0 or "Traceback" not in proc.stderr:
        return None
    tail = proc.stderr.strip().splitlines()[-6:]
    if _EXPECTED_FAILURE.search("\n".join(tail)):
        return None
    return "le programme plante à l'exécution :\n" + "\n".join(tail).replace(home, "~")


def check_code(draft: Draft) -> Optional[str]:
    """Contrôle qualité : fichier entier, et syntaxe valide quand on sait la vérifier."""
    code = draft.content
    if len(code.strip()) < 20:
        return "le fichier est vide"
    if _PLACEHOLDER.search(code):
        return "le fichier contient des parties à compléter (« ... » ou TODO) : écris tout"
    extension = EXTENSIONS.get(draft.language, "")
    if extension == "py":
        try:
            compile(code, "script.py", "exec")
        except SyntaxError as exc:
            return f"erreur de syntaxe Python ligne {exc.lineno} : {exc.msg}"
        return trial_run(code)
    elif extension == "js":
        return _check_with(["node", "--check"], code, ".js")
    elif extension == "sh":
        return _check_with(["bash", "-n"], code, ".sh")
    elif extension == "json":
        try:
            json.loads(code)
        except ValueError as exc:
            return f"JSON invalide : {exc}"
    elif extension == "html" and "</html>" not in code.lower():
        return "la page HTML est incomplète (il manque </html>)"
    return None


class CodeAgent(CreativeAgent):
    """Écrit le programme demandé, le vérifie, l'enregistre et l'ouvre dans l'éditeur."""

    name = "code"

    def handlers(self) -> dict[str, Handler]:
        return {"write_code": self.write_code}

    def write_code(self, params: dict) -> Reply:
        request = str(params.get("request") or "").strip()
        if len(request) < 8:
            return Reply(text=f"Que doit faire ce programme, {TITLE} ? Par exemple : un script qui trie mes téléchargements par type.")
        language = str(params.get("language") or "").strip()
        prompt = f"Demande : {request}" + (f"\nLangage imposé : {language}." if language else "")
        return self.start_job("l'écriture du programme", lambda: self._make(prompt, request, language), params, "une à deux minutes")

    def _make(self, prompt: str, request: str, language: str) -> Creation:
        draft = draft_until_valid(SYSTEM_PROMPT, prompt, check_code, default_language=language or "python")
        return self._store(draft, request)

    def revise(self, creation: Creation, request: str) -> Creation:
        prompt = REVISE_PROMPT.format(
            title=creation.title, language=creation.language, content=creation.content, request=request
        )
        draft = draft_until_valid(SYSTEM_PROMPT, prompt, check_code, default_language=creation.language)
        draft.title = creation.title
        return self._store(draft, f"{creation.request} — {request}")

    def _store(self, draft: Draft, request: str) -> Creation:
        extension = EXTENSIONS.get(draft.language, "txt")
        title = draft.title or slugify(request)
        path = self.workshop.save("code", title, extension, draft.content)
        if extension == "sh":
            path.chmod(0o755)
        summary = draft.summary or f"Un programme {draft.language} pour : {request}."
        return Creation(
            kind="script",
            title=title,
            summary=summary,
            path=path,
            content=draft.content,
            request=request,
            maker=self.name,
            language=draft.language,
        )

