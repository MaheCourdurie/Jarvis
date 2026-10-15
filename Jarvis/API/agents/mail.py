from __future__ import annotations

import re
import unicodedata
from typing import Any

from services import llm
from core.agent import Agent, Handler
from config import MAIL_TRIAGE, load_contacts
from persona import Reply, TITLE, plural


# Nombre de non lus relevés (et triés par le modèle) quand on demande ses mails.
MAIL_RESUME_LIMIT = 8

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

DISALLOWED_MAIL_PATTERNS = [
    re.compile(r"\b(?:bite|teub|zizi|sexe|porn|porno|sodom(?:ie|iser|ise))\b", flags=re.IGNORECASE),
    re.compile(r"\b(?:nique|niquer|encul(?:e|er|é)|pute|salope|connard|connasse|fdp|batard|b[aâ]tard)\b", flags=re.IGNORECASE),
    re.compile(r"\b(?:suce|sucer|branle|branler|fellation|suicide|suicider)\b", flags=re.IGNORECASE),
]

# Détection secondaire après suppression des séparateurs (espaces/ponctuation),
# pour bloquer des contournements du type "z i z i" ou "sui ci der".
DISALLOWED_MAIL_COMPACT_TERMS = {
    "pipi",
    "bite",
    "teub",
    "zizi",
    "sexe",
    "porn",
    "porno",
    "sodomie",
    "sodomiser",
    "sodomise",
    "niquer",
    "encule",
    "enculer",
    "pute",
    "salope",
    "connard",
    "connasse",
    "fdp",
    "batard",
    "suce",
    "sucer",
    "branle",
    "branler",
    "fellation",
    "suicide",
    "suicider",
}

SUBJECT_STOPWORDS = {
    "a",
    "au",
    "aux",
    "avec",
    "ce",
    "cet",
    "cette",
    "ces",
    "dans",
    "de",
    "des",
    "du",
    "en",
    "et",
    "faut",
    "est",
    "es",
    "suis",
    "sommes",
    "sont",
    "etre",
    "être",
    "aller",
    "allez",
    "vais",
    "va",
    "vont",
    "il",
    "je",
    "lui",
    "mail",
    "message",
    "objet",
    "par",
    "pour",
    "que",
    "qui",
    "sujet",
    "sur",
    "te",
    "tu",
    "un",
    "une",
    "via",
    "dire",
    "dit",
    "dis",
    "email",
    "envoi",
    "envoie",
    "envoye",
    "envoyer",
    "jarvis",
    "pense",
    "veux",
    "veut",
    "souhaite",
    "propose",
    "court",
    "claire",
    "clair",
    "professionnel",
    "professionnelle",
    "tactueux",
    "tacteuse",
    "peu",
    "plus",
    "moins",
}


def _normalize_subject_source(value: str) -> str:
    """Normalise une chaîne pour en extraire des mots-clés d'objet."""
    normalized = (value or "").lower().replace("’", "'")
    normalized = EMAIL_PATTERN.sub(" ", normalized)
    normalized = re.sub(r"[^a-z0-9à-ÿ'\-\s]", " ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _extract_subject_keywords(value: str) -> list[str]:
    """Extrait des mots-clés pertinents pour l'objet d'email."""
    normalized = _normalize_subject_source(value)
    if not normalized:
        return []

    words: list[str] = []
    for raw_word in normalized.split():
        word = raw_word.strip("-' ")
        if not word:
            continue

        if "'" in word:
            prefix, suffix = word.split("'", 1)
            if prefix in {"l", "d", "j", "t", "m", "n", "s", "c", "qu"} and suffix:
                word = suffix

        if len(word) < 3 or word.isdigit() or word in SUBJECT_STOPWORDS:
            continue
        if word in words:
            continue
        words.append(word)
    return words


def _format_two_word_subject(words: list[str]) -> str:
    """Construit un objet d'email de 1 à 2 mots maximum."""
    if not words:
        return ""
    return " ".join(word.capitalize() for word in words[:2])


def _normalize_mail_text(value: str) -> str:
    """Normalise un texte pour comparer deux variantes de contenu mail."""
    normalized = (value or "").lower().replace("’", "'")
    normalized = re.sub(r"[^a-z0-9à-ÿ\s']", " ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _looks_like_unpolished_copy(generated: str, original: str) -> bool:
    """Détecte si le modèle a renvoyé le brouillon brut (ou quasi brut)."""
    generated_norm = _normalize_mail_text(generated)
    original_norm = _normalize_mail_text(original)
    if not generated_norm or not original_norm:
        return False

    if generated_norm == original_norm:
        return True

    # Tolère une variation minime (ponctuation/courte extension) mais pas une vraie reformulation.
    return generated_norm.startswith(original_norm) and len(generated_norm) <= len(original_norm) + 12


def _contains_disallowed_mail_content(*values: str) -> bool:
    """Détecte un contenu offensant/inapproprié dans le texte d'email."""
    text = " ".join(value for value in values if value)
    if not text:
        return False

    normalized = unicodedata.normalize("NFKD", text.replace("’", "'").lower())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))

    if any(pattern.search(normalized) for pattern in DISALLOWED_MAIL_PATTERNS):
        return True

    compact = re.sub(r"[^a-z0-9]+", "", normalized)
    if not compact:
        return False

    return any(term in compact for term in DISALLOWED_MAIL_COMPACT_TERMS)


def normalize_generated_french(text: str) -> str:
    """Corrige quelques fautes récurrentes produites par le modèle."""
    normalized = text or ""
    fixes = [
        (r"\bluiphones\b", "lui téléphones"),
        (r"\bluiphone\b", "lui téléphones"),
        (r"\bluiphoner\b", "lui téléphoner"),
    ]
    for pattern, replacement in fixes:
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
    return normalized


def _sender(item: dict) -> str:
    return item.get("from", {}).get("emailAddress", {}).get("name") or "Expéditeur inconnu"


def format_mail_resume(items: list[dict], limit: int = 5) -> Reply:
    """Construit le résumé des emails non lus (affichage + version orale)."""
    if not items:
        return Reply(text=f"Aucun message non lu, {TITLE}. Votre boîte de réception est à jour.", data={"unread": 0})

    count = len(items)
    if count >= limit:
        headline = f"Voici vos {count} derniers messages non lus, {TITLE} :"
        spoken_count = f"Vous avez au moins {count} messages non lus"
    else:
        headline = f"Vous avez {plural(count, 'message non lu', 'messages non lus')}, {TITLE} :"
        spoken_count = f"Vous avez {plural(count, 'message non lu', 'messages non lus')}"

    lines = [headline]
    for idx, item in enumerate(items, start=1):
        subject = item.get("subject") or "(sans objet)"
        preview = (item.get("bodyPreview") or "").replace("\n", " ").strip()
        if len(preview) > 90:
            preview = preview[:90] + "..."
        lines.append(f"{idx}. {_sender(item)} — {subject}")
        if preview:
            lines.append(f"   {preview}")

    first = items[0]
    speech = f"{spoken_count}, {TITLE}. Le plus récent vient de {_sender(first)}, au sujet de : {first.get('subject') or 'sans objet'}."
    others = [_sender(item) for item in items[1:3]]
    if others:
        verb = "Viennent" if len(others) > 1 else "Vient"
        speech += f" {verb} ensuite " + " et ".join(others) + "."
    return Reply(text="\n".join(lines), speech=speech, data={"unread": count})


TRIAGE_PROMPT = (
    "Tu es J.A.R.V.I.S. Tu reçois les mails non lus de {titre} (expéditeur, objet, extrait). En une ou deux phrases "
    "courtes, faites pour être dites à voix haute, en le vouvoyant : signale d'abord ce qui demande son attention "
    "(rendez-vous, échéance, paiement, réponse attendue, message d'un proche), puis regroupe le reste par type "
    "(factures, lettres d'information, notifications, publicités). S'il n'y a rien d'important, dis-le. "
    "N'invente rien, ne cite aucun lien. Commence directement, sans formule d'introduction."
)


def triage_mails(items: list[dict]) -> str | None:
    """Le modèle trie la boîte : « Rien d'urgent, Monsieur : deux factures et une lettre d'information. »"""
    if len(items) < 2 or not MAIL_TRIAGE:
        return None
    online, _reason = llm.ollama_status()
    if not online:
        return None
    listing = "\n".join(
        f"- {_sender(item)} | {item.get('subject') or '(sans objet)'} | "
        f"{(item.get('bodyPreview') or '').replace(chr(10), ' ').strip()[:160]}"
        for item in items[:10]
    )
    try:
        answer = llm.complete(TRIAGE_PROMPT.format(titre=TITLE), listing, 0.2, 140, timeout=40)
    except Exception as exc:
        print(f"[MAIL] Tri impossible: {exc}", flush=True)
        return None
    answer = llm.clean_reply(answer).strip()
    return answer or None


def summarize_inbox(items: list[dict]) -> Reply:
    """Liste des non lus, avec le tri du modèle en tête de la réponse dite."""
    reply = format_mail_resume(items, limit=MAIL_RESUME_LIMIT)
    triage = triage_mails(items)
    if not triage:
        return reply
    count = reply.data.get("unread", len(items))
    spoken = f"{plural(count, 'message non lu', 'messages non lus')}, {TITLE}. {triage}"
    return Reply(text=f"En bref : {triage}\n\n{reply.text}", speech=spoken[:1].upper() + spoken[1:], data=reply.data)


def format_last_mail(item: dict | None) -> Reply:
    """Construit l'affichage détaillé du dernier email reçu."""
    if not item:
        return Reply(text=f"Votre boîte de réception est vide, {TITLE}.")

    sender = _sender(item)
    subject = item.get("subject") or "(sans objet)"
    preview = (item.get("bodyPreview") or "").replace("\n", " ").strip()
    text = (
        f"Votre dernier message, {TITLE} :\n"
        f"De : {sender}\n"
        f"Objet : {subject}\n"
        f"Aperçu : {preview or '(vide)'}"
    )
    speech = f"Votre dernier message vient de {sender}, {TITLE}, au sujet de : {subject}."
    if preview:
        speech += f" Il dit : {preview[:240]}"
    return Reply(text=text, speech=speech)


def fallback_email_subject(draft_context: str, body_hint: str) -> str:
    """Génère un objet d'email de secours à partir du contexte utilisateur."""
    context = " ".join(part for part in [draft_context, body_hint] if part).strip()
    keywords = _extract_subject_keywords(context)

    subject = _format_two_word_subject(keywords)
    return subject or "Message Jarvis"


def fallback_email_body(subject: str, draft_context: str, body_hint: str) -> str:
    """Génère un corps d'email de secours si la génération IA échoue."""
    core = (body_hint or "").strip()
    if not core:
        match = re.search(
            r"(?:dis(?:-|\s)?lui\s+que|dit(?:-|\s)?lui\s+que|en\s+lui\s+disant\s+que|pour\s+lui\s+dire\s+que)\s+(.+)$",
            draft_context,
            flags=re.IGNORECASE,
        )
        if match:
            core = match.group(1).strip(" .;,:!?\"'")

    if not core and subject:
        core = f"Je te contacte au sujet de {subject.lower()}."
    if not core:
        core = "Je te contacte pour te transmettre cette information."

    if not re.search(r"[.!?]$", core):
        core += "."
    core = core[0].upper() + core[1:]

    return f"Bonjour,\n\n{core}\n\nCordialement,"


def generate_email_subject(draft_context: str, body_hint: str) -> str:
    """Demande au modèle de proposer un objet d'email court et professionnel."""
    context = " ".join(part for part in [draft_context, body_hint] if part).strip()
    fallback = fallback_email_subject(draft_context, body_hint)
    prompt = (
        "Propose un objet d'email en francais en 1 ou 2 mots maximum. "
        "Retourne uniquement l'objet, sans phrase complete, sans guillemets, sans ponctuation finale.\n\n"
        f"Contexte: {context}"
    )

    try:
        subject_raw = llm.complete(
            "Tu proposes des objets d'email tres courts: 1 ou 2 mots.",
            prompt,
            temperature=0.1,
            max_tokens=12,
            timeout=30,
        )
        subject_raw = normalize_generated_french(subject_raw)
        subject_raw = (subject_raw.splitlines() or [""])[0].strip(" \"'`-•")

        candidate_words = _extract_subject_keywords(subject_raw)
        candidate = _format_two_word_subject(candidate_words)

        if candidate:
            context_words = set(_extract_subject_keywords(context))
            candidate_words_set = {word.lower() for word in candidate.split()}
            if not context_words or not candidate_words_set.isdisjoint(context_words):
                return candidate
    except Exception:
        pass

    return fallback


def generate_email_body(subject: str, draft_context: str, body_hint: str, polish_only: bool) -> str:
    """Demande au modèle de rédiger ou d'améliorer le corps de l'email."""
    fallback = fallback_email_body(subject, draft_context, body_hint)
    mode_instruction = (
        "Ameliore le brouillon en un email professionnel, chaleureux et naturel. "
        "Ne recopie jamais le brouillon tel quel: reformule-le."
        if polish_only
        else "Redige un email complet et naturel a partir du contexte, meme si les infos sont partielles."
    )

    prompt = (
        "Tu dois retourner uniquement le corps de l'email en texte brut, en francais, sans markdown.\n"
        "L'email est ecrit a la premiere personne, au nom de l'expediteur.\n"
        "Format attendu: salutation + message principal + phrase de cloture courte.\n"
        f"{mode_instruction}\n\n"
        f"Objet: {subject or '(a definir)'}\n"
        f"Contexte utilisateur: {draft_context or '(vide)'}\n"
        f"Brouillon extrait: {body_hint or '(vide)'}"
    )

    try:
        body = llm.complete(
            "Tu es un assistant de redaction d'emails professionnels.",
            prompt,
            temperature=0.25,
            max_tokens=220,
            timeout=45,
        )
        body = re.sub(r"^```(?:text)?\s*|\s*```$", "", body, flags=re.DOTALL).strip()
        body = normalize_generated_french(body)
        if len(body) >= 20:
            if polish_only and _looks_like_unpolished_copy(body, body_hint):
                return fallback
            return body
    except Exception:
        pass

    return fallback


def handle_send_mail(mail_client: Any, params: dict) -> Reply:
    """Exécute le flux d'envoi mail avec génération optionnelle objet/corps.

    Si params["confirm"] est vrai, rien n'est envoyé : Jarvis présente le message
    final et attend un « oui » (la réponse porte alors l'action en attente).
    """
    to_email = params["to_email"]
    recipient = str(params.get("to_name") or to_email)
    subject = (params.get("subject") or "").strip()
    body = (params.get("body") or "").strip()
    auto_subject = bool(params.get("auto_subject"))
    auto_draft = bool(params.get("auto_draft"))
    auto_polish = bool(params.get("auto_polish"))
    draft_context = str(params.get("draft_context") or "").strip()

    if _contains_disallowed_mail_content(draft_context, body):
        return Reply(
            text=(
                f"Je préfère ne pas envoyer ce message, {TITLE} : son contenu est inapproprié. "
                "Reformulez-le en termes respectueux et je m'en charge."
            )
        )

    if not body:
        return Reply(
            text=(
                f"Je peux écrire à {recipient}, {TITLE}, mais il me manque le message à transmettre. "
                "Que dois-je lui dire ?"
            )
        )

    if auto_subject or not subject:
        subject = generate_email_subject(draft_context, body)

    if auto_draft:
        body = generate_email_body(subject, draft_context, body, polish_only=False)
    elif auto_polish:
        body = generate_email_body(subject, draft_context, body, polish_only=True)

    if not body:
        return Reply(
            text=(
                f"Je n'ai pas réussi à rédiger un message valable pour {recipient}, {TITLE}. "
                "Pourriez-vous préciser le contenu ?"
            )
        )

    if _contains_disallowed_mail_content(subject, body):
        return Reply(
            text=(
                f"Je préfère ne pas envoyer ce message, {TITLE} : son contenu final est inapproprié. "
                "Reformulez-le en termes respectueux et je m'en charge."
            )
        )

    if params.get("confirm"):
        text = (
            f"J'ai préparé ce message pour {recipient}, {TITLE} :\n\n"
            f"Objet : {subject}\n\n{body}\n\n"
            "Dois-je l'envoyer ?"
        )
        speech = f"J'ai préparé le message pour {recipient}, {TITLE}. Objet : {subject}. "
        speech += f"{body} " if len(body) <= 320 else "Le texte est à l'écran. "
        speech += "Dois-je l'envoyer ?"
        return Reply(
            text=text,
            speech=speech,
            pending={
                "action": "send_mail",
                "params": {"to_email": to_email, "to_name": params.get("to_name"), "subject": subject, "body": body},
            },
        )

    mail_client.send_mail(to_email, subject, body)
    return Reply(
        text=f"Message envoyé à {recipient}, {TITLE} (objet : {subject}).",
        speech=f"Message envoyé à {recipient}, {TITLE}.",
    )


# ── Chercher, lire, répondre, ranger ───────────────────────────────────────

def mail_query(who: str) -> tuple[str, str]:
    """Traduit « Paul », « la banque », « le dernier » en recherche Gmail, avec un libellé à dire."""
    who = re.sub(r"\s+", " ", (who or "").strip(" .!?\"'«»"))
    if not who or re.fullmatch(r"(?:le |mon )?dernier(?: mail| message)?", who, flags=re.IGNORECASE):
        return "in:inbox", "votre dernier message"
    contacts = {name.lower(): email for name, email in load_contacts().items()}
    if who.lower() in contacts:
        return f"from:{contacts[who.lower()]}", f"le message de {who}"
    if "@" in who:
        return f"from:{who}", f"le message de {who}"
    article = re.match(r"^(?:la|le|les|l'|du|des|de la|de l')\s*", who, flags=re.IGNORECASE)
    if article:
        topic = who[article.end():]
        return topic, f"le message concernant {topic}"
    return f"from:{who}", f"le message de {who}"


def _find_one(mail_client: Any, params: dict) -> tuple[dict | None, str]:
    query, label = mail_query(str(params.get("who") or ""))
    found = mail_client.search_emails(query, limit=1)
    return (found[0] if found else None), label


def handle_search_mail(mail_client: Any, params: dict) -> Reply:
    query, label = mail_query(str(params.get("who") or ""))
    items = mail_client.search_emails(query, limit=5)
    if not items:
        return Reply(text=f"Je ne trouve aucun message pour « {params.get('who')} », {TITLE}.")
    lines = [f"- {_sender(item)} : {item.get('subject') or '(sans objet)'}" for item in items]
    first = items[0]
    return Reply(
        text=f"Ce que j'ai trouvé, {TITLE} :\n" + "\n".join(lines),
        speech=f"J'ai trouvé {plural(len(items), 'message')}, {TITLE}. Le plus récent vient de {_sender(first)} : {first.get('subject') or 'sans objet'}.",
        data={"mails": len(items)},
    )


def handle_read_mail(mail_client: Any, params: dict) -> Reply:
    found, label = _find_one(mail_client, params)
    if found is None:
        return Reply(text=f"Je ne trouve pas {label}, {TITLE}.")
    full = mail_client.get_email(found["id"])
    body = re.sub(r"\n{3,}", "\n\n", (full.get("body") or found.get("bodyPreview") or "").strip())
    sender, subject = _sender(full), full.get("subject") or "(sans objet)"
    spoken_body = re.sub(r"https?://\S+", "", body.replace("\n", " "))[:600]
    return Reply(
        text=f"De : {sender}\nObjet : {subject}\n\n{body[:4000] or '(message vide)'}",
        speech=f"Message de {sender}, {TITLE}, au sujet de : {subject}. {spoken_body}",
        data={"mail_id": found["id"]},
    )


def handle_reply_mail(mail_client: Any, params: dict) -> Reply:
    body = str(params.get("body") or "").strip()
    if not body:
        return Reply(text=f"Que dois-je répondre, {TITLE} ?")
    if _contains_disallowed_mail_content(body):
        return Reply(text=f"Je préfère ne pas envoyer cette réponse, {TITLE} : son contenu est inapproprié.")

    if params.get("mail_id"):  # confirmé : on répond au message présenté
        mail_client.reply_to(mail_client.get_email(params["mail_id"]), body)
        return Reply(text=f"Réponse envoyée, {TITLE}.")

    found, label = _find_one(mail_client, params)
    if found is None:
        return Reply(text=f"Je ne trouve pas {label}, {TITLE}.")
    subject = found.get("subject") or "(sans objet)"
    polished = generate_email_body(f"Re: {subject}", f"Réponse à {_sender(found)} : {body}", body, polish_only=True) or body
    pending = {"action": "reply_mail", "params": {"mail_id": found["id"], "body": polished, "who": params.get("who")}}
    if not params.get("confirm"):
        mail_client.reply_to(mail_client.get_email(found["id"]), polished)
        return Reply(text=f"Réponse envoyée à {_sender(found)}, {TITLE}.")
    return Reply(
        text=f"Ma réponse à {_sender(found)} (« {subject} »), {TITLE} :\n\n{polished}\n\nDois-je l'envoyer ?",
        speech=f"J'ai préparé la réponse à {_sender(found)}, {TITLE}. Dois-je l'envoyer ?",
        pending=pending,
    )


def _tidy(mail_client: Any, params: dict, action: str) -> Reply:
    verb, done = ("archiver", "archivé") if action == "archive_mail" else ("mettre à la corbeille", "mis à la corbeille")
    if params.get("mail_id"):
        (mail_client.archive_email if action == "archive_mail" else mail_client.trash_email)(params["mail_id"])
        return Reply(text=f"C'est fait, {TITLE} : message {done}.")
    found, label = _find_one(mail_client, params)
    if found is None:
        return Reply(text=f"Je ne trouve pas {label}, {TITLE}.")
    summary = f"{_sender(found)} — « {found.get('subject') or '(sans objet)'} »"
    if params.get("confirm"):
        return Reply(
            text=f"Dois-je {verb} ce message, {TITLE} ?\n{summary}",
            speech=f"Dois-je {verb} le message de {_sender(found)}, {TITLE} ?",
            pending={"action": action, "params": {"mail_id": found["id"]}},
        )
    return _tidy(mail_client, {"mail_id": found["id"]}, action)


class MailAgent(Agent):
    """Messagerie Gmail : résumé, recherche, lecture, envoi, réponse, archivage et corbeille."""

    name = "messagerie"
    needs_google = True
    writes = frozenset({"send_mail", "reply_mail", "archive_mail", "trash_mail"})
    confirmable = frozenset({"send_mail", "reply_mail", "archive_mail", "trash_mail"})

    def handlers(self) -> dict[str, Handler]:
        return {
            "mail_resume": lambda params: summarize_inbox(self.context.google.get_unread_emails(limit=MAIL_RESUME_LIMIT)),
            "mail_last": lambda params: format_last_mail(self.context.google.get_latest_email()),
            "send_mail": lambda params: handle_send_mail(self.context.google, params),
            "search_mail": lambda params: handle_search_mail(self.context.google, params),
            "read_mail": lambda params: handle_read_mail(self.context.google, params),
            "reply_mail": lambda params: handle_reply_mail(self.context.google, params),
            "archive_mail": lambda params: _tidy(self.context.google, params, "archive_mail"),
            "trash_mail": lambda params: _tidy(self.context.google, params, "trash_mail"),
        }
