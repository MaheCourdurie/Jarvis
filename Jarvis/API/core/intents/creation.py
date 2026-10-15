"""Contrôleur création : code, pages, logos, palettes, documents, retouches."""

from __future__ import annotations

import re

from persona import fold


# ── Création : code et design ──────────────────────────────────────────────

_CREATE_VERB = (
    r"(?:cree|creer|crees|fais|fait|faire|fabrique|fabriquer|ecris|ecrire|code|coder|codes|genere|generer"
    r"|developpe|developper|dessine|dessiner|concois|concevoir|imagine|imaginer|propose|proposer|realise|realiser"
    r"|prepare|preparer|construis|construire|compose|composer|monte|monter|programme|programmer|redige|rediger)"
)
_CODE_NOUN = r"(?:script|programme|code|fonction|bot|algorithme|appli|application|app|jeu|outil|extension|calculatrice)"
_PAGE_NOUN = r"(?:site(?: web| internet| vitrine)?|page(?: web| d'accueil| html| internet)?|landing(?: page)?|maquette|portfolio|template|mockup)"
_LOGO_NOUN = r"(?:logo|logotype|icone|embleme)"
_PALETTE_NOUN = r"(?:palette|nuancier|gamme de couleurs|couleurs (?:pour|qui))"
_DOCUMENT_NOUN = (
    r"(?:lettre|cv|curriculum(?: vitae)?|compte[- ]rendu|attestation|courrier|discours|dissertation|expose|rapport"
    r"|devis|facture|contrat|proces[- ]verbal|note de synthese)"
)
_CODE_LANGUAGE = re.compile(
    r"\ben (python|javascript|js|typescript|bash|shell|zsh|swift|rust|go|golang|java|kotlin|php|ruby|sql|lua|applescript|c\+\+|c#|c)\b"
    r"|\b(python|javascript|typescript|bash|swift|rust|kotlin|php|ruby|applescript)\b"
)
# « programme » au sens d'emploi du temps ou d'entraînement : ce n'est pas du code.
_NOT_CODE = re.compile(r"\bprogramme (?:d'entrainement|de (?:revision|musculation|la journee|la semaine|course)|du jour|sportif|tele|tv)\b")
_CREATION_TARGET = r"(?:script|programme|code|page|site|logo|palette|maquette|creation|design|jeu|appli|application)"
_REVISE_VERB = (
    r"(?:modifie|modifier|change|changer|ameliore|ameliorer|corrige|corriger|ajoute|ajouter|rajoute|retire|enleve"
    r"|supprime|mets|met|rends|agrandis|reduis|remplace|refais|refaire|retouche|peaufine|traduis|simplifie|optimise)"
)


def _creation_request(verb: str, noun: str, folded: str) -> bool:
    return re.search(rf"\b{verb}\b(?:[- ]moi| moi)?(?:\s+\S+){{0,5}}?\s+{noun}s?\b", folded) is not None


def parse_creation(text: str) -> dict | None:
    """Commandes à l'atelier : programmes, pages, logos, palettes, et retouches de la dernière création."""
    folded = fold(text).strip(" .!?")
    request = text.strip().strip(".!?").strip()

    # Rouvrir, lister, suivre les créations.
    if re.search(rf"\b(?:ouvre|montre|affiche|rouvre)(?:[- ]moi)? (?:ma|la|mon|le) dernier(?:e)? {_CREATION_TARGET}\b", folded):
        return {"action": "open_creation"}
    if re.search(r"\b(?:mes|les) creations\b|\bmon atelier\b|\bou en est (?:la creation|le script|la page|le logo|la palette|le programme)\b", folded):
        return {"action": "list_creations"}

    # Retouches : « ajoute un bouton de contact à la page », « corrige-le », « change les couleurs du logo ».
    target = rf"(?:le|la|ce|cette|mon|ma|du|de la|au|a la|sur la|sur le|dans le|dans la|a ce|a cette)\s+{_CREATION_TARGET}\b"
    if re.search(rf"\b{_REVISE_VERB}\b.*\b{target}", folded) or re.match(
        r"^(?:modifie|ameliore|corrige|refais|retouche|peaufine|simplifie|optimise)[- ](?:le|la)\b", folded
    ):
        if not re.search(rf"\b{_CREATE_VERB}(?:[- ]moi)? (?:un|une|des)\b", folded):
            return {"action": "revise_creation", "params": {"request": request}}

    if re.search(r"\b(?:reviens|retourne|remets|revenir|reprends)\b.*\bversion (?:precedente|d'avant|anterieure)\b|\bannule (?:la |les )?(?:derniere )?(?:modification|retouche)s?\b", folded):
        return {"action": "previous_version"}

    if _creation_request(_CREATE_VERB, _DOCUMENT_NOUN, folded):
        return {"action": "write_document", "params": {"request": request}}

    if _creation_request(_CREATE_VERB, _LOGO_NOUN, folded):
        return {"action": "design_logo", "params": {"request": request}}
    if _creation_request(_CREATE_VERB, _PALETTE_NOUN, folded):
        return {"action": "design_palette", "params": {"request": request}}

    language = _CODE_LANGUAGE.search(folded)
    wants_code = _creation_request(_CREATE_VERB, _CODE_NOUN, folded) and not _NOT_CODE.search(folded)
    if _creation_request(_CREATE_VERB, _PAGE_NOUN, folded) and not wants_code:
        return {"action": "design_page", "params": {"request": request}}
    if wants_code or (language and re.search(rf"\b{_CREATE_VERB}\b", folded)):
        params = {"request": request}
        if language:
            params["language"] = language.group(1) or language.group(2)
        return {"action": "write_code", "params": params}
    return None
