"""Météo via Open-Meteo (service gratuit, sans clé d'API)."""

from __future__ import annotations

import threading
import time

import requests

from config import CITY
from persona import Reply, TITLE


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
CACHE_SECONDS = 600

# Codes météo WMO → description française.
WMO_DESCRIPTIONS = {
    0: "ciel dégagé",
    1: "ciel plutôt dégagé",
    2: "partiellement nuageux",
    3: "ciel couvert",
    45: "brouillard",
    48: "brouillard givrant",
    51: "bruine légère",
    53: "bruine",
    55: "bruine dense",
    56: "bruine verglaçante",
    57: "bruine verglaçante",
    61: "pluie faible",
    63: "pluie",
    65: "forte pluie",
    66: "pluie verglaçante",
    67: "pluie verglaçante",
    71: "neige faible",
    73: "neige",
    75: "fortes chutes de neige",
    77: "grains de neige",
    80: "averses légères",
    81: "averses",
    82: "averses violentes",
    85: "averses de neige",
    86: "fortes averses de neige",
    95: "orage",
    96: "orage avec grêle",
    99: "orage avec grêle",
}


class WeatherError(Exception):
    pass


_lock = threading.Lock()
_places: dict[str, dict] = {}
_forecasts: dict[str, tuple[float, dict]] = {}


def describe_code(code: int | None) -> str:
    """Traduit un code météo WMO en description française."""
    return WMO_DESCRIPTIONS.get(int(code) if code is not None else -1, "conditions variables")


def _locate(city: str) -> dict:
    """Retrouve les coordonnées d'une ville (résultat mis en cache)."""
    key = city.strip().lower()
    with _lock:
        if key in _places:
            return _places[key]

    try:
        res = requests.get(
            GEOCODING_URL,
            params={"name": city, "count": 1, "language": "fr", "format": "json"},
            timeout=6,
        )
        res.raise_for_status()
        results = res.json().get("results") or []
    except Exception as exc:
        raise WeatherError(f"géocodage indisponible: {exc}") from exc

    if not results:
        raise WeatherError(f"ville introuvable: {city}")

    place = {
        "name": results[0].get("name") or city,
        "latitude": results[0]["latitude"],
        "longitude": results[0]["longitude"],
    }
    with _lock:
        _places[key] = place
    return place


def _day(daily: dict, index: int) -> dict | None:
    try:
        return {
            "description": describe_code(daily["weather_code"][index]),
            "min": round(daily["temperature_2m_min"][index]),
            "max": round(daily["temperature_2m_max"][index]),
            "rain_probability": int(daily["precipitation_probability_max"][index] or 0),
        }
    except (KeyError, IndexError, TypeError):
        return None


def get_weather(city: str | None = None) -> dict:
    """Retourne la météo actuelle et les prévisions (aujourd'hui, demain) d'une ville."""
    requested = (city or CITY).strip() or CITY
    key = requested.lower()

    with _lock:
        cached = _forecasts.get(key)
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1]

    place = _locate(requested)
    try:
        res = requests.get(
            FORECAST_URL,
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m,is_day",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "auto",
                "forecast_days": 2,
            },
            timeout=8,
        )
        res.raise_for_status()
        payload = res.json()
    except Exception as exc:
        raise WeatherError(f"service météo indisponible: {exc}") from exc

    current = payload.get("current") or {}
    daily = payload.get("daily") or {}
    weather = {
        "city": place["name"],
        "temperature": round(current.get("temperature_2m", 0)),
        "apparent": round(current.get("apparent_temperature", current.get("temperature_2m", 0))),
        "code": current.get("weather_code"),
        "description": describe_code(current.get("weather_code")),
        "wind_kmh": round(current.get("wind_speed_10m", 0)),
        "humidity": round(current.get("relative_humidity_2m", 0)),
        "is_day": bool(current.get("is_day", 1)),
        "today": _day(daily, 0),
        "tomorrow": _day(daily, 1),
    }

    with _lock:
        _forecasts[key] = (time.time(), weather)
    return weather


def spoken_degrees(value: int) -> str:
    """Formate une température pour la voix (« 18 degrés », « moins 3 degrés »)."""
    unit = "degré" if abs(value) <= 1 else "degrés"
    return f"moins {abs(value)} {unit}" if value < 0 else f"{value} {unit}"


def _spoken_range(low: int, high: int) -> str:
    """Formate une plage de températures pour la voix (« de moins 2 à 6 degrés »)."""
    low_text = f"moins {abs(low)}" if low < 0 else str(low)
    return f"de {low_text} à {spoken_degrees(high)}"


def _umbrella_advice(day: dict | None) -> str:
    if day and day["rain_probability"] >= 60:
        return " Je vous suggère de prévoir un parapluie."
    return ""


def summarize_now(weather: dict) -> tuple[str, str]:
    """Retourne (texte affiché, texte oral) pour la météo du moment."""
    city = weather["city"]
    text = f"À {city}, il fait {weather['temperature']} °C, {weather['description']}."
    speech = f"À {city}, il fait {spoken_degrees(weather['temperature'])}, {weather['description']}."
    today = weather.get("today")
    if today:
        text += f" Aujourd'hui : de {today['min']} à {today['max']} °C, {today['rain_probability']} % de risque de pluie."
        speech += f" Les températures iront {_spoken_range(today['min'], today['max'])} aujourd'hui."
    advice = _umbrella_advice(today)
    return text + advice, speech + advice


def handle_weather(params: dict | None = None) -> Reply:
    """Répond à une demande météo (ville et jour optionnels)."""
    params = params or {}
    try:
        weather = get_weather(params.get("city"))
    except WeatherError as exc:
        print(f"[WEATHER] {exc}", flush=True)
        if "introuvable" in str(exc):
            return Reply(text=f"Je ne trouve pas cette ville, {TITLE}.")
        return Reply(text=f"Je ne parviens pas à joindre le service météo, {TITLE}.")

    if params.get("day") == "tomorrow":
        tomorrow = weather.get("tomorrow")
        if not tomorrow:
            return Reply(text=f"Je n'ai pas de prévisions pour demain, {TITLE}.", data=weather)
        city = weather["city"]
        text = (
            f"Demain à {city} : {tomorrow['description']}, de {tomorrow['min']} à {tomorrow['max']} °C, "
            f"{tomorrow['rain_probability']} % de risque de pluie."
        )
        speech = (
            f"Demain à {city}, {tomorrow['description']}, "
            f"{_spoken_range(tomorrow['min'], tomorrow['max'])}."
        )
        advice = _umbrella_advice(tomorrow)
        return Reply(text=text + advice, speech=speech + advice, data=weather)

    text, speech = summarize_now(weather)
    return Reply(text=text, speech=speech, data=weather)
