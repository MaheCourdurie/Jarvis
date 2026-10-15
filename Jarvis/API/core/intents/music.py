"""Agent musique : lecture, pause, morceau suivant, recherche (Spotify / Musique)."""

from __future__ import annotations

import re

from persona import fold
from core.intents.common import clean_name


def parse_music(text: str) -> dict | None:
    clean = text.strip().replace("’", "'").rstrip(" .!?")
    folded = fold(clean)
    music_word = re.search(r"\b(?:musique|chanson|morceau|titre|piste|lecture|spotify|playlist|album|son de spotify)\b", folded)

    def command(name: str, query: str = "") -> dict:
        params = {"command": name}
        if query:
            params["query"] = query
        return {"action": "music", "params": params}

    if re.search(r"\b(?:c'est quoi|quel(?:le)? est) (?:cette|ce|la) (?:chanson|musique|morceau|titre)\b|\bqu'est-ce qu'on ecoute\b|\bqui chante\b|\bqu'est-ce qui passe\b", folded):
        return command("current")
    if music_word and re.search(r"\b(?:pause|arrete|stoppe|coupe|stop)\b", folded) or re.fullmatch(r"(?:mets )?(?:en )?pause", folded):
        return command("pause")
    if re.search(r"\b(?:morceau|chanson|piste|titre) suivante?\b|^suivante?$|\bpasse (?:au|a la) suivante?\b|\bchanson d'apres\b|\bzappe\b|\bskip\b", folded):
        return command("next")
    if re.search(r"\b(?:morceau|chanson|piste|titre) precedente?\b|^precedente?$|\breviens? (?:au|a la) (?:morceau|chanson) d'avant\b", folded):
        return command("previous")
    if re.search(r"\b(?:reprends?|relance|remets|continue) (?:la )?(?:musique|lecture)\b", folded):
        return command("play")
    query = re.match(
        r"^(?:mets|met|lance|joue|passe|[ée]coute|fais[- ]moi [ée]couter)(?:[- ]moi)?\s+"
        r"(?:du |de la musique de |des chansons de |la chanson |l'album |la playlist |un morceau de |une chanson de )(?P<q>.+?)(?:\s+sur spotify)?$",
        clean, flags=re.IGNORECASE,
    ) or re.match(r"^(?:joue|[ée]coute|fais[- ]moi [ée]couter)(?:[- ]moi)?\s+(?P<q>.+?)(?:\s+sur spotify)?$", clean, flags=re.IGNORECASE)
    if query and not re.fullmatch(r"(?:de la |la |un peu de )?musique", fold(query["q"])):
        return command("play_query", clean_name(query["q"]))
    if re.match(r"^(?:mets|met|lance|joue|passe)(?:[- ]moi)?\s+(?:de la |la |un peu de |une )?musique\b", folded):
        return command("play")
    return None
