"""Agent vision : « regarde mon écran », « décris la photo plage.jpg »."""

from __future__ import annotations

import re

from persona import fold


_IMAGE = re.compile(
    r"^(?:d[ée]cris|regarde|analyse|lis|que vois-tu (?:sur|dans)|qu'est-ce qu'il y a (?:sur|dans)|qu'y a-t-il (?:sur|dans)|"
    r"que repr[ée]sente|c'est quoi)(?:[- ]moi)?\s+(?:la |cette |l'|ma |mon |le )?(?:photo|image|capture|illustration|dessin)\s+"
    r"(?:nomm[ée]e?\s+|appel[ée]e?\s+|de\s+|du\s+)?(?P<q>.+)$",
    re.IGNORECASE,
)


def parse_vision(text: str) -> dict | None:
    clean = text.strip().rstrip(" ?!.").replace("’", "'")
    image = _IMAGE.match(clean)
    if image and not re.search(r"\b(?:d'ecran|d'écran)\b", image["q"], flags=re.IGNORECASE):
        return {"action": "look_image", "params": {"query": image["q"].strip(" «»\"'"), "question": text.strip()}}
    folded = fold(text)
    if re.search(
        r"\b(?:regarde|vois|lis|decris|analyse)(?:[- ](?:moi|tu))?\s+(?:mon |l'|ce qu'il y a (?:sur|a) (?:mon |l'))ecran\b"
        r"|\bqu'est-ce qu'il y a (?:sur|a) (?:mon |l')ecran\b|\btu vois (?:quoi|mon ecran|ce qu'il y a)\b"
        r"|\bqu'est-ce que tu vois\b|\bque vois-tu\b|\bsur mon ecran\b"
        r"|^(?:decris|analyse|regarde|lis)(?:[- ]moi)? (?:la |cette |une )?capture d'ecran\b",
        folded,
    ):
        return {"action": "look_screen", "params": {"question": text.strip()}}
    return None
