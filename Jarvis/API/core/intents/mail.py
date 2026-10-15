"""Agent messagerie : envoyer, lire, répondre, chercher, archiver un mail."""

from __future__ import annotations

import re
from typing import Any

from config import load_contacts
from persona import TITLE, fold
from core.intents.common import clean_fragment, clean_name


EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


_MAIL = r"(?:mail|e-?mail|message|courriel)"


def _find_contact(text: str) -> tuple[str, str] | None:
    """Retrouve un contact cité dans la phrase (« envoie un mail à Paul »)."""
    folded = fold(text)
    best: tuple[str, str] | None = None
    for name, email in load_contacts().items():
        key = re.escape(fold(name))
        if re.search(rf"\b(?:a|au|pour|avec)\s+{key}\b", folded):
            # Le nom le plus long l'emporte (« Paul Martin » avant « Paul »).
            if best is None or len(name) > len(best[0]):
                best = (name, email)
    return best


def _normalize_spoken_email(text: str) -> str:
    """Recolle une adresse dictée (« paul arobase exemple point com »)."""
    if "arobase" not in text.lower():
        return text
    normalized = re.sub(r"\s*\barobase\b\s*", "@", text, flags=re.IGNORECASE)
    return re.sub(r"(@[\w-]+(?:\.[\w-]+)*)\s+point\s+([a-z]{2,6})\b", r"\1.\2", normalized, flags=re.IGNORECASE)


def _extract_email(value: str) -> str | None:
    """Extrait la première adresse email détectée dans le texte."""
    match = EMAIL_PATTERN.search(value)
    if not match:
        return None
    return match.group(0)


def extract_recent_email_from_history(history: list[Any], max_messages: int = 8) -> str | None:
    """Récupère la dernière adresse email visible dans l'historique récent."""
    for item in reversed(history[-max_messages:]):
        content = getattr(item, "content", None)
        if content is None and isinstance(item, dict):
            content = item.get("content", "")
        email = _extract_email(str(content or ""))
        if email:
            return email
    return None


def _extract_mail_subject(text: str, quoted_parts: list[str]) -> str:
    """Extrait l'objet d'email à partir de la phrase utilisateur."""
    subject = ""

    subject_quoted = re.search(r'(?:sujet|objet)\s*[:=]?\s*"([^\"]+)"', text, flags=re.IGNORECASE)
    if subject_quoted:
        subject = clean_fragment(subject_quoted.group(1))

    if not subject:
        subject_plain = re.search(
            r"(?:sujet|objet)\s*[:=]?\s*(.+?)(?=(?:\b(?:message|contenu|corps|et\s+dis(?:-|\s)?lui|"
            r"en\s+lui\s+disant|pour\s+lui\s+dire|dis(?:-|\s)?lui)\b|$))",
            text,
            flags=re.IGNORECASE,
        )
        if subject_plain:
            subject = clean_fragment(subject_plain.group(1))

    if not subject and quoted_parts:
        subject = clean_fragment(quoted_parts[0])

    return subject


def _extract_mail_body(text: str) -> tuple[str, bool]:
    """Extrait le corps d'email et indique s'il était explicitement fourni."""
    body = ""
    explicit_body = False
    normalized = text.replace("’", "'")

    body_quoted = re.search(r'(?:message|contenu|corps)\s*[:=]?\s*"([^\"]+)"', text, flags=re.IGNORECASE)
    if body_quoted:
        body = clean_fragment(body_quoted.group(1))
        explicit_body = True

    if not body:
        body_plain = re.search(r"(?:message|contenu|corps)\s*[:=]?\s*(.+)$", text, flags=re.IGNORECASE)
        if body_plain:
            body = clean_fragment(body_plain.group(1))
            explicit_body = True

    if not body:
        natural_patterns = [
            r"(?:et\s+)?dis(?:-|\s)?lui\s+(?:que|qu['’])\s*(.+)$",
            r"(?:et\s+)?dis(?:-|\s)?lui\s+(.+)$",
            r"(?:et\s+)?dit(?:-|\s)?lui\s+(?:que|qu['’])\s*(.+)$",
            r"en\s+lui\s+disant\s+(?:que|qu['’])\s*(.+)$",
            r"pour\s+lui\s+dire\s+(?:que|qu['’])\s*(.+)$",
            r"(?:et|puis)\s+lui\s+dire\s+(?:que|qu['’])\s*(.+)$",
            r"(?:et|puis)\s+lui\s+dire\s+(.+)$",
            r"pour\s+(?:lui\s+)?(?:dire|annoncer|pr[ée]venir|signaler|confirmer)\s+(?:que|qu['’])\s*(.+)$",
            r"pour\s+lui\s+(?:dire|demander|proposer|rappeler)\s+(.+)$",
            # « écris à paul@exemple.com : la réunion est annulée »
            r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+\s*:\s*(.+)$",
            r"\b(?:a|à)\s+[^:@]{2,40}?\s*:\s*(.+)$",
        ]
        for pattern in natural_patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if match:
                body = clean_fragment(match.group(1))
                break

    if not body:
        after_subject = re.search(
            r"(?:sujet|objet)\s*[:=]?\s*(?:\"[^\"]+\"|[^,;]+)\s*(?:,|;|\bet\b)\s*(.+)$",
            text,
            flags=re.IGNORECASE,
        )
        if after_subject:
            candidate = clean_fragment(after_subject.group(1))
            candidate = re.sub(
                r"^(?:et\s+)?(?:dis(?:-|\s)?lui(?:\s+que)?|dit(?:-|\s)?lui(?:\s+que)?|"
                r"en\s+lui\s+disant\s+que|pour\s+lui\s+dire\s+que)\s+",
                "",
                candidate,
                flags=re.IGNORECASE,
            )
            body = clean_fragment(candidate)

    return body, explicit_body


def _references_previous_mail(text: str) -> bool:
    """Détecte si la phrase fait référence à un email déjà évoqué."""
    lowered = text.lower().replace("’", "'")
    patterns = [
        r"\b(?:ce|cet|cette)\s+(?:mail|email|e-mail|message|destinataire|adresse)\b",
        r"\b(?:envoie|envoye|envoi|envoyer|send)\s*(?:-|\s)?(?:le|la|lui)\b",
        r"\b(?:l[' ]?envoyer|lui\s+envoyer|renvoie(?:-|\s)?le)\b",
        r"\b(?:au|a\s+la)\s+m[eé]me\s+(?:mail|email|destinataire|adresse)\b",
    ]
    return any(re.search(pattern, lowered) for pattern in patterns)


def _is_mail_followup_payload(text: str) -> bool:
    """Détecte une réponse de suivi contenant objet/message sans verbe d'envoi."""
    lowered = text.lower().replace("’", "'").strip()
    return bool(
        re.search(
            r"^(?:sujet|objet|message|contenu|corps)\b"
            r"|^(?:et\s+)?dis(?:-|\s)?lui\b"
            r"|^(?:et\s+)?dit(?:-|\s)?lui\b"
            r"|^en\s+lui\s+disant\b"
            r"|^pour\s+lui\s+dire\b",
            lowered,
            flags=re.IGNORECASE,
        )
    )


def parse_send_mail(text: str, fallback_email: str | None = None) -> dict | None:
    """Interprète une demande naturelle d'envoi d'email et renvoie l'action associée."""
    text = _normalize_spoken_email(text)
    lowered = text.lower().replace("’", "'")
    has_mail_term = re.search(r"\b(?:mails?|emails?|e-mails?|courriers?|courriels?|messages?)\b", lowered) is not None
    references_previous_mail = _references_previous_mail(text)
    has_followup_payload = bool(fallback_email) and _is_mail_followup_payload(text)
    # Verbes d'envoi explicites, par opposition aux verbes de rédaction (« écris-moi un poème »).
    has_dispatch_verb = re.search(r"\b(?:envoie|envoye|envoi|envoyer|envoyez|send|exp[ée]die)\b", lowered) is not None
    has_writing_verb = re.search(r"\b(?:[ée]cris|[ée]crit|[ée]crire|r[ée]dige|r[ée]diger)\b", lowered) is not None

    if not (has_dispatch_verb or has_writing_verb) and not has_followup_payload:
        return None

    explicit_email = _extract_email(text)
    contact = None if explicit_email else _find_contact(text)
    has_recipient = explicit_email is not None or contact is not None
    if not has_mail_term and not has_recipient and not references_previous_mail and not has_followup_payload:
        return None

    to_email = explicit_email or (contact[1] if contact else None)
    to_name = contact[0] if contact else None
    if not to_email and (references_previous_mail or has_followup_payload):
        to_email = fallback_email

    if not to_email:
        # « Rédige un message d'anniversaire » : pas un envoi, le modèle s'en charge.
        if not has_dispatch_verb:
            return None
        return {
            "action": "command_error",
            "message": (
                f"Il me faut l'adresse du destinataire, {TITLE}. Dites par exemple : "
                "envoie un mail à client@exemple.com pour lui dire que le devis est prêt."
            ),
        }

    recipient = to_name or to_email
    quoted_parts = re.findall(r'"([^\"]+)"', text)
    subject = _extract_mail_subject(text, quoted_parts)
    body, explicit_body = _extract_mail_body(text)

    if not body:
        if subject:
            return {
                "action": "command_error",
                "message": (
                    f"Je peux écrire à {recipient} avec l'objet « {subject} », {TITLE}, "
                    "mais il me manque le message. Que dois-je lui dire ?"
                ),
            }
        return {
            "action": "command_error",
            "message": f"Je peux écrire à {recipient}, {TITLE}. Que dois-je lui dire ?",
        }

    auto_subject = not bool(subject)
    auto_draft = False
    auto_polish = bool(body) and not explicit_body

    return {
        "action": "send_mail",
        "params": {
            "to_email": to_email,
            "to_name": to_name,
            "subject": subject,
            "body": body,
            "auto_subject": auto_subject,
            "auto_draft": auto_draft,
            "auto_polish": auto_polish,
            "draft_context": text,
            # Demande formulée en langage naturel : Jarvis montre le message avant de l'envoyer.
            "confirm": True,
        },
    }


def parse_mail_reading(text: str) -> dict | None:
    """Interprète les demandes de lecture de la messagerie."""
    folded = fold(text)
    has_mail = re.search(
        r"\b(?:mails?|emails?|e-mails?|courriers?|courriels?|messagerie|boite (?:mail|de reception|aux lettres))\b"
        r"|\bnouveaux messages\b|\bmessages non lus\b|\bqui m'a ecrit\b",
        folded,
    )
    if not has_mail:
        return None
    # Supprimer, archiver ou répondre n'est pas lire : ces demandes ne sont pas prises en charge.
    if re.search(r"\b(?:supprime|efface|archive|reponds|repondre|transfere|marque)\b", folded):
        return None

    if re.search(r"\b(?:dernier|derniere|latest|plus recent)\b", folded):
        return {"action": "mail_last"}
    if re.search(
        r"\b(?:resume|lis|lire|consulte|consulter|verifie|verifier|regarde|regarder|check|checker|montre|montrer"
        r"|affiche|afficher|non lus?|nouveaux?|recu|releve)\b"
        r"|\bai[- ]je\b|\best[- ]ce que j'ai\b|\bj'ai des\b|\bquoi de neuf\b|\bqui m'a ecrit\b",
        folded,
    ):
        return {"action": "mail_resume"}
    return None


def parse_mail_more(text: str) -> dict | None:
    """Répondre, lire en entier, chercher, archiver ou supprimer un mail."""
    clean = text.strip().replace("’", "'")
    reply = re.match(
        rf"^(?:r[ée]ponds?|r[ée]pondez)(?:[- ]lui)?\s+(?:au (?:dernier )?{_MAIL}\s+(?:de|d')\s*|(?:à|a)\s+)?(?P<who>[^:]*?)\s*"
        r"(?:\bque\b|\bqu'|\bpour (?:lui )?dire que\b|:)\s*(?P<body>.+)$",
        clean, flags=re.IGNORECASE,
    )
    if reply:
        return {"action": "reply_mail", "params": {"who": clean_name(reply["who"]), "body": reply["body"].strip(), "confirm": True}}

    read = re.match(
        rf"^(?:lis|lit|lire|ouvre|montre|affiche)(?:[- ]moi)?\s+(?:le|son)\s+(?:dernier\s+)?{_MAIL}\s+"
        r"(?:de|d'|du|des|venant de|envoy[ée] par)\s*(?P<who>.+)$",
        clean, flags=re.IGNORECASE,
    )
    if read:
        return {"action": "read_mail", "params": {"who": clean_name(read["who"])}}

    search = re.match(
        rf"^(?:cherche|recherche|trouve|retrouve)(?:[- ]moi)?\s+(?:les |des |le |un |mes )?{_MAIL}s?\s+"
        r"(?:de|d'|du|des|sur|concernant|à propos de|a propos de|qui parlent? de|avec|venant de)\s*(?P<who>.+)$",
        clean, flags=re.IGNORECASE,
    )
    if search:
        return {"action": "search_mail", "params": {"who": clean_name(search["who"])}}

    tidy = re.match(
        rf"^(?P<verb>archive|supprime|efface|jette|mets? (?:à|a) la corbeille)\s+(?:le|ce|mon)\s+(?:dernier\s+)?{_MAIL}"
        r"(?:\s+(?:de|d'|du|des)\s*(?P<who>.+))?$",
        clean, flags=re.IGNORECASE,
    )
    if tidy:
        action = "archive_mail" if tidy["verb"].lower() == "archive" else "trash_mail"
        return {"action": action, "params": {"who": clean_name(tidy["who"] or ""), "confirm": True}}
    return None
