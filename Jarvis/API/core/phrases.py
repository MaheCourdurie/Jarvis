"""Les tournures des nouvelles capacités : une fonction par famille de phrases.

core/intents.py reconnaît les commandes historiques ; ce fichier, celles ajoutées ensuite
(mails avancés, poste, météo étendue, mémoire, musique, maison…). detect_action les appelle
dans un ordre précis : une phrase est confiée au premier parseur qui la reconnaît.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from core.intents import (
    WEEKDAY_INDEX,
    _extract_day_period_bounds,
    _extract_relative_delay,
    _extract_time_of_day,
    _apply_day_period,
    _fold,
    _normalize_spoken_time,
    _parse_datetime_expression,
)
from persona import TITLE

WEEKDAY_CODES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
_DAY = r"(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)"
_MAIL = r"(?:mail|e-?mail|message|courriel)"
_ARTICLES = re.compile(r"^(?:du|de la|de l'|des|un|une|le|la|les|l'|d')\s*", re.IGNORECASE)


def _strip(value: str) -> str:
    return value.strip().strip(" .!?,;:«»\"'")


# ── Récurrence (alarmes et agenda) ─────────────────────────────────────────

def extract_repeat(folded: str) -> dict | None:
    """« tous les jours », « en semaine », « tous les mardis et jeudis » → codes alarme et agenda."""
    # « tous les jours de semaine » avant « tous les jours ».
    if re.search(r"\ben semaine\b|\bdu lundi au vendredi\b|\bjours? (?:de (?:la )?semaine|ouvres?)\b", folded):
        return {"alarm": "weekdays", "rrule": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", "label": "du lundi au vendredi"}
    if re.search(r"\btous les jours\b|\bchaque jour\b|\bquotidien", folded):
        return {"alarm": "daily", "rrule": "FREQ=DAILY", "label": "tous les jours"}
    days_match = re.search(rf"\b(?:tous les|chaque)\s+({_DAY}s?(?:\s*(?:,|et)\s*{_DAY}s?)*)", folded)
    if days_match:
        days = sorted({WEEKDAY_INDEX[name] for name in re.findall(_DAY, days_match.group(1))})
        names = [list(WEEKDAY_INDEX)[day] + "s" for day in days]
        label = "tous les " + (names[0] if len(names) == 1 else ", ".join(names[:-1]) + " et " + names[-1])
        return {
            "alarm": "weekly:" + ",".join(map(str, days)),
            "rrule": "FREQ=WEEKLY;BYDAY=" + ",".join(WEEKDAY_CODES[day] for day in days),
            "label": label,
            "days": days,
        }
    if re.search(r"\btoutes les semaines\b|\bchaque semaine\b|\bhebdomadaire", folded):
        return {"alarm": "weekly", "rrule": "FREQ=WEEKLY", "label": "toutes les semaines"}
    return None


def first_occurrence(text: str, repeat: dict) -> datetime | None:
    """Première échéance d'une répétition : l'heure dite, le premier jour concerné à venir."""
    normalized = _normalize_spoken_time(text)
    clock = _extract_time_of_day(normalized)
    if clock is None:
        return None
    hour = _apply_day_period(clock[0], normalized.lower())
    now = datetime.now()
    candidate = now.replace(hour=hour, minute=clock[1], second=0, microsecond=0)
    days = set(repeat.get("days") or (range(5) if repeat["alarm"] == "weekdays" else range(7)))
    for _ in range(8):
        if candidate > now and candidate.weekday() in days:
            return candidate
        candidate += timedelta(days=1)
    return None


# ── Messagerie avancée ─────────────────────────────────────────────────────

def parse_mail_more(text: str) -> dict | None:
    """Répondre, lire en entier, chercher, archiver ou supprimer un mail."""
    clean = text.strip().replace("’", "'")
    reply = re.match(
        rf"^(?:r[ée]ponds?|r[ée]pondez)(?:[- ]lui)?\s+(?:au (?:dernier )?{_MAIL}\s+(?:de|d')\s*|(?:à|a)\s+)?(?P<who>[^:]*?)\s*"
        r"(?:\bque\b|\bqu'|\bpour (?:lui )?dire que\b|:)\s*(?P<body>.+)$",
        clean, flags=re.IGNORECASE,
    )
    if reply:
        return {"action": "reply_mail", "params": {"who": _strip(reply["who"]), "body": reply["body"].strip(), "confirm": True}}

    read = re.match(
        rf"^(?:lis|lit|lire|ouvre|montre|affiche)(?:[- ]moi)?\s+(?:le|son)\s+(?:dernier\s+)?{_MAIL}\s+"
        r"(?:de|d'|du|des|venant de|envoy[ée] par)\s*(?P<who>.+)$",
        clean, flags=re.IGNORECASE,
    )
    if read:
        return {"action": "read_mail", "params": {"who": _strip(read["who"])}}

    search = re.match(
        rf"^(?:cherche|recherche|trouve|retrouve)(?:[- ]moi)?\s+(?:les |des |le |un |mes )?{_MAIL}s?\s+"
        r"(?:de|d'|du|des|sur|concernant|à propos de|a propos de|qui parlent? de|avec|venant de)\s*(?P<who>.+)$",
        clean, flags=re.IGNORECASE,
    )
    if search:
        return {"action": "search_mail", "params": {"who": _strip(search["who"])}}

    tidy = re.match(
        rf"^(?P<verb>archive|supprime|efface|jette|mets? (?:à|a) la corbeille)\s+(?:le|ce|mon)\s+(?:dernier\s+)?{_MAIL}"
        r"(?:\s+(?:de|d'|du|des)\s*(?P<who>.+))?$",
        clean, flags=re.IGNORECASE,
    )
    if tidy:
        action = "archive_mail" if tidy["verb"].lower() == "archive" else "trash_mail"
        return {"action": action, "params": {"who": _strip(tidy["who"] or ""), "confirm": True}}
    return None


# ── Alarmes : répétition ───────────────────────────────────────────────────

def parse_snooze(text: str) -> dict | None:
    """« Encore 5 minutes », « snooze », « laisse-moi dormir ».»"""
    folded = _fold(text).strip(" .!?")
    if not re.match(r"^(?:encore|snooze|repete|repousse|laisse[- ]moi (?:encore )?dormir)\b", folded):
        return None
    if not (re.search(r"minute|alarme|reveil|dormir|snooze", folded) or folded in {"encore", "repete"}):
        return None
    delay = _extract_relative_delay(text)
    minutes = max(1, round(delay.total_seconds() / 60)) if delay else 5
    return {"action": "snooze_alarm", "params": {"minutes": minutes}}


def recurring_alarm(text: str, title: str) -> dict | None:
    """Une alarme qui revient : « réveille-moi tous les jours de semaine à 7h »."""
    repeat = extract_repeat(_fold(text))
    if repeat is None:
        return None
    if repeat["alarm"] == "weekly":
        when = _parse_datetime_expression(text)
        if when is None:
            return None
        repeat = {**repeat, "alarm": f"weekly:{when.weekday()}"}
    else:
        when = first_occurrence(text, repeat)
    if when is None:
        return {"action": "command_error", "message": f"À quelle heure, {TITLE} ? Par exemple : réveille-moi tous les jours à 7 h."}
    return {"action": "set_alarm", "params": {"when": when.isoformat(), "title": title, "kind": "alarm", "repeat": repeat["alarm"]}}


# ── Agenda : déplacer ──────────────────────────────────────────────────────

def parse_move_event(text: str) -> dict | None:
    """« Décale le dentiste à 16h », « déplace la réunion de demain à jeudi 10h »."""
    clean = _normalize_spoken_time(text.strip().replace("’", "'").rstrip(" .!?"))
    match = re.match(
        r"^(?:d[ée]cale|d[ée]place|repousse|avance|reporte|change l'heure d[ue])\s+(?:le |la |l'|mon |ma |mes |les )?"
        r"(?P<what>.+?)\s+(?:à|a|au|pour|vers|jusqu'à)\s+(?P<target>[^,]+)$",
        clean, flags=re.IGNORECASE,
    )
    if not match:
        return None
    what = match["what"]
    if re.search(r"\b(?:alarme|r[ée]veil|minuteur|rappel)\b", _fold(what)):
        return None
    day = _extract_day_period_bounds(what)
    query = re.sub(rf"\s+(?:de|du|d')\s*(?:demain|aujourd'hui|ce (?:matin|soir)|{_DAY}(?: prochain)?)\b.*$", "", what, flags=re.IGNORECASE)
    target_text = match["target"]
    target = _parse_datetime_expression(target_text)
    if target is None:
        return {"action": "command_error", "message": f"À quel moment dois-je le déplacer, {TITLE} ? Par exemple : décale le dentiste à 16 h."}
    time_only = not re.search(rf"\b(?:demain|apr[eè]s-demain|{_DAY}|\d{{1,2}}/\d{{1,2}}|\d{{4}}-\d{{2}})", _fold(target_text))
    params = {"query": _strip(query), "target": target.isoformat(), "time_only": time_only}
    if day is not None:
        params["from"], params["to"] = day[0].isoformat(), day[1].isoformat()
    return {"action": "move_event", "params": params}


# ── Poste : écran, apparence, réseau ───────────────────────────────────────

def _on_off(folded: str) -> bool:
    return not re.search(r"\b(?:coupe|desactive|eteins?|arrete|enleve|retire|quitte|stoppe|sors? d[ue])\b", folded)


def parse_poste(text: str) -> dict | None:
    folded = _fold(text).strip(" .!?")
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


# ── Notes et listes ────────────────────────────────────────────────────────

def parse_notes(text: str) -> dict | None:
    clean = text.strip().replace("’", "'").rstrip(" .!")
    folded = _fold(clean)
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
        items = [_ARTICLES.sub("", item.strip()) for item in re.split(r",|\bet\b", add["items"]) if item.strip()]
        return {"action": "add_to_list", "params": {"items": items, "list": _list_name(add["list"])}}

    if re.search(r"\b(?:qu'est-ce qu'il y a|quoi|que reste-t-il|montre|lis|affiche|c'est quoi)\b.*\b(?:ma|la) liste\b", folded):
        name = re.search(r"\bliste (?:de |des |du |d')\s*([\w' -]+)", folded)
        return {"action": "read_list", "params": {"list": _list_name(name.group(1) if name else None)}}
    return None


def _list_name(raw: str | None) -> str:
    name = _strip(raw or "")
    return "Courses" if not name or _fold(name).startswith("course") else name


# ── Mémoire ────────────────────────────────────────────────────────────────

def parse_memory(text: str) -> dict | None:
    clean = text.strip().replace("’", "'").rstrip(" .!")
    folded = _fold(clean)
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


# ── Météo étendue ──────────────────────────────────────────────────────────

def weather_day(folded: str):
    """Le jour demandé pour la météo : today, tomorrow, weekend, week, ou un décalage en jours."""
    if re.search(r"\bweek-?end\b", folded):
        return "weekend"
    if re.search(r"\b(?:cette|la|de la|sur la) semaine\b|\bprochains jours\b|\b7 jours\b|\bjours qui viennent\b|\bsemaine prochaine\b", folded):
        return "week"
    if re.search(r"\bapres-demain\b", folded):
        return 2
    later = re.search(r"\bdans (\d) jours\b", folded)
    if later:
        return int(later.group(1))
    if re.search(r"\bdemain\b", folded):
        return "tomorrow"
    for name, index in WEEKDAY_INDEX.items():
        if re.search(rf"\b{name}\b", folded):
            offset = (index - datetime.now().weekday()) % 7
            return {0: "today", 1: "tomorrow"}.get(offset, offset)
    return "today"


def parse_sky(text: str) -> dict | None:
    folded = _fold(text)
    if re.search(r"\b(?:lever|coucher) du soleil\b|\bsoleil se (?:leve|couche)\b|\bse (?:leve|couche) le soleil\b|\bfait nuit\b", folded):
        return {"action": "sun", "params": {"day": "tomorrow" if "demain" in folded else "today"}}
    if re.search(r"\bqualite de l'air\b|\bpollution\b|\bl'air est (?:pollue|bon)\b", folded):
        return {"action": "air_quality", "params": {}}
    return None


# ── Traduction ─────────────────────────────────────────────────────────────

_LANGUAGES = (
    r"anglais|espagnol|allemand|italien|portugais|arabe|chinois|japonais|russe|neerlandais|néerlandais|polonais"
    r"|turc|coreen|coréen|grec|suedois|suédois|latin|breton|occitan|catalan|hebreu|hébreu|hindi|francais|français"
)


def parse_translate(text: str) -> dict | None:
    clean = text.strip().replace("’", "'").rstrip(" ?!.")
    match = re.match(
        rf"^(?:comment (?:on dit|dit-on|dire|se dit|tu dis)|traduis|traduire|tu peux traduire|peux-tu traduire|c'est quoi|que veut dire)"
        rf"\s+(?:en (?P<lang1>{_LANGUAGES})\s*:?\s*)?(?P<text>.+?)(?:\s+en (?P<lang2>{_LANGUAGES}))?$",
        clean, flags=re.IGNORECASE,
    )
    if not match or not (match["lang1"] or match["lang2"]):
        return None
    language = (match["lang1"] or match["lang2"]).lower()
    return {"action": "translate", "params": {"text": _strip(match["text"]), "language": language}}


# ── Trajets ────────────────────────────────────────────────────────────────

def parse_travel(text: str) -> dict | None:
    clean = text.strip().replace("’", "'").rstrip(" ?!.")
    folded = _fold(clean)
    if not re.search(
        r"\bcombien de (?:temps|minutes|km|kilometres)\b|\btemps de (?:trajet|route|parcours)\b|\bquelle distance\b"
        r"|\bje mets combien\b|\bitineraire\b|\bc'est loin\b|\bcombien de route\b",
        folded,
    ):
        return None
    mode = "pied" if re.search(r"\ba pied\b|\ben marchant\b", folded) else "velo" if re.search(r"\b(?:a|en) velo\b", folded) else "voiture"
    rest = re.sub(r"\s+(?:à|a|en)\s+(?:pied|v[ée]lo|voiture)\b|\s+en marchant\b", "", clean, flags=re.IGNORECASE)
    dest = re.search(
        r"(?:pour aller|pour rejoindre|jusqu'(?:à|a|au)|aller (?:à|a|au|jusqu'à)|vers|pour)\s+(?:à |a |au |aux |la |le |l')?(?P<dest>.+)$"
        r"|\b(?:à|a|au|aux)\s+(?P<dest2>[^,]+)$",
        rest, flags=re.IGNORECASE,
    )
    if not dest:
        return {"action": "command_error", "message": f"Pour aller où, {TITLE} ?"}
    destination = _strip(dest["dest"] or dest["dest2"])
    destination = re.sub(r"^(?:c'est loin\s+)?(?:d'ici\s+)?(?:à|a|au)\s+", "", destination, flags=re.IGNORECASE)
    destination = re.sub(r"^(?:(?:à|a|au|aux|la|le|les)\s+|l')+", "", destination, flags=re.IGNORECASE)
    origin = re.search(r"\bdepuis\s+(?P<origin>.+?)(?:\s+(?:jusqu|pour|vers|à|a)\b|$)", clean, flags=re.IGNORECASE)
    params = {"destination": destination, "mode": mode}
    if origin:
        params["origin"] = _strip(origin["origin"])
        params["destination"] = re.sub(r"\s+depuis\s+.+$", "", destination, flags=re.IGNORECASE)
    return {"action": "travel_time", "params": params}


# ── Fichiers ───────────────────────────────────────────────────────────────

_FILE = r"(?:fichier|document|pdf|dossier|photo|image|presentation|présentation|tableur|rapport|facture)s?"


def _file_query(raw: str) -> str:
    query = re.sub(r"^(?:nomm[ée]|appel[ée]|intitul[ée]|qui s'appelle|qui se nomme|sur|de)\s+", "", raw.strip(), flags=re.IGNORECASE)
    return _strip(query)


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


# ── Vision ─────────────────────────────────────────────────────────────────

def parse_vision(text: str) -> dict | None:
    folded = _fold(text)
    if re.search(
        r"\b(?:regarde|vois|lis|decris|analyse)(?:[- ](?:moi|tu))?\s+(?:mon |l'|ce qu'il y a (?:sur|a) (?:mon |l'))ecran\b"
        r"|\bqu'est-ce qu'il y a (?:sur|a) (?:mon |l')ecran\b|\btu vois (?:quoi|mon ecran|ce qu'il y a)\b"
        r"|\bqu'est-ce que tu vois\b|\bque vois-tu\b|\bsur mon ecran\b",
        folded,
    ):
        return {"action": "look_screen", "params": {"question": text.strip()}}
    return None


# ── Musique ────────────────────────────────────────────────────────────────

def parse_music(text: str) -> dict | None:
    clean = text.strip().replace("’", "'").rstrip(" .!?")
    folded = _fold(clean)
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
    if query and not re.fullmatch(r"(?:de la |la |un peu de )?musique", _fold(query["q"])):
        return command("play_query", _strip(query["q"]))
    if re.match(r"^(?:mets|met|lance|joue|passe)(?:[- ]moi)?\s+(?:de la |la |un peu de |une )?musique\b", folded):
        return command("play")
    return None


# ── Maison connectée (Raccourcis) ──────────────────────────────────────────

def parse_home(text: str) -> dict | None:
    clean = text.strip().rstrip(" .!?")
    folded = _fold(clean)
    named = re.match(r"^(?:lance|execute|demarre)\s+(?:le |mon )?raccourci\s+(?P<name>.+)$", folded)
    if named:
        name = re.match(r"^(?:lance|exécute|execute|démarre|demarre)\s+(?:le |mon )?raccourci\s+(?P<name>.+)$", clean, flags=re.IGNORECASE)
        return {"action": "run_shortcut", "params": {"name": _strip(name["name"] if name else named["name"])}}
    if re.search(r"\b(?:quels sont|liste|montre(?:-moi)?) (?:mes |les )raccourcis\b", folded):
        return {"action": "list_shortcuts"}
    if re.match(r"^(?:allume|eteins?|ouvre|ferme|active|desactive|tamise|baisse|monte|lance)\b", folded) and re.search(
        r"\b(?:lumieres?|lampes?|volets?|stores?|prises?|chauffage|thermostat|clim(?:atisation)?|portail|garage|ventilateur"
        r"|salon|cuisine|chambre|salle de bain|bureau|entree|jardin|alarme de la maison)\b",
        folded,
    ):
        return {"action": "run_shortcut", "params": {"phrase": clean}}
    return None


# ── Routines ───────────────────────────────────────────────────────────────

def parse_routines(text: str) -> dict | None:
    clean = text.strip().rstrip(" .!?")
    folded = _fold(clean)
    create = re.match(r"^(?:cr[ée]e|ajoute|enregistre|nouvelle)\s+(?:une |la |ma )?routine\s+(?P<name>[^:]+?)\s*:\s*(?P<steps>.+)$", clean, flags=re.IGNORECASE)
    if create:
        return {"action": "create_routine", "params": {"name": _strip(create["name"]), "steps": create["steps"]}}
    if re.search(r"\b(?:quelles sont|liste|montre(?:-moi)?) (?:mes |les )routines\b", folded):
        return {"action": "list_routines"}
    run = re.match(r"^(?:lance|active|demarre|execute|passe en|on passe en)?\s*(?:la routine|ma routine|le mode|mode)\s+(?P<name>[\w' -]+)$", folded)
    if run:
        return {"action": "run_routine", "params": {"name": run["name"].strip()}}
    return None


# ── Web : résumer une page, ouvrir Wikipédia ───────────────────────────────

def parse_encyclopedia(text: str) -> dict | None:
    match = re.match(
        r"^(?:ouvre|cherche|montre)(?:[- ]moi)?\s+(?:la page\s+)?(?:de\s+|d')?wikip[ée]dia\s+(?:sur|de|du|des|pour|concernant|à propos de)\s+(?P<q>.+)$",
        text.strip().rstrip(" .!?"), flags=re.IGNORECASE,
    )
    if not match:
        return None
    return {"action": "web_search", "params": {"query": _strip(match["q"]), "engine": "wikipedia"}}


def parse_summarize_url(text: str) -> dict | None:
    if not re.search(r"\b(?:r[ée]sume|r[ée]sum[ée]|que dit|de quoi parle|lis)\b", text, flags=re.IGNORECASE):
        return None
    url = re.search(r"https?://\S+|www\.\S+|\b[\w-]+\.(?:fr|com|org|net|io|eu|info)(?:/\S*)?", text)
    if not url:
        return None
    return {"action": "summarize_url", "params": {"url": url.group(0).rstrip(".,;!?)")}}
