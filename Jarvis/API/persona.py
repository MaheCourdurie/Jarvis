"""Persona J.A.R.V.I.S. : formule d'appel, tournures et mise en forme des réponses.

Chaque module métier renvoie un objet Reply :
- text   : ce qui est affiché dans le HUD (peut contenir des listes et des identifiants)
- speech : ce que Jarvis dit à voix haute (court, sans identifiants ni symboles)
"""

from __future__ import annotations

import random
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from config import USER_TITLE, local_now


TITLE = USER_TITLE

WEEKDAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTHS_FR = [
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
]

ACKNOWLEDGEMENTS = [
    "Bien, {t}.",
    "Tout de suite, {t}.",
    "C'est fait, {t}.",
    "À votre service, {t}.",
]


@dataclass
class Reply:
    """Réponse d'un module : texte affiché, version orale et données pour le HUD."""

    text: str
    speech: Optional[str] = None
    data: dict = field(default_factory=dict)
    # Action en attente de confirmation ({"action": ..., "params": ...}).
    pending: Optional[dict] = None

    @property
    def spoken(self) -> str:
        """Texte à prononcer : la version orale dédiée, sinon le texte nettoyé."""
        if self.speech is not None:
            return self.speech
        return to_speech(self.text)


def ack() -> str:
    """Retourne un accusé de réception dans le ton du majordome."""
    return random.choice(ACKNOWLEDGEMENTS).format(t=TITLE)


def greeting(now: datetime | None = None) -> str:
    """Retourne la salutation adaptée à l'heure (Bonjour / Bonsoir)."""
    hour = (now or local_now()).hour
    return "Bonjour" if 5 <= hour < 18 else "Bonsoir"


def plural(count: int, singular: str, plural_form: str | None = None) -> str:
    """Accorde un nom avec son nombre (« 1 alarme », « 3 alarmes »)."""
    word = singular if count <= 1 else (plural_form or singular + "s")
    return f"{count} {word}"


# ── Dates et heures en français ────────────────────────────────────────────

def format_time(value: datetime) -> str:
    """Formate une heure pour l'affichage (« 7 h 30 », « 10 h »)."""
    if value.minute == 0:
        return f"{value.hour} h"
    return f"{value.hour} h {value.minute:02d}"


def spoken_time(value: datetime) -> str:
    """Formate une heure pour la synthèse vocale (« 7 heures 30 », « midi »)."""
    hour, minute = value.hour, value.minute
    if minute == 0:
        if hour == 0:
            return "minuit"
        if hour == 12:
            return "midi"
        return "1 heure" if hour == 1 else f"{hour} heures"
    unit = "heure" if hour in (0, 1) else "heures"
    return f"{hour} {unit} {minute}"


def format_date(value: datetime | date) -> str:
    """Formate une date complète (« mardi 30 septembre »)."""
    return f"{WEEKDAYS_FR[value.weekday()]} {_day_number(value.day)} {MONTHS_FR[value.month - 1]}"


def day_label(value: datetime | date, now: datetime | None = None) -> str:
    """Retourne « aujourd'hui », « demain » ou la date complète."""
    reference = now or _now_like(value)
    target = value.date() if isinstance(value, datetime) else value
    delta = (target - reference.date()).days
    if delta == 0:
        return "aujourd'hui"
    if delta == 1:
        return "demain"
    label = format_date(value)
    if target.year != reference.year:
        label += f" {target.year}"
    return label


def format_when(value: datetime, now: datetime | None = None) -> str:
    """Formate un moment pour l'affichage (« demain à 7 h 30 »)."""
    return f"{day_label(value, now)} à {format_time(value)}"


def spoken_when(value: datetime, now: datetime | None = None) -> str:
    """Formate un moment pour la voix (« demain à 7 heures 30 »)."""
    return f"{day_label(value, now)} à {spoken_time(value)}"


def period_label(start: datetime, end: datetime, now: datetime | None = None) -> str:
    """Nomme une période [start, end) : « demain », « le mardi 30 septembre » ou « entre le … et le … »."""
    last_day = end - timedelta(seconds=1)
    if start.date() == last_day.date():
        label = day_label(start, now)
        return label if label in {"aujourd'hui", "demain"} else f"le {label}"
    return f"entre le {format_date(start)} et le {format_date(last_day)}"


def _day_number(day: int) -> str:
    return "1er" if day == 1 else str(day)


def _now_like(value: datetime | date) -> datetime:
    """Retourne l'instant présent dans le même fuseau que la valeur fournie."""
    tz = value.tzinfo if isinstance(value, datetime) else None
    return datetime.now(tz)


# ── Mise en forme orale ────────────────────────────────────────────────────

_SPEECH_DROP = [
    re.compile(r"\[id\s*:[^\]]*\]", flags=re.IGNORECASE),
    re.compile(r"https?://\S+"),
    re.compile(r"[*_`#>]+"),
]


def to_speech(text: str) -> str:
    """Nettoie un texte affiché pour qu'il puisse être prononcé naturellement."""
    spoken = text or ""
    for pattern in _SPEECH_DROP:
        spoken = pattern.sub(" ", spoken)

    lines = []
    for raw_line in spoken.splitlines():
        line = re.sub(r"^\s*(?:[-•–]|\d+[.)])\s+", "", raw_line).strip()
        if not line or line.startswith("/"):
            continue
        if not re.search(r"[.!?:;,…]$", line):
            line += "."
        lines.append(line)

    spoken = " ".join(lines)
    spoken = spoken.replace("->", "à").replace("→", "à")
    spoken = re.sub(r"\s+", " ", spoken).strip()
    return spoken


def strip_accents(value: str) -> str:
    """Retire les accents pour comparer des mots sans tenir compte de la graphie."""
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def fold(text: str) -> str:
    """Minuscules, sans accents ni apostrophes typographiques : base des détections."""
    return strip_accents((text or "").lower().replace("’", "'"))


# ── Apostrophe et petites phrases ──────────────────────────────────────────

_VOCATIVE_PREFIX = re.compile(
    r"^\s*(?:(?:dis(?:[- ]moi)?|hey|h[ée]|eh|ok|okay|s'il te pla[iî]t)[\s,]+)?jarvis\b[\s,;:!.?-]*",
    flags=re.IGNORECASE,
)
_VOCATIVE_SUFFIX = re.compile(r"[\s,]+jarvis[\s!.?]*$", flags=re.IGNORECASE)


def strip_vocative(text: str) -> str:
    """Retire l'interpellation « Jarvis, … » ou « …, Jarvis » d'une phrase."""
    cleaned = (text or "").strip()
    without_prefix = _VOCATIVE_PREFIX.sub("", cleaned, count=1)
    without_suffix = _VOCATIVE_SUFFIX.sub("", without_prefix, count=1).strip()
    return without_suffix


SMALLTALK = [
    # « JARVIS, you there? — For you sir, always. »
    (
        re.compile(r"^(?:tu es|es[- ]tu|t'es|vous etes|etes[- ]vous) (?:toujours |bien )?la$"),
        ["Pour vous, {t}, toujours."],
    ),
    (
        re.compile(r"^(?:tu m'entends|tu me recois|vous m'entendez|tu m'ecoutes)$"),
        ["Cinq sur cinq, {t}.", "Parfaitement, {t}."],
    ),
    # « Wake up. Daddy's home. — Welcome home, sir. »
    (
        re.compile(
            r"^(?:reveille[- ]toi(?:[ ,]+papa est rentre)?|papa est rentre"
            r"|je suis (?:rentre|de retour)(?: a la maison)?)$"
        ),
        ["Bienvenue à la maison, {t}."],
    ),
    (
        re.compile(r"^(?:merci|je te remercie|je vous remercie|thanks|thank you)(?: beaucoup| bien| infiniment)?$"),
        ["Je vous en prie, {t}.", "À votre service, {t}.", "C'est un plaisir, {t}."],
    ),
    (
        re.compile(r"^(?:bonne nuit|dors bien)$"),
        ["Bonne nuit, {t}. Je veille."],
    ),
    (
        re.compile(
            r"^(?:au revoir|a plus tard|a bientot|a demain|a tout a l'heure|ce sera tout|c'est tout"
            r"|mets[- ]toi en veille|repos)(?: merci)?$"
        ),
        ["Bien, {t}. Je reste à votre disposition."],
    ),
]
# Après ces phrases, la conversation est close : le HUD repasse en veille.
_CLOSING = re.compile(r"^(?:merci|je te remercie|je vous remercie|thanks|thank you|bonne nuit|dors bien|au revoir|a |ce sera|c'est tout|mets|repos)")


def smalltalk_reply(text: str) -> Reply | None:
    """Répond sans passer par le modèle aux petites phrases les plus fréquentes."""
    stripped = (text or "").strip()
    core = strip_vocative(stripped)

    # L'utilisateur n'a dit que « Jarvis » : on se tient prêt.
    if stripped and not core:
        line = random.choice(["{t} ?", "À votre écoute, {t}."]).format(t=TITLE)
        return Reply(text=line, data={"attentive": True})

    normalized = strip_accents(core.lower().replace("’", "'"))
    normalized = re.sub(r"[\s!.?,;:]+$", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)

    for pattern, answers in SMALLTALK:
        if pattern.match(normalized):
            data = {"standby": True} if _CLOSING.match(normalized) else {}
            return Reply(text=random.choice(answers).format(t=TITLE), data=data)
    return None
