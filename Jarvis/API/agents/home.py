"""Agent maison : pilote la maison connectée à travers les Raccourcis (HomeKit, scènes, appareils).

macOS n'expose pas HomeKit directement ; l'app Raccourcis, si. Chaque raccourci créé par
l'utilisateur (« Allumer salon », « Fermer les volets ») devient une commande vocale :
« allume la lumière du salon » lance le raccourci dont le nom correspond le mieux.
"""

from __future__ import annotations

import re
import shutil

from agents.system import SYSTEM, _run, _unsupported, run_shortcut as launch_shortcut
from core.agent import Agent, Handler
from persona import Reply, TITLE, ack, fold

STOP_WORDS = {"le", "la", "les", "l", "du", "de", "des", "d", "un", "une", "mon", "ma", "mes", "au", "aux", "a", "et", "en", "dans", "s", "il", "te", "plait", "jarvis", "moi"}
# Formes d'un même verbe : « allume » et « allumer » doivent correspondre.
STEMS = [
    (r"^allum\w*", "allumer"), (r"^(?:eteins?|eteindre|eteint|coupe\w*)", "eteindre"), (r"^ouvr\w*|^ouvre", "ouvrir"),
    (r"^ferm\w*", "fermer"), (r"^activ\w*", "activer"), (r"^desactiv\w*", "desactiver"), (r"^lumier\w*|^lampe\w*", "lumiere"),
    (r"^volets?", "volet"), (r"^lanc\w*", "lancer"), (r"^demarr\w*", "lancer"),
]


def words(text: str) -> set[str]:
    result = set()
    for word in re.findall(r"[a-z0-9]+", fold(text)):
        if word in STOP_WORDS:
            continue
        for pattern, stem in STEMS:
            if re.match(pattern, word):
                word = stem
                break
        result.add(word)
    return result


def list_shortcuts() -> list[str]:
    if SYSTEM != "darwin" or not shutil.which("shortcuts"):
        return []
    ok, output = _run(["shortcuts", "list"], timeout=15)
    return [line.strip() for line in output.splitlines() if line.strip()] if ok else []


def best_match(request: str, names: list[str]) -> str | None:
    """Le raccourci qui correspond le mieux à la phrase (tous ses mots-clés doivent y être)."""
    wanted = words(request)
    folded = fold(request)
    exact = [name for name in names if fold(name) in folded]
    if exact:
        return max(exact, key=len)
    scored = []
    for name in names:
        keys = words(name)
        if keys and keys <= wanted:
            scored.append((len(keys), name))
    return max(scored)[1] if scored else None


class HomeAgent(Agent):
    """Lance les raccourcis de la maison connectée."""

    name = "maison"

    def handlers(self) -> dict[str, Handler]:
        return {"run_shortcut": self.run_shortcut, "list_shortcuts": self.list}

    def run_shortcut(self, params: dict) -> Reply:
        if SYSTEM != "darwin" or not shutil.which("shortcuts"):
            return _unsupported("la maison connectée")
        request = str(params.get("name") or params.get("phrase") or "").strip()
        names = list_shortcuts()
        name = best_match(request, names)
        if name is None:
            return Reply(
                text=(
                    f"Je n'ai pas de raccourci pour « {request} », {TITLE}. Créez-le dans l'app Raccourcis "
                    "(par exemple « Allumer salon » avec l'action Maison), puis redemandez-moi."
                ),
                speech=f"Je n'ai pas de raccourci pour cela, {TITLE}. La marche à suivre est à l'écran.",
            )
        ok, detail = launch_shortcut(name, timeout=60)
        if not ok:
            print(f"[MAISON] {name} : {detail}", flush=True)
            return Reply(text=f"Le raccourci « {name} » a échoué, {TITLE}.")
        return Reply(text=f"{ack()} Raccourci « {name} » lancé.", speech=f"{ack()}")

    def list(self, params: dict) -> Reply:
        names = list_shortcuts()
        if not names:
            return Reply(text=f"Vous n'avez aucun raccourci, {TITLE}. Créez-en dans l'app Raccourcis.")
        return Reply(
            text=f"Vos raccourcis, {TITLE} :\n" + "\n".join(f"- {name}" for name in names),
            speech=f"Vous avez {len(names)} raccourcis, {TITLE}. La liste est à l'écran.",
        )
