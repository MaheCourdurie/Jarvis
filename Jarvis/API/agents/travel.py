"""Agent trajets : durée et distance en voiture, à vélo ou à pied (OpenStreetMap, sans clé)."""

from __future__ import annotations

import math
import re
import time

import requests

from config import CITY, HOME_ADDRESS
from core.agent import Agent, Handler
from persona import Reply, TITLE, fold

GEOCODER = "https://nominatim.openstreetmap.org/search"
ROUTER = "https://routing.openstreetmap.de/routed-{profile}/route/v1/driving/{a};{b}"
PROFILES = {"voiture": "car", "velo": "bike", "pied": "foot"}
MODE_LABELS = {"voiture": "En voiture", "velo": "À vélo", "pied": "À pied"}
HEADERS = {"User-Agent": "Jarvis-assistant-personnel/2.0 (usage personnel)"}
_places: dict[str, tuple[float, float, str]] = {}


class TravelError(Exception):
    pass


def _distance_km(a: tuple[float, float, str], b: tuple[float, float, str]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def _geocode(query: str, near: tuple[float, float, str] | None = None, bounded: bool = False, limit: int = 1):
    """Le premier résultat (ou la liste des « limit » premiers si limit > 1)."""
    params = {"q": query, "format": "json", "limit": limit, "accept-language": "fr"}
    if near is not None:
        lat, lon = near[0], near[1]
        params.update({"viewbox": f"{lon - 0.35},{lat + 0.25},{lon + 0.35},{lat - 0.25}", "bounded": 1 if bounded else 0})
    try:
        res = requests.get(GEOCODER, params=params, headers=HEADERS, timeout=8)
        res.raise_for_status()
        results = res.json()
    except Exception as exc:
        raise TravelError(f"géocodage indisponible: {exc}") from exc
    finally:
        time.sleep(1)  # règle d'usage de Nominatim : une requête par seconde
    if limit > 1:
        return results
    return results[0] if results else None


def _point(result: dict, query: str) -> tuple[float, float, str]:
    name = result.get("name") or result.get("display_name", query).split(",")[0]
    return float(result["lat"]), float(result["lon"]), name


def _words(text: str) -> set[str]:
    return {word for word in re.findall(r"\w+", fold(text)) if len(word) > 2}


def _names_match(query: str, result: dict) -> bool:
    """Le nom trouvé correspond-il à la demande, sans être un lieu bien plus précis ?"""
    wanted, found = _words(query), _words(result.get("name") or "")
    return bool(wanted) and wanted <= found and len(found) <= len(wanted) + 2


def locate(place: str, near: tuple[float, float, str] | None = None) -> tuple[float, float, str]:
    """Coordonnées d'un lieu (adresse, ville, commerce connu d'OpenStreetMap).

    near : le point de départ. « La gare » est celle de la ville ; « le Capitole » celui d'à
    côté plutôt qu'un homonyme lointain ; « Montpellier » reste la ville de Montpellier.
    """
    place = re.sub(r"^(?:(?:à|a|au|aux|la|le|les)\s+|l')+", "", place.strip(), flags=re.IGNORECASE)
    key = f"{place.lower()}@{near[:2] if near else ''}"
    if key in _places:
        return _places[key]
    found = None
    if near is not None and CITY and "," not in place:
        # Dans la ville d'abord : un lieu qui porte bien ce nom (pas la commune, pas une rue homonyme).
        asks_street = re.search(r"\b(?:rue|avenue|allee|boulevard|chemin|place|impasse)\b", fold(place))
        wanted = _words(place)
        for local in _geocode(f"{place}, {CITY}", near, bounded=True, limit=5) or []:
            if local.get("class") in {"boundary", "place"} or (local.get("class") == "highway" and not asks_street):
                continue
            if wanted and wanted <= _words(local.get("name") or local.get("display_name", "")):
                found = _point(local, place)
                break
    if found is None:
        anywhere = _geocode(place, near)
        if anywhere is not None and (near is None or _distance_km(near, _point(anywhere, place)) <= 30):
            found = _point(anywhere, place)
        elif near is not None:
            nearby = _geocode(place, near, bounded=True)
            if nearby is not None and _names_match(place, nearby):
                found = _point(nearby, place)
            elif anywhere is not None:
                found = _point(anywhere, place)
    if found is None:
        raise TravelError(f"lieu introuvable: {place}")
    _places[key] = found
    return found


def route(origin: tuple[float, float, str], destination: tuple[float, float, str], mode: str) -> tuple[float, float]:
    """(durée en secondes, distance en mètres)."""
    url = ROUTER.format(profile=PROFILES[mode], a=f"{origin[1]},{origin[0]}", b=f"{destination[1]},{destination[0]}")
    try:
        res = requests.get(url, params={"overview": "false"}, headers=HEADERS, timeout=10)
        res.raise_for_status()
        best = res.json()["routes"][0]
    except Exception as exc:
        raise TravelError(f"calcul d'itinéraire indisponible: {exc}") from exc
    return best["duration"], best["distance"]


def spoken_duration(seconds: float) -> str:
    minutes = max(1, round(seconds / 60))
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes > 1 else ''}"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest:02d}" if rest else f"{hours} heure{'s' if hours > 1 else ''}"


class TravelAgent(Agent):
    """Temps de trajet depuis la maison (JARVIS_HOME_ADDRESS, sinon la ville de Jarvis)."""

    name = "trajets"

    def handlers(self) -> dict[str, Handler]:
        return {"travel_time": self.travel_time}

    def travel_time(self, params: dict) -> Reply:
        destination = str(params.get("destination") or "").strip(" ?.!")
        mode = params.get("mode") if params.get("mode") in PROFILES else "voiture"
        if not destination:
            return Reply(text=f"Pour aller où, {TITLE} ?")
        start = str(params.get("origin") or HOME_ADDRESS or CITY)
        from_home = not params.get("origin") and bool(HOME_ADDRESS)
        try:
            origin = locate(start)
            target = locate(destination, near=origin)
            seconds, meters = route(origin, target, mode)
        except TravelError as exc:
            print(f"[TRAJETS] {exc}", flush=True)
            if "introuvable" in str(exc):
                return Reply(text=f"Je ne trouve pas « {destination} » sur la carte, {TITLE}. Précisez la ville ou l'adresse.")
            return Reply(text=f"Le service d'itinéraires ne répond pas, {TITLE}.")
        kilometers = meters / 1000
        caveat = " (hors embouteillages)" if mode == "voiture" else ""
        distance = f"{kilometers:.1f} km".replace(".", ",") if kilometers < 10 else f"{round(kilometers)} km"
        return Reply(
            text=f"{MODE_LABELS[mode]}, de {'chez vous' if from_home else origin[2]} à {target[2]} : environ {spoken_duration(seconds)} pour {distance}{caveat}.",
            speech=f"{MODE_LABELS[mode]}, comptez environ {spoken_duration(seconds)} jusqu'à {target[2]}, {TITLE}{caveat}.",
            data={"seconds": round(seconds), "meters": round(meters)},
        )
