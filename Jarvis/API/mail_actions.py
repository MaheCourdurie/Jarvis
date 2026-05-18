from __future__ import annotations

import re
import unicodedata
from typing import Any

import requests


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


def extract_first_email(value: str) -> str | None:
    """Extrait la première adresse email trouvée dans une chaîne."""
    match = EMAIL_PATTERN.search(value or "")
    if not match:
        return None
    return match.group(0)


def extract_recent_email_from_history(history: list[Any], max_messages: int = 8) -> str | None:
    """Récupère la dernière adresse email visible dans l'historique récent."""
    for item in reversed(history[-max_messages:]):
        content = getattr(item, "content", None)
        if content is None and isinstance(item, dict):
            content = item.get("content", "")
        email = extract_first_email(str(content or ""))
        if email:
            return email
    return None


def normalize_generated_french(text: str) -> str:
    """Corrige quelques fautes récurrentes produites par le modèle."""
    normalized = text or ""
    fixes = [
        (r"\\bluiphones\\b", "lui téléphones"),
        (r"\\bluiphone\\b", "lui téléphones"),
        (r"\\bluiphoner\\b", "lui téléphoner"),
    ]
    for pattern, replacement in fixes:
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
    return normalized


def format_mail_resume(items: list[dict]) -> str:
    """Construit un résumé texte des emails non lus."""
    if not items:
        return "Aucun email non lu dans la boîte de réception."

    lines = ["Résumé de tes emails non lus :"]
    for idx, item in enumerate(items, start=1):
        sender = item.get("from", {}).get("emailAddress", {}).get("name") or "Expéditeur inconnu"
        subject = item.get("subject") or "(sans objet)"
        preview = (item.get("bodyPreview") or "").replace("\n", " ").strip()
        if len(preview) > 90:
            preview = preview[:90] + "..."
        lines.append(f"{idx}. {sender} — {subject}")
        if preview:
            lines.append(f"   {preview}")
    lines.append("\nAction suivante: /maillast pour lire le dernier email.")
    return "\n".join(lines)


def format_last_mail(item: dict | None) -> str:
    """Construit l'affichage détaillé du dernier email reçu."""
    if not item:
        return " Aucun email trouvé dans la boîte de réception."

    sender = item.get("from", {}).get("emailAddress", {}).get("name") or "Expéditeur inconnu"
    subject = item.get("subject") or "(sans objet)"
    preview = (item.get("bodyPreview") or "").replace("\n", " ").strip()
    return (
        " Dernier email récupéré :\n"
        f"De: {sender}\n"
        f"Objet: {subject}\n"
        f"Aperçu: {preview or '(vide)'}"
    )


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
            r"(?:dis(?:-|\\s)?lui\\s+que|dit(?:-|\\s)?lui\\s+que|en\\s+lui\\s+disant\\s+que|pour\\s+lui\\s+dire\\s+que)\\s+(.+)$",
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

    return f"Bonjour,\n\n{core}\n\nCordialement,"


def generate_email_subject(draft_context: str, body_hint: str, ollama_url: str, ollama_model: str) -> str:
    """Demande à Ollama de proposer un objet d'email court et professionnel."""
    context = " ".join(part for part in [draft_context, body_hint] if part).strip()
    fallback = fallback_email_subject(draft_context, body_hint)
    prompt = (
        "Propose un objet d'email en francais en 1 ou 2 mots maximum. "
        "Retourne uniquement l'objet, sans phrase complete, sans guillemets, sans ponctuation finale.\n\n"
        f"Contexte: {context}"
    )
    payload = {
        "model": ollama_model,
        "messages": [
            {
                "role": "system",
                "content": "Tu proposes des objets d'email tres courts: 1 ou 2 mots.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "options": {"temperature": 0.1, "num_predict": 12},
        "stream": False,
    }

    try:
        res = requests.post(f"{ollama_url}/api/chat", json=payload, timeout=30)
        res.raise_for_status()
        data = res.json()
        subject_raw = (data.get("message", {}).get("content") or "").strip()
        subject_raw = normalize_generated_french(subject_raw)
        subject_raw = subject_raw.splitlines()[0].strip(" \"'`-•")

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


def generate_email_body(
    subject: str,
    draft_context: str,
    body_hint: str,
    polish_only: bool,
    ollama_url: str,
    ollama_model: str,
) -> str:
    """Demande à Ollama de rédiger ou d'améliorer le corps de l'email."""
    fallback = fallback_email_body(subject, draft_context, body_hint)
    mode_instruction = (
        "Ameliore le brouillon en un email professionnel, chaleureux et naturel. "
        "Ne recopie jamais le brouillon tel quel: reformule-le."
        if polish_only
        else "Redige un email complet et naturel a partir du contexte, meme si les infos sont partielles."
    )

    prompt = (
        "Tu dois retourner uniquement le corps de l'email en texte brut, en francais, sans markdown.\n"
        "Format attendu: salutation + message principal + phrase de cloture courte.\n"
        f"{mode_instruction}\n\n"
        f"Objet: {subject or '(a definir)'}\n"
        f"Contexte utilisateur: {draft_context or '(vide)'}\n"
        f"Brouillon extrait: {body_hint or '(vide)'}"
    )

    payload = {
        "model": ollama_model,
        "messages": [
            {
                "role": "system",
                "content": "Tu es un assistant de redaction d'emails professionnels.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "options": {"temperature": 0.25, "num_predict": 220},
        "stream": False,
    }

    try:
        res = requests.post(f"{ollama_url}/api/chat", json=payload, timeout=45)
        res.raise_for_status()
        data = res.json()
        body = (data.get("message", {}).get("content") or "").strip()
        body = re.sub(r"^```(?:text)?\\s*|\\s*```$", "", body, flags=re.DOTALL).strip()
        body = normalize_generated_french(body)
        if len(body) >= 20:
            if polish_only and _looks_like_unpolished_copy(body, body_hint):
                return fallback
            return body
    except Exception:
        pass

    return fallback


def handle_send_mail(mail_client: Any, params: dict, ollama_url: str, ollama_model: str) -> str:
    """Exécute le flux d'envoi mail avec génération optionnelle objet/corps."""
    to_email = params["to_email"]
    subject = (params.get("subject") or "").strip()
    body = (params.get("body") or "").strip()
    auto_subject = bool(params.get("auto_subject"))
    auto_draft = bool(params.get("auto_draft"))
    auto_polish = bool(params.get("auto_polish"))
    draft_context = str(params.get("draft_context") or "").strip()

    if _contains_disallowed_mail_content(draft_context, body):
        return (
            "Je ne peux pas envoyer ce mail car le contenu demandé est inapproprié. "
            "Reformule avec un message respectueux."
        )

    if not body:
        return (
            f"Je peux envoyer un email à {to_email}, mais il me manque le message à transmettre. "
            "Précise le contenu avant envoi."
        )

    if auto_subject or not subject:
        subject = generate_email_subject(draft_context, body, ollama_url=ollama_url, ollama_model=ollama_model)

    if auto_draft:
        body = generate_email_body(
            subject,
            draft_context,
            body,
            polish_only=False,
            ollama_url=ollama_url,
            ollama_model=ollama_model,
        )
    elif auto_polish:
        body = generate_email_body(
            subject,
            draft_context,
            body,
            polish_only=True,
            ollama_url=ollama_url,
            ollama_model=ollama_model,
        )

    if not body:
        return (
            f"Je peux envoyer un email à {to_email}, mais je n'ai pas réussi à générer un message valide. "
            "Réessaie avec un contenu plus précis."
        )

    if _contains_disallowed_mail_content(subject, body):
        return (
            "Je ne peux pas envoyer ce mail car le contenu final est inapproprié. "
            "Reformule avec un message respectueux."
        )

    mail_client.send_mail(to_email, subject, body)
    if auto_subject or auto_draft or auto_polish:
        return f"Email rédigé et envoyé à {to_email} (objet: {subject})."
    return f"Email envoyé à {to_email} (objet: {subject})."
