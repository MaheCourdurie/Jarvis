"""Météo via Open-Meteo (service gratuit, sans clé d'API)."""

from __future__ import annotations

import threading
import time
from datetime import datetime

import requests

from config import CITY
from persona import Reply, TITLE


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
# Indice européen de qualité de l'air (EAQI) : seuil haut de chaque niveau.
AIR_LEVELS = [(20, "bonne"), (40, "correcte"), (60, "moyenne"), (80, "médiocre"), (100, "mauvaise"), (10_000, "très mauvaise")]
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
        day = {
            "description": describe_code(daily["weather_code"][index]),
            "min": round(daily["temperature_2m_min"][index]),
            "max": round(daily["temperature_2m_max"][index]),
            "rain_probability": int(daily["precipitation_probability_max"][index] or 0),
        }
    except (KeyError, IndexError, TypeError):
        return None
    for key in ("time", "sunrise", "sunset"):
        values = daily.get(key) or []
        if index < len(values):
            day[key] = values[index]
    return day


def _hours(hourly: dict, now_iso: str | None, count: int = 24) -> list[dict]:
    """Les prochaines heures (à partir de l'heure en cours) : heure, température, pluie, ciel."""
    times = hourly.get("time") or []
    start = 0
    if now_iso:
        current_hour = str(now_iso)[:13]
        start = next((index for index, value in enumerate(times) if str(value)[:13] >= current_hour), 0)
    hours = []
    for index in range(start, min(start + count, len(times))):
        try:
            hours.append({
                "time": times[index],
                "temperature": round(hourly["temperature_2m"][index]),
                "rain_probability": int(hourly["precipitation_probability"][index] or 0),
                "description": describe_code(hourly["weather_code"][index]),
            })
        except (KeyError, IndexError, TypeError):
            break
    return hours


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
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
                "hourly": "temperature_2m,precipitation_probability,weather_code",
                "timezone": "auto",
                "forecast_days": 7,
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
        "days": [day for day in (_day(daily, index) for index in range(7)) if day],
        "hours": _hours(payload.get("hourly") or {}, current.get("time")),
        "latitude": place["latitude"],
        "longitude": place["longitude"],
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

    day = params.get("day")
    if day == "hours":
        return _hourly_reply(weather, params.get("period"))
    if day in {"week", "weekend"} or isinstance(day, int) and day >= 2:
        return _forecast_reply(weather, day)

    if day == "tomorrow":
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


def _day_name(day: dict, offset: int) -> str:
    if offset == 0:
        return "aujourd'hui"
    if offset == 1:
        return "demain"
    try:
        return WEEKDAYS[datetime.fromisoformat(day["time"]).weekday()]
    except (KeyError, ValueError):
        return f"dans {offset} jours"


def _forecast_reply(weather: dict, day) -> Reply:
    """Prévisions sur plusieurs jours : la semaine, le week-end, ou un jour précis."""
    days = weather.get("days") or []
    city = weather["city"]
    if isinstance(day, int):
        if day >= len(days):
            return Reply(text=f"Mes prévisions ne vont pas au-delà de {len(days)} jours, {TITLE}.", data=weather)
        selected = [(day, days[day])]
    elif day == "weekend":
        selected = [
            (index, item) for index, item in enumerate(days)
            if "time" in item and datetime.fromisoformat(item["time"]).weekday() >= 5
        ][:2]
    else:
        selected = list(enumerate(days))
    if not selected:
        return Reply(text=f"Je n'ai pas de prévisions pour cette période, {TITLE}.", data=weather)

    lines = [
        f"- {_day_name(item, index).capitalize()} : {item['description']}, {item['min']} à {item['max']} °C, "
        f"pluie {item['rain_probability']} %"
        for index, item in selected
    ]
    rainy = [_day_name(item, index) for index, item in selected if item["rain_probability"] >= 60]
    warmest = max(selected, key=lambda pair: pair[1]["max"])
    if len(selected) == 1:
        index, item = selected[0]
        speech = f"{_day_name(item, index).capitalize()} à {city}, {item['description']}, {_spoken_range(item['min'], item['max'])}."
        speech += _umbrella_advice(item)
    else:
        speech = f"À {city}, le plus doux sera {_day_name(warmest[1], warmest[0])}, avec {spoken_degrees(warmest[1]['max'])}."
        speech += f" De la pluie probable {', '.join(rainy)}." if rainy else " Pas de pluie marquée en vue."
    return Reply(text=f"Prévisions à {city}, {TITLE} :\n" + "\n".join(lines), speech=speech, data=weather)


# Moments de la journée : heures de début et de fin (la nuit déborde sur le lendemain).
PERIODS = {"matin": (6, 12), "midi": (11, 14), "apres-midi": (12, 18), "soir": (18, 24), "nuit": (21, 30)}
PERIOD_LABELS = {"matin": "ce matin", "midi": "ce midi", "apres-midi": "cet après-midi", "soir": "ce soir", "nuit": "cette nuit"}


def _hour_of(item: dict) -> int:
    return datetime.fromisoformat(item["time"]).hour


def _hourly_reply(weather: dict, period: str | None = None) -> Reply:
    """Les prochaines heures, ou un moment de la journée : températures et heure de la pluie."""
    hours = weather.get("hours") or []
    city = weather["city"]
    if period in PERIODS:
        start, end = PERIODS[period]
        first_day = hours[0]["time"][:10] if hours else ""
        selected = []
        for item in hours:
            hour = _hour_of(item) + (24 if item["time"][:10] > first_day else 0)
            if start <= hour < end:
                selected.append(item)
        label = PERIOD_LABELS[period]
    else:
        selected, label = hours[:12], "dans les prochaines heures"
    if not selected:
        return Reply(text=f"Je n'ai pas de prévisions heure par heure pour {label}, {TITLE}.", data=weather)

    lines = [
        f"- {_hour_of(item)} h : {item['temperature']} °C, {item['description']}, pluie {item['rain_probability']} %"
        for item in selected
    ]
    low = min(item["temperature"] for item in selected)
    high = max(item["temperature"] for item in selected)
    rainy = next((item for item in selected if item["rain_probability"] >= 50), None)
    temperatures = spoken_degrees(low) if low == high else _spoken_range(low, high)
    speech = f"À {city}, {label}, {temperatures}."
    if rainy:
        dry_until = rainy is not selected[0]
        speech += (
            f" De la pluie probable à partir de {_hour_of(rainy)} heures."
            if dry_until
            else f" De la pluie probable dès maintenant ({rainy['rain_probability']} %)."
        )
        speech += " Je vous suggère de prévoir un parapluie."
    else:
        speech += " Pas de pluie en vue."
    title = f"{label.capitalize()} à {city}, {TITLE} :"
    return Reply(text=title + "\n" + "\n".join(lines), speech=speech, data=weather)


def handle_sun(params: dict | None = None) -> Reply:
    """Lever et coucher du soleil (aujourd'hui, ou demain)."""
    params = params or {}
    try:
        weather = get_weather(params.get("city"))
    except WeatherError:
        return Reply(text=f"Je ne parviens pas à joindre le service météo, {TITLE}.")
    day = weather.get("tomorrow" if params.get("day") == "tomorrow" else "today") or {}
    if "sunrise" not in day:
        return Reply(text=f"Je n'ai pas les heures du soleil, {TITLE}.")
    rise, set_ = (datetime.fromisoformat(day[key]) for key in ("sunrise", "sunset"))
    label = "Demain" if params.get("day") == "tomorrow" else "Aujourd'hui"
    return Reply(
        text=f"{label} à {weather['city']} : lever du soleil à {rise:%H:%M}, coucher à {set_:%H:%M}.",
        speech=f"{label}, le soleil se lève à {rise.hour} heures {rise.minute:02d} et se couche à {set_.hour} heures {set_.minute:02d}, {TITLE}.",
    )


def handle_air_quality(params: dict | None = None) -> Reply:
    """Qualité de l'air (indice européen), avec les particules fines."""
    params = params or {}
    try:
        place = _locate((params.get("city") or CITY).strip() or CITY)
        res = requests.get(
            AIR_QUALITY_URL,
            params={"latitude": place["latitude"], "longitude": place["longitude"], "current": "european_aqi,pm2_5,ozone"},
            timeout=8,
        )
        res.raise_for_status()
        current = res.json().get("current") or {}
    except Exception as exc:
        print(f"[WEATHER] Qualité de l'air indisponible: {exc}", flush=True)
        return Reply(text=f"Je ne parviens pas à obtenir la qualité de l'air, {TITLE}.")
    index = current.get("european_aqi")
    if index is None:
        return Reply(text=f"Je n'ai pas de mesure de qualité de l'air pour {place['name']}, {TITLE}.")
    level = next(label for limit, label in AIR_LEVELS if index <= limit)
    advice = " Évitez l'effort physique prolongé dehors." if index > 80 else ""
    return Reply(
        text=f"Qualité de l'air à {place['name']} : {level} (indice européen {round(index)}, particules fines {current.get('pm2_5', '?')} µg/m³).{advice}",
        speech=f"La qualité de l'air est {level} à {place['name']}, {TITLE}.{advice}",
    )
