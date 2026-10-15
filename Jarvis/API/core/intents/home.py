"""Agent maison : raccourcis HomeKit."""

from __future__ import annotations

import re

from persona import fold
from core.intents.common import clean_name


def parse_home(text: str) -> dict | None:
    clean = text.strip().rstrip(" .!?")
    folded = fold(clean)
    named = re.match(r"^(?:lance|execute|demarre)\s+(?:le |mon )?raccourci\s+(?P<name>.+)$", folded)
    if named:
        name = re.match(r"^(?:lance|exécute|execute|démarre|demarre)\s+(?:le |mon )?raccourci\s+(?P<name>.+)$", clean, flags=re.IGNORECASE)
        return {"action": "run_shortcut", "params": {"name": clean_name(name["name"] if name else named["name"])}}
    if re.search(r"\b(?:quels sont|liste|montre(?:-moi)?) (?:mes |les )raccourcis\b", folded):
        return {"action": "list_shortcuts"}
    if re.match(r"^(?:allume|eteins?|ouvre|ferme|active|desactive|tamise|baisse|monte|lance)\b", folded) and re.search(
        r"\b(?:lumieres?|lampes?|volets?|stores?|prises?|chauffage|thermostat|clim(?:atisation)?|portail|garage|ventilateur"
        r"|salon|cuisine|chambre|salle de bain|bureau|entree|jardin|alarme de la maison)\b",
        folded,
    ):
        return {"action": "run_shortcut", "params": {"phrase": clean}}
    return None
