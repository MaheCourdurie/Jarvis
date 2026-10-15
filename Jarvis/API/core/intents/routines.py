"""Agent routines : créer, lister, lancer une routine."""

from __future__ import annotations

import re

from persona import fold
from core.intents.common import clean_name


def parse_routines(text: str) -> dict | None:
    clean = text.strip().rstrip(" .!?")
    folded = fold(clean)
    create = re.match(r"^(?:cr[ée]e|ajoute|enregistre|nouvelle)\s+(?:une |la |ma )?routine\s+(?P<name>[^:]+?)\s*:\s*(?P<steps>.+)$", clean, flags=re.IGNORECASE)
    if create:
        return {"action": "create_routine", "params": {"name": clean_name(create["name"]), "steps": create["steps"]}}
    if re.search(r"\b(?:quelles sont|liste|montre(?:-moi)?) (?:mes |les )routines\b", folded):
        return {"action": "list_routines"}
    run = re.match(r"^(?:lance|active|demarre|execute|passe en|on passe en)?\s*(?:la routine|ma routine|le mode|mode)\s+(?P<name>[\w' -]+)$", folded)
    if run:
        return {"action": "run_routine", "params": {"name": run["name"].strip()}}
    return None
