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


# Un nom de fichier de code (« convertisseur.py », « ~/Developer/app/main.js »).
_FILE_NAME = r"(?P<q>(?:~?/)?[\w./-]*\w\.(?:py|js|ts|sh|html|css|swift|java|kt|c|cpp|rs|go|php|rb|lua|sql|json|applescript))"
_CODE_THING = r"(?:fichier|script|programme|code)"


def parse_code_tools(text: str) -> dict | None:
    """« Écris les tests du script », « corrige le fichier main.py », « explique-moi ce programme »."""
    clean = text.strip().rstrip(" .!?").replace("’", "'")
    folded = fold(clean)
    if re.search(
        r"\b(?:ecris|ecrire|genere|generer|fais|faire|ajoute|ajouter|cree|creer|redige)(?:[- ]moi| moi)?\s+(?:les |des |un |une )?"
        r"(?:tests? (?:unitaires|automatiques)|(?:tests?|jeu de tests)\s+(?:du|de ce|pour (?:le|ce|mon)|de mon|au|a ce|a mon)\s+(?:script|programme|code))\b",
        folded,
    ) or re.search(r"\bteste (?:le|ce|mon) (?:script|programme|code)\b", folded):
        return {"action": "code_tests"}

    named = re.search(_FILE_NAME, clean)
    fix = re.match(rf"^(?:corrige|debugge|debug|debogue|repare|reparer|corriger)(?:[- ]moi)?\b", folded)
    if fix and named and re.search(rf"\b{_CODE_THING}\b|\.\w+\b", folded):
        return {"action": "fix_code", "params": {"query": named["q"], "request": clean}}
    if fix and re.search(r"\b(?:les )?bugs? (?:de|du|dans) (?:mon|le|ce) (?:script|programme|code)\b", folded):
        return {"action": "fix_code", "params": {"query": "", "request": clean}}

    explain = re.match(
        rf"^(?:explique|expliques|decris|analyse)(?:[- ]moi| moi)?\s+(?:le |ce |mon |la |cette )?{_CODE_THING}?\s*",
        folded,
    ) or re.match(r"^(?:qu'est-ce que|que) fait (?:le|ce|mon) (?:fichier|script|programme|code)\b", folded)
    if explain and named:
        return {"action": "explain_code", "params": {"query": named["q"]}}
    if explain and re.search(rf"\b(?:ce|mon|le) (?:script|programme|code)\b|\b(?:ce|le dernier) {_CODE_THING}\b", folded) and not re.search(r"\bfichier\b", folded):
        return {"action": "explain_code", "params": {"query": ""}}
    return None


def parse_creation(text: str) -> dict | None:
    """Commandes à l'atelier : programmes, pages, logos, palettes, et retouches de la dernière création."""
    folded = fold(text).strip(" .!?")
    request = text.strip().strip(".!?").strip()

    # Rouvrir, lister, suivre les créations.
    if re.search(rf"\b(?:ouvre|montre|affiche|rouvre)(?:[- ]moi)? (?:ma|la|mon|le) dernier(?:e)? {_CREATION_TARGET}\b", folded):
        return {"action": "open_creation"}
    if re.search(r"\b(?:mes|les) creations\b|\bmon atelier\b|\bou en est (?:la creation|le script|la page|le logo|la palette|le programme)\b", folded):
        return {"action": "list_creations"}

    # Code existant : tests du dernier programme, corriger ou expliquer un fichier.
    code_action = parse_code_tools(text)
    if code_action is not None:
        return code_action

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
