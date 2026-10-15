"""Agent poste : diagnostic, volume, applications, écran, réseau, apparence."""

from __future__ import annotations

import re

from persona import fold


WEB_ONLY_SITES = {
    "youtube": "https://www.youtube.com",
    "wikipedia": "https://fr.wikipedia.org",
    "gmail": "https://mail.google.com",
    "google": "https://www.google.com",
    "google maps": "https://maps.google.com",
    "maps google": "https://maps.google.com",
    "google drive": "https://drive.google.com",
    "google agenda": "https://calendar.google.com",
    "netflix": "https://www.netflix.com",
    "amazon": "https://www.amazon.fr",
    "leboncoin": "https://www.leboncoin.fr",
    "le bon coin": "https://www.leboncoin.fr",
    "linkedin": "https://www.linkedin.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "github": "https://github.com",
    "twitch": "https://www.twitch.tv",
    "reddit": "https://www.reddit.com",
}


def parse_system(text: str) -> dict | None:
    """Interprète les demandes de pilotage du poste : diagnostic, volume, applications, web, veille."""
    folded = fold(text).strip(" .!?")
    cleaned = text.strip().strip(".!?").strip()

    # Diagnostic
    if re.search(r"\bbatterie\b|\bautonomie\b", folded):
        return {"action": "system_status", "params": {"focus": "battery"}}
    if re.search(
        r"\bdiagnostic\b|\b(?:etat|statut|status|rapport|bilan) (?:du|des|de tes|de vos|de mon|systeme)\s*(?:systemes?|mac|poste|pc|ordinateur|machine)?"
        r"|\brapport d'etat\b|\btous les systemes\b|\b(?:utilisation|charge|usage) (?:du |de la )?(?:processeur|cpu|memoire|ram)\b"
        r"|\bespace disque\b|\bmemoire (?:vive|utilisee|disponible)\b",
        folded,
    ):
        return {"action": "system_status"}

    # Volume
    sound = r"(?:son|volume)"
    level = re.search(rf"\b{sound}\s+(?:a|au|sur)\s+(\d{{1,3}})\b", folded)
    if level:
        return {"action": "volume", "params": {"mode": "set", "level": min(100, int(level.group(1)))}}
    if re.search(rf"\b{sound}\s+(?:au maximum|au max|a fond)\b", folded):
        return {"action": "volume", "params": {"mode": "set", "level": 100}}
    if re.search(rf"\b(?:coupe|mute|desactive|eteins)\s+le\s+{sound}\b|\ben sourdine\b|\bmode muet\b", folded):
        return {"action": "volume", "params": {"mode": "mute"}}
    if re.search(rf"\b(?:remets|reactive|retablis|rallume|active)\s+le\s+{sound}\b", folded):
        return {"action": "volume", "params": {"mode": "unmute"}}
    if re.search(rf"\b(?:monte|augmente|hausse)\b.*\b{sound}\b|\bplus fort\b", folded):
        return {"action": "volume", "params": {"mode": "up"}}
    if re.search(rf"\b(?:baisse|diminue|reduis)\b.*\b{sound}\b|\bmoins fort\b", folded):
        return {"action": "volume", "params": {"mode": "down"}}
    if re.search(rf"\b(?:quel est le|a combien est le|niveau du|montre le)\s+{sound}\b", folded):
        return {"action": "volume", "params": {"mode": "get"}}

    # Veille de l'écran
    if re.search(
        r"\bverrouille[rz]?\s+(?:l'ecran|la session|le mac|l'ordinateur|le poste)\b"
        r"|\b(?:mets|mettre|passe)\s+(?:l'ecran|le mac|l'ordinateur|le poste)\s+en veille\b|\beteins l'ecran\b",
        folded,
    ):
        return {"action": "sleep_display"}

    # Recherche à ouvrir dans le navigateur (les recherches « parlées » sont dans parse_web_question)
    browser_search = re.match(
        r"^(?:ouvre|affiche|montre)(?:[- ]moi)?\s+(?:une\s+|la\s+)?recherche\s+(?:web\s+|internet\s+|google\s+)?(?:sur|pour|de)\s+(.+)$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if browser_search:
        return {"action": "web_search", "params": {"query": browser_search.group(1).strip(), "engine": "web"}}

    # Ouverture d'un site ou d'une application
    opening = re.match(r"^(?:ouvre|ouvrir|ouvrez|lance|lancer|lancez|d[ée]marre|d[ée]marrer)(?:[- ]moi)?\s+(.+)$", cleaned, flags=re.IGNORECASE)
    if opening:
        target = opening.group(1).strip()
        site = re.sub(r"^(?:le\s+site\s+(?:de\s+|d')?|la\s+page\s+(?:de\s+|d')?)", "", target, flags=re.IGNORECASE)
        if re.fullmatch(r"(?:https?://)?[\w-]+(?:\.[\w-]+)+(?:/\S*)?", site):
            return {"action": "open_url", "params": {"url": site}}
        # Des sites sans application sur le Mac : « ouvre YouTube » ouvre le site.
        known = WEB_ONLY_SITES.get(fold(site).strip(" .!?"))
        if known:
            return {"action": "open_url", "params": {"url": known}}
        return {"action": "open_app", "params": {"name": target}}

    closing = re.match(r"^(?:ferme|fermer|fermez|quitte|quitter|quittez)\s+(.+)$", cleaned, flags=re.IGNORECASE)
    if closing:
        return {"action": "quit_app", "params": {"name": closing.group(1).strip()}}

    return None


def _on_off(folded: str) -> bool:
    return not re.search(r"\b(?:coupe|desactive|eteins?|arrete|enleve|retire|quitte|stoppe|sors? d[ue])\b", folded)


def parse_poste(text: str) -> dict | None:
    folded = fold(text).strip(" .!?")
    if re.search(r"\bluminosite\b|\becran plus (?:clair|lumineux|sombre)\b|\b(?:eclaire|assombris) l'ecran\b", folded):
        down = re.search(r"\b(?:baisse|diminue|moins|reduis|sombre|assombris)\b", folded) is not None
        return {"action": "brightness", "params": {"direction": "down" if down else "up"}}
    if re.search(r"\bmode (?:sombre|nuit|clair)\b|\btheme (?:sombre|clair)\b|\bdark mode\b", folded) and not re.search(r"\broutine\b", folded):
        wanted = None if re.search(r"\b(?:bascule|inverse|change)\b", folded) else ("clair" not in folded and _on_off(folded))
        return {"action": "dark_mode", "params": {"on": wanted}}
    if re.search(r"\bverrouille[rz]?\b|\bbloque (?:le |mon )?(?:mac|ordi|ordinateur|session|ecran)\b", folded):
        return {"action": "lock_screen"}
    if re.search(r"\bcapture d'ecran\b|\bscreenshot\b|\bfais une capture\b", folded):
        return {"action": "screenshot"}
    if re.search(r"\bwi-?fi\b", folded):
        return {"action": "wifi", "params": {"on": _on_off(folded)}}
    if re.search(r"\bbluetooth\b", folded):
        return {"action": "bluetooth", "params": {"on": _on_off(folded)}}
    if re.search(r"\bne pas deranger\b|\bmode (?:concentration|focus)\b", folded):
        return {"action": "do_not_disturb", "params": {"on": _on_off(folded)}}
    return None
