"""Agent code : écrit des scripts et de petites applications complètes, vérifiées avant livraison."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import difflib

from agents import files
from agents.atelier import Creation, CreativeAgent, Draft, draft_until_valid, generate, slugify
from config import CODE_TRIAL_RUN
from core.agent import Handler
from persona import Reply, TITLE
from services import llm

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

FIX_PROMPT = """Voici le fichier « {name} » ({language}) de ton utilisateur :
```{language}
{content}```

{request}

Trouve les bugs, les plantages possibles et les erreurs de logique, et corrige-les sans changer
ce que fait le programme ni son style. Renvoie le fichier COMPLET corrigé, dans le format habituel :
TITRE : le nom du fichier ; RÉSUMÉ : les corrections faites, en une ou deux phrases."""

TESTS_PROMPT = """Voici le programme « {title} » ({name}) :
```python
{content}```

Écris ses tests automatiques avec unittest (bibliothèque standard, sans pytest) :
- le programme est déjà importé sous le nom `programme` : n'écris AUCUN import pour lui,
  appelle directement programme.ma_fonction(...) ;
- teste les fonctions principales, les cas limites et les erreurs attendues ;
- aucun réseau, aucune saisie au clavier, aucun fichier en dehors d'un tempfile.TemporaryDirectory ;
- termine par `if __name__ == "__main__": unittest.main()`.

Format de réponse, strictement :
TITRE: Tests de {title}
RÉSUMÉ: <une phrase : ce que vérifient les tests et comment les lancer>
```python
<le fichier de tests complet>
```"""

EXPLAIN_PROMPT = (
    "Tu es l'agent de programmation de J.A.R.V.I.S. Explique ce fichier de code à ton utilisateur, en français, "
    "en 4 à 6 phrases simples faites pour être lues à voix haute : à quoi il sert, comment il s'organise, comment "
    "le lancer, et un point d'attention s'il y en a un (bug probable, dépendance, danger). Pas de markdown, pas de code."
)

# En-tête ajouté aux tests : le programme est chargé depuis son fichier, quel que soit son nom.
TESTS_HEADER = """# Tests de « {title} » : python3 {tests_name}  (dans le dossier de {program_name})
import importlib.util as _importlib_util
import pathlib as _pathlib

_spec = _importlib_util.spec_from_file_location("programme", _pathlib.Path(__file__).with_name("{program_name}"))
programme = _importlib_util.module_from_spec(_spec)
_spec.loader.exec_module(programme)

"""

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


def run_tests(program_name: str, program: str, tests_name: str, tests: str) -> Optional[str]:
    """Fait tourner les tests avec le programme dans le bac à sable ; renvoie les échecs s'il y en a.

    Sans bac à sable (hors macOS), les tests ne sont pas lancés : seule leur syntaxe est vérifiée.
    """
    try:
        compile(tests, tests_name, "exec")
    except SyntaxError as exc:
        return f"erreur de syntaxe Python ligne {exc.lineno} des tests : {exc.msg}"
    if not CODE_TRIAL_RUN or not shutil.which("sandbox-exec") or _GRAPHICAL.search(program):
        return None
    with tempfile.TemporaryDirectory(prefix="jarvis-tests-") as home:
        home = str(Path(home).resolve())
        (Path(home) / program_name).write_text(program, encoding="utf-8")
        (Path(home) / tests_name).write_text(tests, encoding="utf-8")
        profile = (
            "(version 1)(allow default)(deny network*)(deny file-write*)"
            f'(allow file-write* (subpath "{home}") (subpath "/private/var/folders") (subpath "/dev"))'
        )
        try:
            proc = subprocess.run(
                ["sandbox-exec", "-p", profile, user_python(), "-B", tests_name],
                cwd=home, env={"HOME": home, "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "LANG": "fr_FR.UTF-8"},
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TRIAL_SECONDS * 3,
            )
        except subprocess.TimeoutExpired:
            return "les tests ne se terminent pas (boucle sans fin, ou attente d'une saisie) : simplifie-les"
        except Exception:
            return None
    if proc.returncode == 0:
        return None
    tail = (proc.stderr or proc.stdout).strip().splitlines()[-12:]
    return "des tests échouent ; corrige les TESTS (le programme, lui, ne change pas) :\n" + "\n".join(tail).replace(home, "~")


def changed_lines(before: str, after: str) -> int:
    """Nombre de lignes modifiées entre deux versions d'un fichier."""
    diff = difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
    return sum(1 for line in diff if line[:1] in "+-" and not line.startswith(("+++", "---")))


def language_of(path: Path) -> str:
    extension = path.suffix.lstrip(".").lower()
    return next((name for name, ext in EXTENSIONS.items() if ext == extension), extension or "texte")


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
    """Écrit le programme demandé, le vérifie, l'enregistre et l'ouvre dans l'éditeur.

    Il sait aussi écrire les tests du dernier programme, corriger un fichier existant (la
    version corrigée est enregistrée à côté, l'original n'est jamais touché) et expliquer un fichier.
    """

    name = "code"

    def handlers(self) -> dict[str, Handler]:
        return {
            "write_code": self.write_code,
            "code_tests": self.code_tests,
            "fix_code": self.fix_code,
            "explain_code": self.explain_code,
        }

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

    # ── Tests du dernier programme ────────────────────────────────────────

    def code_tests(self, params: dict) -> Reply:
        program = self.workshop.last
        if program is None or program.kind != "script":
            return Reply(text=f"Je n'ai pas de programme récent à tester, {TITLE}. Demandez-moi d'abord un script.")
        if EXTENSIONS.get(program.language) != "py":
            return Reply(text=f"Je n'écris des tests que pour les programmes Python, {TITLE} ; « {program.title} » est en {program.language}.")
        return self.start_job(f"les tests de « {program.title} »", lambda: self._tests(program), params, "une à deux minutes")

    def _tests(self, program: Creation) -> Creation:
        program_name = program.path.name
        tests_name = f"test_{program.path.stem.replace('-', '_')}.py"
        header = TESTS_HEADER.format(title=program.title, tests_name=tests_name, program_name=program_name)
        prompt = TESTS_PROMPT.format(title=program.title, name=program_name, content=program.content)

        def check(draft: Draft) -> Optional[str]:
            if re.search(r"^\s*(?:import|from)\s+programme\b", draft.content, re.MULTILINE):
                return "n'importe pas `programme` : il est déjà chargé, appelle directement programme.<fonction>"
            return run_tests(program_name, program.content, tests_name, header + draft.content)

        draft = draft_until_valid(SYSTEM_PROMPT, prompt, check, default_language="python", temperature=0.2)
        path = program.path.with_name(tests_name)
        path.write_text(header + draft.content, encoding="utf-8")
        count = len(re.findall(r"^\s*def test", draft.content, re.MULTILINE))
        summary = draft.summary or f"{count} tests pour « {program.title} »."
        if shutil.which("sandbox-exec") and CODE_TRIAL_RUN:
            summary += f" Les {count} tests passent." if count > 1 else ""
        return Creation(
            kind="script", title=f"Tests de {program.title}", summary=summary, path=path,
            content=header + draft.content, request=f"tests de {program.title}", maker=self.name, language="python",
        )

    # ── Un fichier existant : corriger, expliquer ─────────────────────────

    def _locate(self, params: dict) -> tuple[Optional[Path], str]:
        """Le fichier dont il est question : nommé dans la phrase, sinon le dernier programme."""
        query = str(params.get("query") or "").strip(" «»\"'.?!")
        if not query:
            program = self.workshop.last
            if program is not None and program.kind == "script":
                return program.path, ""
            return None, f"Quel fichier, {TITLE} ? Par exemple : corrige le fichier convertisseur.py."
        candidate = Path(query).expanduser()
        if candidate.is_absolute() and candidate.is_file():
            return candidate, ""
        found = files.find(query, limit=5)
        if not found:
            return None, f"Je ne trouve aucun fichier nommé « {query} » sur ce Mac, {TITLE}."
        return found[0], ""

    def fix_code(self, params: dict) -> Reply:
        path, problem = self._locate(params)
        if path is None:
            return Reply(text=problem)
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return Reply(text=f"Je ne parviens pas à lire {path.name}, {TITLE} : ce n'est pas un fichier texte.")
        if len(content) > 24_000:
            return Reply(text=f"{path.name} est trop long pour ma mémoire de travail, {TITLE} (plus de 24 000 caractères).")
        request = str(params.get("request") or "").strip()
        return self.start_job(f"la correction de {path.name}", lambda: self._fix(path, content, request), params, "une à deux minutes")

    def _fix(self, path: Path, content: str, request: str) -> Creation:
        language = language_of(path)
        prompt = FIX_PROMPT.format(name=path.name, language=language, content=content, request=f"Demande : {request}" if request else "")
        draft = draft_until_valid(SYSTEM_PROMPT, prompt, check_code, default_language=language, temperature=0.2)
        # Jamais d'écrasement : la version corrigée est enregistrée dans l'atelier, à côté des créations.
        fixed = self.workshop.save("code", f"{path.stem}-corrige", path.suffix.lstrip(".") or "txt", draft.content)
        lines = changed_lines(content, draft.content)
        summary = (draft.summary or "Corrections faites.") + f" {lines} lignes modifiées ; l'original est intact ({path})."
        return Creation(
            kind="script", title=f"{path.stem} corrigé", summary=summary, path=fixed, content=draft.content,
            request=f"corriger {path.name}", maker=self.name, language=language, extra={"original": str(path)},
        )

    def explain_code(self, params: dict) -> Reply:
        path, problem = self._locate(params)
        if path is None:
            return Reply(text=problem)
        text = files.read_text(path, budget=12_000)
        if not text.strip():
            return Reply(text=f"Je ne parviens pas à lire {path.name}, {TITLE}.")
        try:
            explanation = llm.clean_reply(
                generate(EXPLAIN_PROMPT, f"Fichier {path.name} :\n```\n{text}\n```", 0.2, max_tokens=500)
            )
        except Exception as exc:
            print(f"[CODE] Explication impossible: {exc}", flush=True)
            return Reply(text=f"Je n'ai pas réussi à analyser {path.name}, {TITLE}.")
        return Reply(text=f"{path.name} :\n\n{explanation}", speech=explanation, data={"path": str(path)})
