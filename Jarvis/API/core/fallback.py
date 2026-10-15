"""Quand le routeur ne reconnaît pas une phrase qui ressemble pourtant à un ordre.

1. Le modèle choisit, dans une liste fermée d'actions sûres, celle qui correspond (routage de secours).
2. La phrase est notée dans le journal des incompris (JARVIS_MISSES_FILE), pour l'apprendre ensuite
   au routeur et l'ajouter à l'examen des agents.

Seules les actions qu'on peut exécuter avec la phrase brute sont proposées : rien qui envoie,
supprime ou demande une date précise. Ces cas restent au routeur, qui sait les comprendre en détail.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from typing import Callable, Optional

from config import MISSES_FILE
from persona import fold
from services import llm

_lock = threading.Lock()

# Phrase à l'impératif (ou « peux-tu … ») : probablement un ordre plutôt qu'une question.
_COMMAND = re.compile(
    r"^(?:(?:peux|pourrais|pouvez|pourriez)[- ](?:tu|vous)\s+|tu peux\s+|est-ce que tu peux\s+|j'aimerais que tu\s+|je veux que tu\s+)?"
    r"(?:m'|me\s+)?(?:ouvre|ferme|lance|mets|met|montre|affiche|donne|lis|cree|ecris|envoie|ajoute|supprime|efface|annule"
    r"|active|desactive|allume|eteins|baisse|monte|augmente|diminue|change|programme|regle|joue|passe|cherche|trouve"
    r"|verifie|check|prepare|redige|dessine|traduis|enregistre|note|arrete|coupe|demarre|range|trie|regarde|retiens"
    r"|resume|calcule|planifie|reserve|commande|imprime|copie|deplace|renomme|telecharge|sauvegarde|verrouille|bloque)\b"
)

# Actions proposées au modèle : nom → (description, paramètres construits à partir de la phrase).
CATALOG: dict[str, tuple[str, Callable[[str], dict]]] = {
    "mail_resume": ("résumer les mails non lus", lambda text: {}),
    "events_week": ("montrer l'agenda de la semaine", lambda text: {}),
    "availability_week": ("donner les créneaux libres de la semaine", lambda text: {}),
    "list_alarms": ("lister les alarmes et minuteurs", lambda text: {}),
    "time": ("dire l'heure", lambda text: {}),
    "date": ("dire la date", lambda text: {}),
    "weather": ("donner la météo d'aujourd'hui", lambda text: {"day": "today"}),
    "briefing": ("faire le point sur la journée", lambda text: {}),
    "system_status": ("faire l'état de l'ordinateur (batterie, mémoire, processeur)", lambda text: {}),
    "screenshot": ("faire une capture d'écran", lambda text: {}),
    "look_screen": ("regarder l'écran et répondre à une question sur ce qui s'y trouve", lambda text: {"question": text}),
    "write_code": ("écrire un programme ou un script", lambda text: {"request": text}),
    "design_page": ("créer une page web ou un site", lambda text: {"request": text}),
    "design_logo": ("dessiner un logo", lambda text: {"request": text}),
    "design_palette": ("proposer une palette de couleurs", lambda text: {"request": text}),
    "write_document": ("rédiger un document (lettre, CV, compte-rendu…)", lambda text: {"request": text}),
    "list_creations": ("lister les créations de l'atelier", lambda text: {}),
    "recall": ("dire ce que Jarvis sait de l'utilisateur", lambda text: {}),
    "list_routines": ("lister les routines", lambda text: {}),
    "list_shortcuts": ("lister les raccourcis de la maison", lambda text: {}),
    "run_shortcut": ("piloter un appareil de la maison connectée (lumière, volets, prise…)", lambda text: {"phrase": text}),
    "read_list": ("lire la liste de courses", lambda text: {}),
}

PROMPT = """Tu es le répartiteur de J.A.R.V.I.S. Une phrase de l'utilisateur n'a pas été reconnue.
Choisis l'action qui y répond, uniquement si elle correspond clairement :
{catalog}
Si aucune ne convient (question générale, discussion, demande impossible), réponds "none".
Réponds uniquement en JSON : {{"action": "<nom>"}}"""


def looks_like_command(text: str) -> bool:
    return _COMMAND.match(fold(text).strip()) is not None


def guess_action(text: str, available: set[str]) -> Optional[dict]:
    """Demande au modèle quelle action correspond ; None s'il n'y en a pas (ou s'il hésite)."""
    choices = {name: entry for name, entry in CATALOG.items() if name in available}
    catalog = "\n".join(f"- {name} : {description}" for name, (description, _) in choices.items())
    try:
        answer = llm.complete(PROMPT.format(catalog=catalog), text, 0.0, 30, timeout=20, json_mode=True)
        action = str(json.loads(answer).get("action") or "").strip()
    except Exception as exc:
        print(f"[ROUTAGE] Secours impossible: {exc}", flush=True)
        return None
    if action not in choices:
        return None
    return {"action": action, "params": choices[action][1](text)}


def record_miss(text: str, guessed: Optional[str]) -> None:
    """Note la phrase incomprise (et ce que le modèle en a fait) dans le journal."""
    entry = {"time": datetime.now().isoformat(timespec="seconds"), "phrase": text, "modele": guessed or "conversation"}
    try:
        with _lock:
            MISSES_FILE.parent.mkdir(parents=True, exist_ok=True)
            with MISSES_FILE.open("a", encoding="utf-8") as journal:
                journal.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"[ROUTAGE] Journal des incompris inaccessible: {exc}", flush=True)


def recent_misses(limit: int = 30) -> list[dict]:
    try:
        lines = MISSES_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries = []
    for line in lines[-limit:]:
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries
