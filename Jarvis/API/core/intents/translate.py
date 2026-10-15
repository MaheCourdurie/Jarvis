"""Agent traduction."""

from __future__ import annotations

import re

from core.intents.common import clean_name


_LANGUAGES = (
    r"anglais|espagnol|allemand|italien|portugais|arabe|chinois|japonais|russe|neerlandais|néerlandais|polonais"
    r"|turc|coreen|coréen|grec|suedois|suédois|latin|breton|occitan|catalan|hebreu|hébreu|hindi|francais|français"
)


def parse_translate(text: str) -> dict | None:
    clean = text.strip().replace("’", "'").rstrip(" ?!.")
    match = re.match(
        rf"^(?:comment (?:on dit|dit-on|dire|se dit|tu dis)|traduis|traduire|tu peux traduire|peux-tu traduire|c'est quoi|que veut dire)"
        rf"\s+(?:en (?P<lang1>{_LANGUAGES})\s*:?\s*)?(?P<text>.+?)(?:\s+en (?P<lang2>{_LANGUAGES}))?$",
        clean, flags=re.IGNORECASE,
    )
    if not match or not (match["lang1"] or match["lang2"]):
        return None
    language = (match["lang1"] or match["lang2"]).lower()
    return {"action": "translate", "params": {"text": clean_name(match["text"]), "language": language}}
