"""L'atelier : ce que partagent les agents qui créent (code, design).

Une création prend une à deux minutes au modèle local : elle est faite en tâche de fond.
Jarvis répond tout de suite (« Je m'y mets »), puis annonce le résultat quand il est prêt,
comme une alarme : le HUD l'affiche et le dit, sinon le Mac le prononce.

Chaque création est enregistrée dans JARVIS_CREATIONS_DIR et ouverte sur le poste.
L'atelier garde la dernière en mémoire : « ajoute un bouton de contact » la retouche.
"""

from __future__ import annotations

import re
import threading
import time
import unicodedata
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from agents.system import SYSTEM, _run
from config import CREATION_MAX_TOKENS, CREATION_MODEL, CREATIONS_DIR, LLM_NUM_CTX
from core.agent import Agent, Handler
from persona import Reply, TITLE, plural
from services import events, llm, voice

# Réponse attendue du modèle : un titre, un résumé, puis le fichier dans un bloc de code.
_TITLE_LINE = re.compile(r"^\s*\**\s*TITRE\s*\**\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_SUMMARY_LINE = re.compile(r"^\s*\**\s*R[ÉE]SUM[ÉE]\s*\**\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_CODE_BLOCK = re.compile(r"```[ \t]*([\w+#.-]*)[ \t]*\n(.*?)(?:\n```|$)", re.DOTALL)

# Tentatives de génération : la première, plus une correction si le contrôle qualité échoue.
ATTEMPTS = 2
# Mémoire de travail du modèle : la même que pour la conversation, donc jamais de rechargement.
CREATION_CTX = LLM_NUM_CTX


class CreationError(Exception):
    """Le modèle n'a pas produit de création utilisable."""


@dataclass
class Draft:
    """Ce que le modèle a rendu, une fois découpé."""

    title: str
    summary: str
    language: str
    content: str
    # Faux si le bloc de code n'est pas refermé : le modèle a été coupé avant la fin.
    closed: bool = True


@dataclass
class Creation:
    """Une création terminée, enregistrée sur le disque."""

    kind: str  # « script », « page », « logo », « palette »
    title: str
    summary: str
    path: Path
    content: str
    request: str
    maker: str  # nom de l'agent qui l'a faite (pour les retouches)
    language: str = ""
    extra: dict = field(default_factory=dict)


def slugify(value: str, default: str = "creation") -> str:
    """« Page d'accueil — Boulangerie » → « page-d-accueil-boulangerie »."""
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:48].strip("-") or default


def parse_draft(answer: str, default_language: str = "") -> Draft:
    """Découpe la réponse du modèle (TITRE / RÉSUMÉ / bloc de code)."""
    blocks = list(_CODE_BLOCK.finditer(answer or ""))
    if not blocks:
        raise CreationError("aucun bloc de code dans la réponse")
    # Le plus long bloc est le fichier ; les autres sont des exemples d'utilisation.
    block = max(blocks, key=lambda match: len(match.group(2)))
    title = _TITLE_LINE.search(answer or "")
    summary = _SUMMARY_LINE.search(answer or "")
    return Draft(
        title=(title.group(1).strip(" *`\"'") if title else ""),
        summary=(summary.group(1).strip(" *") if summary else ""),
        language=(block.group(1) or default_language).lower(),
        content=block.group(2).strip("\n") + "\n",
        closed=block.group(0).rstrip().endswith("```"),
    )


def generate(system: str, prompt: str, temperature: float, max_tokens: int = CREATION_MAX_TOKENS, json_mode: bool = False) -> str:
    """Une génération longue (jusqu'à plusieurs minutes), avec une mémoire de travail élargie.

    La réponse doit tenir dans la mémoire avec la demande (environ 3 caractères par jeton).
    """
    room = CREATION_CTX - (len(system) + len(prompt)) // 3 - 256
    if room < 512:
        raise CreationError("la création à retoucher est trop longue pour ma mémoire de travail")
    return llm.complete(
        system, prompt, temperature, min(max_tokens, room), timeout=900, json_mode=json_mode, num_ctx=CREATION_CTX,
        model=CREATION_MODEL or None,
    )


def draft_until_valid(
    system: str,
    prompt: str,
    check: Callable[[Draft], Optional[str]],
    default_language: str = "",
    temperature: float = 0.3,
) -> Draft:
    """Fait produire le fichier, le soumet au contrôle qualité, et redemande une fois s'il échoue.

    check(draft) renvoie None si tout va bien, sinon le problème, que le modèle reçoit
    pour se corriger (erreur de syntaxe, fichier coupé, morceau manquant…).
    """
    feedback = ""
    problem = "aucune réponse"
    for attempt in range(1, ATTEMPTS + 1):
        answer = generate(system, prompt + feedback, temperature)
        try:
            draft = parse_draft(answer, default_language)
            problem = (
                "le fichier a été coupé avant la fin : fais une version plus courte et plus simple"
                if not draft.closed
                else check(draft)
            )
        except CreationError as exc:
            problem = str(exc)
        if not problem:
            return draft
        print(f"[ATELIER] Contrôle qualité, essai {attempt} refusé : {problem}", flush=True)
        feedback = (
            f"\n\nTa réponse précédente a été refusée par le contrôle qualité : {problem}. "
            "Recommence en respectant strictement le format et les règles, avec un fichier complet."
        )
    raise CreationError(problem)


class Workshop:
    """Le dossier des créations, la dernière en mémoire, et l'exécution en tâche de fond."""

    def __init__(self, root: Path = CREATIONS_DIR) -> None:
        self.root = root
        self.last: Optional[Creation] = None
        self.history: list[Creation] = []
        self.busy: dict[str, float] = {}  # commande → heure de la demande
        self._lock = threading.Lock()
        # Une commande à la fois : le modèle local ne va pas plus vite à deux tâches.
        self._bench = threading.Lock()
        # Remplaçable dans les tests pour exécuter la commande sur place.
        self.launch: Callable[[Callable[[], None]], None] = lambda job: threading.Thread(
            target=job, daemon=True, name="jarvis-atelier"
        ).start()

    def save(self, folder: str, title: str, extension: str, content: str) -> Path:
        """Enregistre sans jamais écraser : « logo.svg », puis « logo-2.svg »…"""
        directory = self.root / folder
        directory.mkdir(parents=True, exist_ok=True)
        stem = slugify(title)
        path = directory / f"{stem}.{extension}"
        version = 2
        while path.exists():
            path = directory / f"{stem}-{version}.{extension}"
            version += 1
        path.write_text(content, encoding="utf-8")
        return path

    def url_of(self, creation: Creation) -> Optional[str]:
        """L'adresse où l'ouvrir depuis un autre appareil (l'aperçu d'un logo plutôt que le SVG seul)."""
        from routes.creations import creation_url

        return creation_url(creation.extra.get("preview") or creation.path, self.root)

    def remember(self, creation: Creation) -> None:
        with self._lock:
            if self.last is not None:
                self.history.append(self.last)
            self.last = creation

    def step_back(self) -> Optional[Creation]:
        """Revient à la création précédente (les fichiers, eux, restent tous sur le disque)."""
        with self._lock:
            if not self.history:
                return None
            self.last = self.history.pop()
            return self.last

    def recent(self, limit: int = 8) -> list[Path]:
        if not self.root.exists():
            return []
        files = [path for path in self.root.rglob("*") if path.is_file() and not path.name.startswith(".")]
        return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)[:limit]

    def commission(self, label: str, job: Callable[[], Creation], open_after: bool) -> None:
        """Lance la création en tâche de fond, puis l'annonce (ou annonce l'échec)."""

        def run() -> None:
            try:
                with self._bench:
                    start = time.perf_counter()
                    creation = job()
            except Exception as exc:
                print(f"[ATELIER] {label} : échec ({exc})", flush=True)
                failed = label[0].upper() + label[1:]
                announce(
                    f"{failed} n'a pas abouti, {TITLE} : le modèle n'a pas rendu un résultat fiable ({exc}). "
                    "Reformulez la demande, peut-être plus simplement.",
                    f"{failed} n'a pas abouti, {TITLE}. Pourriez-vous reformuler ?",
                    label,
                )
                return
            finally:
                with self._lock:
                    self.busy.pop(label, None)

            self.remember(creation)
            opened = open_creation(creation) if open_after else False
            elapsed = round(time.perf_counter() - start)
            print(f"[ATELIER] {creation.maker} › {creation.kind} « {creation.title} » prêt en {elapsed} s : {creation.path}", flush=True)
            feminine = creation.kind in FEMININE_KINDS
            where = f"Je l'ai {'ouverte' if feminine else 'ouvert'}" if opened else "C'est enregistré sur le Mac"
            text = f"{creation.summary}\n{where} : {creation.path}".strip()
            speech = f"{_ready_phrase(creation)}, {TITLE}. {creation.summary} {where}.".replace("  ", " ")
            announce(text, speech, creation.title, path=str(creation.path), url=self.url_of(creation))

        with self._lock:
            self.busy[label] = time.time()
        self.launch(run)


FEMININE_KINDS = {"page", "palette"}


def _ready_phrase(creation: Creation) -> str:
    ready = "prête" if creation.kind in FEMININE_KINDS else "prêt"
    return f"Votre {creation.kind} « {creation.title} » est {ready}"


def announce(text: str, speech: str, label: str, **payload) -> None:
    """Prévient l'utilisateur : par le HUD s'il est ouvert, sinon à voix haute sur le Mac."""
    events.publish("creation", label=label, text=text, speech=speech, **payload)
    if not events.hud_is_listening():
        voice.speak_local(speech)


def open_creation(creation: Creation) -> bool:
    """Ouvre la création sur le poste : le code dans l'éditeur, le reste dans le navigateur."""
    path = creation.extra.get("preview") or creation.path
    if creation.kind == "script" and path.suffix != ".html":
        if SYSTEM == "darwin":
            ok, _ = _run(["open", "-a", "Visual Studio Code", str(path)])
            if not ok:
                ok, _ = _run(["open", "-R", str(path)])  # à défaut, le montre dans le Finder
            return ok
        return False
    if SYSTEM == "darwin":
        ok, _ = _run(["open", str(path)])
        return ok
    return bool(webbrowser.open(Path(path).as_uri()))


# Durée annoncée pour une retouche, selon ce qui est retouché.
REVISION_ETA = {
    "page": "trois à quatre minutes",
    "script": "une à deux minutes",
    "logo": "une minute environ",
    "palette": "une trentaine de secondes",
}


def _of(label: str) -> str:
    """« de » + article : « du dessin du logo », « de la conception », « des retouches »."""
    if label.startswith("le "):
        return "du " + label[3:]
    if label.startswith("les "):
        return "des " + label[4:]
    return "de " + label


class CreativeAgent(Agent):
    """Agent qui crée : sa commande part à l'atelier, et il sait retoucher ce qu'il a fait."""

    needs_origin = True

    def __init__(self, context, workshop: Workshop) -> None:
        self.workshop = workshop
        super().__init__(context)

    def start_job(self, label: str, job: Callable[[], Creation], params: dict, eta: str) -> Reply:
        if label in self.workshop.busy:
            return Reply(text=f"J'y travaille déjà, {TITLE}. Je vous préviens dès que c'est prêt.")
        remote = bool(params.get("remote"))
        waiting = list(self.workshop.busy)
        self.workshop.commission(label, job, open_after=not remote)
        if waiting:
            eta += f", après {waiting[0]} déjà en cours"
        where = "" if not remote else " Je l'enregistrerai sur le Mac."
        return Reply(
            text=f"Je m'occupe {_of(label)}, {TITLE}. Comptez {eta} ; je vous préviens dès que c'est prêt.{where}",
            speech=f"Je m'y mets, {TITLE}. Comptez {eta}, je vous préviens dès que c'est prêt.",
            data={"creation": label},
        )

    def revise(self, creation: Creation, request: str) -> Creation:
        """Retouche une création de cet agent selon la demande."""
        raise NotImplementedError


class AtelierAgent(Agent):
    """Le chef d'atelier : rouvre, liste et fait retoucher les créations par leur auteur."""

    name = "atelier"
    needs_origin = True

    def __init__(self, context, workshop: Workshop, makers: list[CreativeAgent]) -> None:
        self.workshop = workshop
        self.makers = {maker.name: maker for maker in makers}
        super().__init__(context)

    def handlers(self) -> dict[str, Handler]:
        return {
            "revise_creation": self.revise_last,
            "open_creation": self.open_last,
            "list_creations": self.list_recent,
            "previous_version": self.previous_version,
            "choose_creation": self.choose,
            "export_pdf": self.export_pdf,
            "make_icons": self.make_icons,
        }

    def choose(self, params: dict) -> Reply:
        """« La deuxième » : parmi les propositions, garde celle-là ; c'est elle qu'on retouchera."""
        board = self.workshop.last
        choices = (board.extra.get("choices") if board else None) or []
        if not choices:
            return Reply(text=f"Je n'ai pas de propositions en attente, {TITLE}. Demandez par exemple : propose-moi trois logos pour mon club.")
        index = int(params.get("index") or 1) - 1
        if not 0 <= index < len(choices):
            return Reply(text=f"Il n'y a que {plural(len(choices), 'proposition')}, {TITLE}.")
        chosen = choices[index]
        if chosen.kind == "logo" and "icons" not in chosen.extra:
            from agents.design import export_icons

            icons = export_icons(chosen.path, chosen.title)
            if icons is not None:
                chosen.extra["icons"] = icons
        self.workshop.remember(chosen)
        if not params.get("remote"):
            open_creation(chosen)
        icons = chosen.extra.get("icons")
        return Reply(
            text=f"Je garde « {chosen.title} », {TITLE} : c'est elle que je retoucherai.\n{chosen.path}"
            + (f"\nFavicon et icônes d'app : {icons}" if icons else ""),
            speech=f"Entendu, {TITLE}. Je garde « {chosen.title} ».",
            data={"url": self.workshop.url_of(chosen)},
        )

    def export_pdf(self, params: dict) -> Reply:
        """Exporte la dernière page ou le dernier document en PDF (avec Chrome, Edge ou Brave)."""
        from services.pdf import html_to_pdf

        creation = self.workshop.last
        source = None
        if creation is not None:
            source = creation.extra.get("html") or creation.extra.get("preview") or creation.path
        if source is None or Path(source).suffix.lower() != ".html":
            return Reply(text=f"Je n'ai pas de page ni de document récent à exporter en PDF, {TITLE}.")
        pdf = html_to_pdf(Path(source))
        if pdf is None:
            return Reply(text=f"Il me faut Chrome, Edge ou Brave sur ce Mac pour exporter en PDF, {TITLE}.")
        creation.extra["pdf"] = pdf
        if not params.get("remote"):
            open_creation(Creation(creation.kind, creation.title, "", pdf, "", "", creation.maker))
        from routes.creations import creation_url

        return Reply(
            text=f"« {creation.title} » est exporté en PDF, {TITLE} :\n{pdf}",
            speech=f"C'est fait, {TITLE} : « {creation.title} » est en PDF.",
            data={"url": creation_url(pdf, self.workshop.root)},
        )

    def make_icons(self, params: dict) -> Reply:
        """Favicon et icônes d'app à partir du dernier logo."""
        from agents.design import export_icons

        creation = self.workshop.last
        if creation is None or creation.kind != "logo":
            return Reply(text=f"Il me faut d'abord un logo, {TITLE}. Demandez par exemple : fais un logo pour mon application.")
        icons = export_icons(creation.path, creation.title)
        creation.extra["icons"] = icons
        made = sorted(path.name for path in icons.iterdir())
        return Reply(
            text=f"Favicon et icônes d'app de « {creation.title} », {TITLE} ({icons}) :\n" + "\n".join(f"- {name}" for name in made),
            speech=f"Les icônes de « {creation.title} » sont prêtes, {TITLE}.",
        )

    def previous_version(self, params: dict) -> Reply:
        """« Reviens à la version précédente » : la précédente redevient celle qu'on retouche."""
        creation = self.workshop.step_back()
        if creation is None:
            return Reply(text=f"Il n'y a pas de version précédente, {TITLE}.")
        if not params.get("remote"):
            open_creation(creation)
        return Reply(
            text=f"Je reviens à « {creation.title} », {TITLE} : c'est elle que je retoucherai.\n{creation.path}",
            speech=f"Je reviens à la version précédente de « {creation.title} », {TITLE}.",
        )

    def revise_last(self, params: dict) -> Reply:
        creation = self.workshop.last
        request = str(params.get("request") or "").strip()
        if creation is None:
            return Reply(text=f"Je n'ai encore rien créé depuis mon démarrage, {TITLE}. Que dois-je concevoir ?")
        if not request:
            return Reply(text=f"Que dois-je changer à « {creation.title} », {TITLE} ?")
        if creation.extra.get("choices"):
            return Reply(text=f"Laquelle dois-je retoucher, {TITLE} ? Dites d'abord « la première », « la deuxième »…")
        maker = self.makers[creation.maker]
        label = f"la retouche de « {creation.title} »"
        eta = REVISION_ETA.get(creation.kind, "quelques minutes")
        return maker.start_job(label, lambda: maker.revise(creation, request), params, eta)

    def open_last(self, params: dict) -> Reply:
        creation = self.workshop.last
        if creation is None:
            recent = self.workshop.recent(limit=1)
            if not recent:
                return Reply(text=f"Je n'ai encore rien créé, {TITLE}.")
            path = recent[0]
            creation = Creation(kind="fichier", title=path.stem, summary="", path=path, content="", request="", maker="")
        if params.get("remote"):
            return Reply(text=f"Votre dernière création est sur le Mac, {TITLE} : {creation.path}")
        if not open_creation(creation):
            return Reply(text=f"Je ne parviens pas à l'ouvrir, {TITLE}. Elle est ici : {creation.path}")
        return Reply(
            text=f"Voici « {creation.title} », {TITLE}.\n{creation.path}",
            speech=f"Voici « {creation.title} », {TITLE}.",
        )

    def list_recent(self, params: dict) -> Reply:
        files = self.workshop.recent()
        busy = list(self.workshop.busy)
        if not files and not busy:
            return Reply(text=f"Votre atelier est vide, {TITLE}. Demandez-moi un script, une page, un logo ou une palette.")
        lines = [f"En cours : {label}" for label in busy]
        lines += [
            f"- {path.relative_to(self.workshop.root)} ({datetime.fromtimestamp(path.stat().st_mtime):%d/%m %H:%M})"
            for path in files
        ]
        speech = f"{plural(len(files), 'création')} dans votre atelier, {TITLE}"
        speech += f", et {len(busy)} en cours." if busy else "."
        return Reply(
            text=f"Vos dernières créations, {TITLE} ({self.workshop.root}) :\n" + "\n".join(lines),
            speech=speech[0].upper() + speech[1:],
        )
