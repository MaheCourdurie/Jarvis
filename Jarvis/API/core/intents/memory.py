"""Agent mémoire : retenir, oublier, rappeler ce que Jarvis sait de l'utilisateur."""

from __future__ import annotations

import re

from persona import fold


def parse_memory(text: str) -> dict | None:
    clean = text.strip().replace("’", "'").rstrip(" .!")
    folded = fold(clean)
    keep = re.match(
        r"^(?:souviens[- ]toi|rappelle[- ]toi|retiens|n'oublie pas|garde en m[ée]moire|m[ée]morise)\s+(?:bien\s+)?(?:que|qu'|de)?\s*(?P<fact>.+)$",
        clean, flags=re.IGNORECASE,
    )
    if keep:
        return {"action": "remember", "params": {"fact": keep["fact"].strip()}}
    forget = re.match(r"^oublie(?:z)?\s+(?P<all>tout(?: ce que tu sais(?: sur moi)?)?$)?(?:que |qu'|ce que je t'ai dit sur )?(?P<fact>.*)$", folded)
    if forget and (forget["all"] or forget["fact"].strip()):
        return {"action": "forget", "params": {"fact": forget["fact"].strip(), "all": bool(forget["all"])}}
    if re.search(r"\b(?:qu'est-ce que tu sais|que sais-tu|tu sais quoi|ce que tu sais) (?:sur|de) moi\b|\btu te souviens de quoi\b|\bqu'as-tu retenu\b", folded):
        return {"action": "recall"}
    return None
