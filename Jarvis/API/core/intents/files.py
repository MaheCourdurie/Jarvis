"""Agent fichiers : retrouver, ouvrir, résumer un fichier."""

from __future__ import annotations

import re

from core.intents.common import clean_name


_FILE = r"(?:fichier|document|pdf|dossier|photo|image|presentation|présentation|tableur|rapport|facture)s?"


def _file_query(raw: str) -> str:
    query = re.sub(r"^(?:nomm[ée]|appel[ée]|intitul[ée]|qui s'appelle|qui se nomme|sur|de)\s+", "", raw.strip(), flags=re.IGNORECASE)
    return clean_name(query)


def parse_files(text: str) -> dict | None:
    clean = text.strip().replace("’", "'").rstrip(" ?!.")
    summary = re.match(
        rf"^(?:r[ée]sume|fais(?:[- ]moi)? (?:un |le )?r[ée]sum[ée] d[ue])(?:[- ]moi)?\s+(?:le |mon |ma |ce |la )?{_FILE}\s+(?P<q>.+)$",
        clean, flags=re.IGNORECASE,
    )
    if summary:
        return {"action": "summarize_file", "params": {"query": _file_query(summary["q"])}}
    opening = re.match(rf"^ouvre(?:[- ]moi)?\s+(?:le |mon |ma |la )?{_FILE}\s+(?P<q>.+)$", clean, flags=re.IGNORECASE)
    if opening:
        return {"action": "open_file", "params": {"query": _file_query(opening["q"])}}
    finding = re.match(
        rf"^(?:o[uù] (?:est|se trouve|sont|j'ai mis)|trouve|retrouve|cherche)(?:[- ]moi)?\s+(?:le |mon |ma |mes |les |un |une |la )?{_FILE}\s+(?P<q>.+)$",
        clean, flags=re.IGNORECASE,
    )
    if finding:
        return {"action": "find_file", "params": {"query": _file_query(finding["q"])}}
    return None
