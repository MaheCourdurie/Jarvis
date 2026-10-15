"""Agent notes : notes Apple et listes (courses…)."""

from __future__ import annotations

import re

from persona import fold
from core.intents.common import ARTICLES, clean_name


def parse_notes(text: str) -> dict | None:
    clean = text.strip().replace("’", "'").rstrip(" .!")
    folded = fold(clean)
    note = re.match(
        r"^(?:(?:prends?|prenez|cr[ée]e|fais|ajoute)(?:[- ]moi)?\s+une note|note (?:que|ceci|dans mes notes))\s*:?\s*(?P<text>.+)$",
        clean, flags=re.IGNORECASE,
    )
    if note:
        return {"action": "add_note", "params": {"text": note["text"].strip()}}

    add = re.match(
        r"^(?:ajoute|rajoute|mets|met|note|inscris)\s+(?P<items>.+?)\s+(?:à|a|sur|dans)\s+(?:ma|la|mes)\s+listes?"
        r"(?:\s+(?:de|des|du|d')\s*(?P<list>[\w' -]+))?$",
        clean, flags=re.IGNORECASE,
    )
    if add:
        items = [ARTICLES.sub("", item.strip()) for item in re.split(r",|\bet\b", add["items"]) if item.strip()]
        return {"action": "add_to_list", "params": {"items": items, "list": _list_name(add["list"])}}

    if re.search(r"\b(?:qu'est-ce qu'il y a|quoi|que reste-t-il|montre|lis|affiche|c'est quoi)\b.*\b(?:ma|la) liste\b", folded):
        name = re.search(r"\bliste (?:de |des |du |d')\s*([\w' -]+)", folded)
        return {"action": "read_list", "params": {"list": _list_name(name.group(1) if name else None)}}
    return None


def _list_name(raw: str | None) -> str:
    name = clean_name(raw or "")
    return "Courses" if not name or fold(name).startswith("course") else name
