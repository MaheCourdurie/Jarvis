"""Agent web : recherches à faire soi-même, Wikipédia, résumé d'une page."""

from __future__ import annotations

import re

from persona import fold
from core.intents.common import clean_name


_SEARCH_VERB = re.compile(
    r"^(?:(?:peux|pourrais|pouvez|pourriez)[- ](?:tu|vous)\s+)?(?:me\s+)?"
    r"(?:(?:fais|lance)(?:[- ]moi)?\s+une\s+recherche(?:\s+(?:web|internet))?\s+(?:sur|pour|de)\s+"
    r"|(?:cherche|recherche|chercher|rechercher|trouve|trouver|renseigne[- ]toi sur)(?:[- ]moi)?\s+"
    r"|regarde(?:[- ]moi)?\s+(?=.*\bsur (?:internet|le web|le net|google)\b))(.+)$",
    flags=re.IGNORECASE,
)
# Questions dont la réponse se trouve sur le web : informations locales, récentes ou chiffrées.
_WEB_TOPICS = re.compile(
    r"\bhoraires?\b|\bheures? d'ouverture\b|\ba quelle heure (?:ouvre|ferme)\b|\b(?:ouvre|ferme) a quelle heure\b"
    r"|\b(?:est|sont)[- ](?:il|elle|ils|elles|ce que) (?:encore |toujours )?ouverte?s?\b|\bencore ouverte?s?\b"
    r"|\bpharmacies? de garde\b|\bprogramme (?:tv|tele|cine|du cinema)\b|\bseances? (?:de|du) cinema\b"
    r"|\bau cinema\b|\bfilms? (?:a l'affiche|en ce moment|qui passent?)\b"
    r"|\bactualites?\b|\bactus?\b|\bnews\b|\bdernieres nouvelles\b"
    r"|\bresultats? (?:du|de la|des|d'un|d'une)\b|\bscore (?:du|de|des)\b|\bqui a gagne\b|\bclassement (?:de|du|des)\b"
    r"|\bprix (?:de|du|d'un|d'une|des)\b|\bcombien (?:ca )?coute\b|\btarifs?\b"
    r"|\bcours (?:de l'action|du bitcoin|de l'euro|du dollar|de bourse|de l'or)\b|\btaux de change\b"
    r"|\bnumero de telephone\b|\badresse (?:de|du|des|d'un|d'une)\b"
    r"|\bdate de sortie\b|\bquand (?:sort|sortira|sortent)\b|\bprochaine sortie\b|\btrafic\b|\bbouchons\b|\bgreves?\b"
    r"|\b(?:restaurant|resto|boulangerie|pharmacie|medecin|dentiste|garage|supermarche|magasin|coiffeur)s? "
    r"(?:ouverte?s?|pres|proche|a proximite|dans le coin|autour|a cote)\b"
    r"|\bmeilleure?s? (?:restaurant|resto|bar|pizzeria|boulangerie|coiffeur|garage|medecin|dentiste)s?\b"
)
_PERSONAL_DATA = re.compile(r"\b(?:mes|mon|ma|nos|notre) (?:mails?|emails?|agenda|calendrier|evenements?|alarmes?|contacts?|horaires?|rendez)")


def parse_web_question(text: str) -> dict | None:
    """Repère les demandes que Jarvis doit aller chercher lui-même sur le web."""
    cleaned = text.strip().strip(".!?").strip()
    folded = fold(cleaned)
    if _PERSONAL_DATA.search(folded) or re.search(r"\bdans (?:mes|mon|ma) \w+", folded):
        return None

    explicit = _SEARCH_VERB.match(cleaned)
    if explicit:
        query = explicit.group(1).strip()
        # « sur YouTube » : on ouvre la recherche dans le navigateur, c'est pour regarder.
        video = re.search(r"\s+(?:sur|dans)\s+youtube$", query, flags=re.IGNORECASE)
        if video:
            return {"action": "web_search", "params": {"query": query[: video.start()].strip(), "engine": "youtube"}}
        video = re.match(r"(?:sur|dans)\s+youtube\s+(.+)$", query, flags=re.IGNORECASE)
        if video:
            return {"action": "web_search", "params": {"query": video.group(1).strip(), "engine": "youtube"}}
        query = re.sub(r"\s+(?:sur|dans)\s+(?:google|internet|le web|le net|wikip[ée]dia)$", "", query, flags=re.IGNORECASE).strip()
        if query:
            return {"action": "web_answer", "params": {"query": query}}

    if _WEB_TOPICS.search(folded):
        # La requête sera formulée par le modèle à partir de la question et de la ville.
        return {"action": "web_answer", "params": {"query": None}}

    return None


_WIKI_VERB = r"(?:ouvre|ouvrir|cherche|montre|affiche|va sur|lance)(?:[- ]moi)?"
_WIKI_PATTERNS = (
    # « Ouvre la page Wikipédia sur Napoléon », « ouvre l'article wikipedia de Marie Curie »
    re.compile(
        rf"^{_WIKI_VERB}\s+(?:la page\s+|l'article\s+|la fiche\s+)?(?:de\s+|d'|sur\s+)?wikip[ée]dia\s+"
        r"(?:(?:sur|de|du|des|d'|pour|concernant|à propos de|a propos de|(?:à|a) la page|(?:à|a) l'article)\s*)?(?P<q>.+)$",
        flags=re.IGNORECASE,
    ),
    # « Ouvre Napoléon sur Wikipédia », « montre-moi la page de Napoléon sur wikipedia »
    re.compile(
        rf"^{_WIKI_VERB}\s+(?:la page\s+(?:de\s+|d')?|l'article\s+(?:sur\s+|de\s+)?)?(?P<q>.+?)\s+(?:sur|dans)\s+wikip[ée]dia$",
        flags=re.IGNORECASE,
    ),
)


def parse_encyclopedia(text: str) -> dict | None:
    clean = text.strip().rstrip(" .!?").replace("’", "'")
    for pattern in _WIKI_PATTERNS:
        match = pattern.match(clean)
        if match and clean_name(match["q"]):
            return {"action": "web_search", "params": {"query": clean_name(match["q"]), "engine": "wikipedia"}}
    return None


def parse_summarize_url(text: str) -> dict | None:
    if not re.search(r"\b(?:r[ée]sume|r[ée]sum[ée]|que dit|de quoi parle|lis)\b", text, flags=re.IGNORECASE):
        return None
    url = re.search(r"https?://\S+|www\.\S+|\b[\w-]+\.(?:fr|com|org|net|io|eu|info)(?:/\S*)?", text)
    if not url:
        return None
    return {"action": "summarize_url", "params": {"url": url.group(0).rstrip(".,;!?)")}}
