"""Agent trajets : temps de trajet et distance."""

from __future__ import annotations

import re

from persona import TITLE, fold
from core.intents.common import clean_name


def parse_travel(text: str) -> dict | None:
    clean = text.strip().replace("’", "'").rstrip(" ?!.")
    folded = fold(clean)
    if not re.search(
        r"\bcombien de (?:temps|minutes|km|kilometres)\b|\btemps de (?:trajet|route|parcours)\b|\bquelle distance\b"
        r"|\bje mets combien\b|\bitineraire\b|\bc'est loin\b|\bcombien de route\b",
        folded,
    ):
        return None
    mode = "pied" if re.search(r"\ba pied\b|\ben marchant\b", folded) else "velo" if re.search(r"\b(?:a|en) velo\b", folded) else "voiture"
    rest = re.sub(r"\s+(?:à|a|en)\s+(?:pied|v[ée]lo|voiture)\b|\s+en marchant\b", "", clean, flags=re.IGNORECASE)
    dest = re.search(
        r"(?:pour aller|pour rejoindre|jusqu'(?:à|a|au)|aller (?:à|a|au|jusqu'à)|vers|pour)\s+(?:à |a |au |aux |la |le |l')?(?P<dest>.+)$"
        r"|\b(?:à|a|au|aux)\s+(?P<dest2>[^,]+)$",
        rest, flags=re.IGNORECASE,
    )
    if not dest:
        return {"action": "command_error", "message": f"Pour aller où, {TITLE} ?"}
    destination = clean_name(dest["dest"] or dest["dest2"])
    destination = re.sub(r"^(?:c'est loin\s+)?(?:d'ici\s+)?(?:à|a|au)\s+", "", destination, flags=re.IGNORECASE)
    destination = re.sub(r"^(?:(?:à|a|au|aux|la|le|les)\s+|l')+", "", destination, flags=re.IGNORECASE)
    origin = re.search(r"\bdepuis\s+(?P<origin>.+?)(?:\s+(?:jusqu|pour|vers|à|a)\b|$)", clean, flags=re.IGNORECASE)
    params = {"destination": destination, "mode": mode}
    if origin:
        params["origin"] = clean_name(origin["origin"])
        params["destination"] = re.sub(r"\s+depuis\s+.+$", "", destination, flags=re.IGNORECASE)
    return {"action": "travel_time", "params": params}
