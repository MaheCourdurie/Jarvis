"""Agent documents : lettres, CV, comptes-rendus, rédigés puis livrés en .docx (Word, Pages)."""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import Optional

from agents.atelier import Creation, CreativeAgent, Draft, draft_until_valid
from core.agent import Handler
from persona import Reply, TITLE

PROMPT = """Tu es l'agent de rédaction de J.A.R.V.I.S. : un rédacteur professionnel francophone.
Tu livres un document complet, prêt à imprimer ou à envoyer.

Règles de métier :
- Le genre exact demandé : lettre (formelle, avec lieu et date, objet, formule de politesse),
  CV (sections claires : profil, expériences, formation, compétences), compte-rendu, attestation, etc.
- Un français irréprochable, un ton adapté au destinataire, des phrases nettes.
- Ce que tu ne sais pas (nom, adresse, numéro de contrat…) apparaît entre crochets à compléter :
  [Votre nom], [Adresse du destinataire]. N'invente jamais de données personnelles.
- Mise en forme en HTML simple : <h1>, <h2>, <p>, <ul>, <strong>, <table> si utile. Pas de CSS
  compliqué, pas d'image.

Format de réponse, strictement :
TITRE: <nom court du document, 2 à 6 mots>
RÉSUMÉ: <une phrase en français qui décrit le document>
```html
<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>…</title></head><body>…</body></html>
```"""

REVISE_PROMPT = """Voici le document actuel « {title} » :
```html
{content}```

Modification demandée : {request}

Applique-la et renvoie le document COMPLET, dans le même format (TITRE identique)."""


def check_document(draft: Draft) -> Optional[str]:
    page = draft.content.lower()
    if "<body" not in page or "</html>" not in page:
        return "le document n'est pas un HTML complet (<body> … </html>)"
    if len(re.sub(r"<[^>]+>", " ", draft.content).split()) < 60:
        return "le document est trop court : rédige-le en entier"
    return None


class DocumentAgent(CreativeAgent):
    """Rédige le document, l'enregistre en .docx (et en HTML) et l'ouvre dans le traitement de texte."""

    name = "documents"

    def handlers(self) -> dict[str, Handler]:
        return {"write_document": self.write_document}

    def write_document(self, params: dict) -> Reply:
        request = str(params.get("request") or "").strip()
        if len(request) < 8:
            return Reply(text=f"Quel document, {TITLE} ? Par exemple : une lettre de résiliation de mon abonnement de salle de sport.")
        return self.start_job("la rédaction du document", lambda: self._make(f"Document demandé : {request}", request), params, "une à deux minutes")

    def _make(self, prompt: str, request: str, title: str = "") -> Creation:
        draft = draft_until_valid(PROMPT, prompt, check_document, "html", temperature=0.4)
        title = title or draft.title or request
        source = self.workshop.save("documents", title, "html", draft.content)
        path = source
        if shutil.which("textutil"):
            docx = source.with_suffix(".docx")
            subprocess.run(["textutil", "-convert", "docx", "-output", str(docx), str(source)], capture_output=True, timeout=60)
            if docx.exists():
                path = docx
        summary = draft.summary or "Votre document."
        if re.search(r"\[[^\]]{2,40}\]", draft.content):
            summary += " Les éléments entre crochets sont à compléter."
        return Creation("document", title, summary, path, draft.content, request, self.name, "html", {"html": source})

    def revise(self, creation: Creation, request: str) -> Creation:
        prompt = REVISE_PROMPT.format(title=creation.title, content=creation.content, request=request)
        return self._make(prompt, f"{creation.request} — {request}", creation.title)
