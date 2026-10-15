"""Agent vision : « regarde mon écran »."""

from __future__ import annotations

import re

from persona import fold


def parse_vision(text: str) -> dict | None:
    folded = fold(text)
    if re.search(
        r"\b(?:regarde|vois|lis|decris|analyse)(?:[- ](?:moi|tu))?\s+(?:mon |l'|ce qu'il y a (?:sur|a) (?:mon |l'))ecran\b"
        r"|\bqu'est-ce qu'il y a (?:sur|a) (?:mon |l')ecran\b|\btu vois (?:quoi|mon ecran|ce qu'il y a)\b"
        r"|\bqu'est-ce que tu vois\b|\bque vois-tu\b|\bsur mon ecran\b",
        folded,
    ):
        return {"action": "look_screen", "params": {"question": text.strip()}}
    return None
