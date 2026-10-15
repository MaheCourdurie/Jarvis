"""Agent design : pages web, logos et palettes de couleurs, avec un œil de directeur artistique."""

from __future__ import annotations

import base64
import html
import json
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Optional

from agents.atelier import CREATION_CTX, Creation, CreationError, CreativeAgent, Draft, draft_until_valid, generate
from config import DESIGN_SELF_REVIEW
from core.agent import Handler
from persona import Reply, TITLE
from services import llm

PAGE_PROMPT = """Tu es l'agent design de J.A.R.V.I.S. : directeur artistique et intégrateur web exigeant.
Tu livres une page web complète, belle et prête à ouvrir dans un navigateur.

Règles de métier :
- Un seul fichier HTML5 : <!doctype html>, <meta charset="utf-8">, <meta name="viewport">, <title>,
  le CSS dans <style>, le JavaScript éventuel dans <script>.
- Une direction artistique affirmée et adaptée au sujet : 3 à 5 couleurs déclarées en variables CSS
  dans :root, une ou deux polices (Google Fonts permis via <link>), une hiérarchie typographique nette,
  des espacements généreux.
- Mise en page responsive (grid ou flex, une media query pour le téléphone) et contrastes lisibles.
- Un contenu réaliste en français, propre au sujet : vrais titres, textes, boutons et sections.
  Jamais de lorem ipsum.
- Aucune image externe : illustrations en SVG dans la page, dégradés CSS ou emoji.
- N'invente jamais de coordonnées qui ont l'air vraies (adresse, code postal, téléphone, email) :
  écris des exemples évidents (« 1 rue de l'Exemple », « 05 00 00 00 00 », « contact@exemple.fr »).
- Finitions : états :hover et :focus, transitions douces, pied de page.
- Concis : moins de 250 lignes. CSS compact, une règle par ligne (`.carte{padding:24px;border-radius:16px}`),
  sans commentaires.

Format de réponse, strictement :
TITRE: <nom court de la page, 2 à 5 mots>
RÉSUMÉ: <une phrase en français qui décrit la page et son style>
```html
<la page complète>
```"""

LOGO_PROMPT = """Tu es l'agent design de J.A.R.V.I.S. : designer d'identité visuelle.
Tu dessines un logo vectoriel en SVG, simple, mémorable et lisible en petit.

Règles de métier :
- Un seul élément <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">.
- Formes géométriques nettes (cercles, rectangles, chemins simples), 2 ou 3 couleurs au plus.
- Le symbole est grand : il occupe au moins les deux tiers du cadre.
- Un symbole qui évoque le sujet ; le nom en texte seulement s'il est court, avec une police
  générique (font-family="Helvetica, Arial, sans-serif"), centré, d'au moins 48 de hauteur
  (font-size="48" ou plus).
- Le logo doit rester lisible sur fond clair comme sur fond sombre : aucun élément noir, gris
  foncé ou blanc seul ; le texte prend une couleur franche du logo (fill="#…").
- Pas d'image, pas de lien externe, pas de filtre complexe. Fond transparent.

Format de réponse, strictement :
TITRE: <nom du logo, 1 à 4 mots>
RÉSUMÉ: <une phrase en français qui décrit le symbole et les couleurs>
```svg
<le svg complet>
```"""

PALETTE_PROMPT = """Tu es l'agent design de J.A.R.V.I.S. : coloriste et directeur artistique.
Compose une palette de 5 couleurs harmonieuse et utilisable pour une interface.

Règles de métier :
- Des rôles clairs : un fond, un texte (contraste fort avec le fond), une couleur principale,
  une couleur d'accent, et une couleur secondaire ou neutre.
- Des couleurs justes pour le sujet et l'ambiance demandés, pas des couleurs primaires brutes.
- Codes hexadécimaux à 6 chiffres.

Réponds uniquement par un objet JSON de cette forme :
{"nom": "nom évocateur de la palette", "ambiance": "une phrase en français",
 "couleurs": [{"nom": "nom de la couleur", "hex": "#RRGGBB", "role": "fond"}, ...],
 "conseil": "une phrase sur la façon de l'utiliser"}"""

REVISE_PROMPT = """Voici la création actuelle « {title} » :
```{language}
{content}```

Modification demandée : {request}

Applique la modification en gardant la qualité et le style du reste, et renvoie le fichier COMPLET,
dans le même format (TITRE identique, RÉSUMÉ décrivant ce qui a changé)."""

REVIEW_PROMPT = """Tu es le relecteur visuel de l'agent design de J.A.R.V.I.S. Regarde ce rendu ({kind}).
La demande était : « {request} ».
Ne signale que les défauts GRAVES et visibles : texte illisible, coupé ou tronqué, éléments qui se
chevauchent, mise en page cassée, contraste insuffisant, symbole trop petit dans son cadre, élément
demandé absent. Ignore les questions de goût.
Réponds uniquement en JSON : {{"ok": true}} si c'est correct, sinon
{{"ok": false, "defauts": ["défaut précis en français", "..."]}} (3 au plus)."""

FIX_PROMPT = """Voici la création « {title} » :
```{language}
{content}```

En regardant son rendu, le relecteur a constaté ces défauts : {defects}.
Corrige-les sans changer le reste, et renvoie le fichier COMPLET dans le même format (TITRE identique)."""

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def snapshot(path: Path, size: int = 1000) -> Optional[str]:
    """Photographie le rendu d'une page ou d'un SVG avec Quick Look ; renvoie l'image en base64."""
    if not shutil.which("qlmanage"):
        return None
    with tempfile.TemporaryDirectory(prefix="jarvis-apercu-") as folder:
        try:
            subprocess.run(["qlmanage", "-t", "-s", str(size), "-o", folder, str(path)],
                           capture_output=True, timeout=30, check=False)
        except Exception:
            return None
        images = list(Path(folder).glob("*.png"))
        return base64.b64encode(images[0].read_bytes()).decode() if images else None


def visual_review(kind: str, path: Path, request: str) -> list[str]:
    """Le modèle regarde le rendu et liste les défauts graves (liste vide si tout va bien)."""
    if not DESIGN_SELF_REVIEW:
        return []
    image = snapshot(path)
    if image is None:
        return []
    try:
        answer = llm.complete(
            REVIEW_PROMPT.format(kind=kind, request=request), "Voici le rendu.", 0.1, 250,
            timeout=180, json_mode=True, num_ctx=CREATION_CTX, images=[image],
        )
        verdict = json.loads(answer)
    except Exception as exc:
        print(f"[ATELIER] Relecture visuelle impossible: {exc}", flush=True)
        return []
    if verdict.get("ok", True):
        return []
    return [str(defect) for defect in verdict.get("defauts") or [] if str(defect).strip()][:3]


def export_png(svg_path: Path, size: int = 1024) -> Optional[Path]:
    """Version PNG du logo (pour un profil, un document…)."""
    if not shutil.which("qlmanage"):
        return None
    with tempfile.TemporaryDirectory(prefix="jarvis-png-") as folder:
        subprocess.run(["qlmanage", "-t", "-s", str(size), "-o", folder, str(svg_path)], capture_output=True, timeout=30)
        rendered = list(Path(folder).glob("*.png"))
        if not rendered:
            return None
        target = svg_path.with_suffix(".png")
        shutil.move(str(rendered[0]), target)
        return target
_PLACEHOLDER = re.compile(r"lorem ipsum|\bTODO\b|<!--\s*\.\.\.\s*-->", re.IGNORECASE)


def check_page(draft: Draft) -> Optional[str]:
    page = draft.content.lower()
    if "<html" not in page or "</html>" not in page:
        return "la page n'est pas un document HTML complet (<html> … </html>)"
    if "<style" not in page:
        return "la page n'a pas de CSS dans une balise <style>"
    if 'name="viewport"' not in page:
        return "il manque <meta name=\"viewport\"> : la page doit s'adapter au téléphone"
    if _PLACEHOLDER.search(page):
        return "la page contient du texte de remplissage (lorem ipsum, TODO) : écris le vrai contenu"
    if re.search(r"<img[^>]+src=[\"']https?://", page):
        return "les images externes sont interdites : dessine en SVG ou en CSS"
    return None


def check_logo(draft: Draft) -> Optional[str]:
    try:
        root = ElementTree.fromstring(draft.content.strip())
    except ElementTree.ParseError as exc:
        return f"le SVG est mal formé : {exc}"
    if not root.tag.endswith("svg"):
        return "l'élément racine doit être <svg>"
    if "viewBox" not in root.attrib:
        return "il manque l'attribut viewBox"
    shapes = [el for el in root.iter() if el.tag.split("}")[-1] in {"path", "circle", "rect", "ellipse", "polygon", "line", "polyline", "text"}]
    if not shapes:
        return "le SVG ne contient aucune forme"
    if any(el.tag.split("}")[-1] == "image" for el in root.iter()):
        return "pas d'image dans le logo : uniquement des formes vectorielles"
    for text in (el for el in root.iter() if el.tag.split("}")[-1] == "text"):
        size = re.match(r"\s*([\d.]+)", str(text.get("font-size") or _style(text, "font-size") or "16"))
        if size and float(size.group(1)) < 40:
            return "le texte du logo est trop petit : font-size de 48 au moins"
        fill = str(text.get("fill") or _style(text, "fill") or "#000000")
        if _HEX.match(fill) and not 0.04 <= _luminance(fill) <= 0.8:
            return "le texte du logo disparaît sur fond sombre ou clair : donne-lui une couleur franche du logo"
        if fill.lower() in {"black", "white", "#000", "#fff"}:
            return "le texte du logo disparaît sur fond sombre ou clair : donne-lui une couleur franche du logo"
    return None


def _style(element, prop: str) -> str:
    """Valeur d'une propriété écrite dans l'attribut style (« fill:#123456; font-size:60px »)."""
    match = re.search(rf"(?:^|;)\s*{prop}\s*:\s*([^;]+)", element.get("style") or "")
    return match.group(1).strip() if match else ""


def _luminance(hex_color: str) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(first: str, second: str) -> float:
    """Contraste WCAG entre deux couleurs (4,5 minimum pour un texte courant)."""
    light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return round((light + 0.05) / (dark + 0.05), 1)


def parse_palette(answer: str) -> dict:
    try:
        data = json.loads(answer)
    except ValueError as exc:
        raise CreationError(f"la palette n'est pas un JSON valide : {exc}") from exc
    colors = [c for c in data.get("couleurs") or [] if isinstance(c, dict) and _HEX.match(str(c.get("hex", "")))]
    if not 4 <= len(colors) <= 7:
        raise CreationError("la palette doit compter 5 couleurs avec des codes #RRGGBB")
    for color in colors:
        color["hex"] = color["hex"].upper()
        color["nom"] = str(color.get("nom") or color["hex"])
        color["role"] = str(color.get("role") or "")
    data["couleurs"] = colors
    data["nom"] = str(data.get("nom") or "Palette")
    return data


def render_palette(data: dict) -> str:
    """Page de présentation : nuancier, codes, rôles, et contrastes texte/fond vérifiés."""
    colors = data["couleurs"]
    by_role = {c["role"].lower(): c["hex"] for c in colors}
    background = by_role.get("fond") or max(colors, key=lambda c: _luminance(c["hex"]))["hex"]
    text = by_role.get("texte") or min(colors, key=lambda c: _luminance(c["hex"]))["hex"]
    swatches = "\n".join(
        f"""<figure><div class="swatch" style="background:{c['hex']}"></div>
<figcaption><strong>{html.escape(c['nom'])}</strong><code>{c['hex']}</code><span>{html.escape(c['role'])}</span></figcaption></figure>"""
        for c in colors
    )
    pairs = []
    for c in colors:
        if c["hex"] == background:
            continue
        ratio = contrast_ratio(c["hex"], background)
        verdict = "texte courant" if ratio >= 4.5 else "gros titres" if ratio >= 3 else "décor seulement"
        pairs.append(
            f"<li><span class=\"chip\" style=\"background:{background};color:{c['hex']}\">Aa</span>"
            f"{html.escape(c['nom'])} sur le fond : <strong>{ratio:.1f}:1</strong> — {verdict}</li>"
        )
    name = html.escape(data["nom"])
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name}</title>
<style>
  body {{ margin: 0; font: 16px/1.5 -apple-system, "Helvetica Neue", Arial, sans-serif; background: {background}; color: {text}; }}
  main {{ max-width: 960px; margin: 0 auto; padding: 48px 16px; }}
  h1 {{ font-size: 2.4rem; margin: 0 0 8px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; margin: 32px 0; }}
  figure {{ margin: 0; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 24px rgba(0,0,0,.12); background: #fff; color: #111; }}
  .swatch {{ height: 140px; }}
  figcaption {{ display: grid; gap: 2px; padding: 12px; }}
  code {{ font-size: .9rem; }}
  figcaption span {{ color: #666; font-size: .85rem; }}
  ul {{ list-style: none; padding: 0; display: grid; gap: 8px; }}
  .chip {{ display: inline-block; width: 44px; text-align: center; font-weight: 700; border-radius: 8px; margin-right: 10px; border: 1px solid rgba(0,0,0,.1); }}
</style>
</head>
<body>
<main>
<h1>{name}</h1>
<p>{html.escape(str(data.get("ambiance") or ""))}</p>
<div class="grid">
{swatches}
</div>
<h2>Contrastes</h2>
<ul>
{chr(10).join(pairs)}
</ul>
<p><em>{html.escape(str(data.get("conseil") or ""))}</em></p>
</main>
</body>
</html>
"""


def render_logo_preview(title: str, svg: str) -> str:
    """Le logo sur fond clair, sur fond sombre, et en petit (comme une icône)."""
    name = html.escape(title)
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name}</title>
<style>
  body {{ margin: 0; font: 15px/1.5 -apple-system, "Helvetica Neue", Arial, sans-serif; background: #f4f4f6; color: #222; }}
  main {{ max-width: 960px; margin: 0 auto; padding: 40px 16px; }}
  .row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }}
  .tile {{ border-radius: 16px; padding: 32px; display: grid; place-items: center; min-height: 280px; }}
  .tile svg {{ width: 220px; height: 220px; }}
  .light {{ background: #fff; }} .dark {{ background: #111318; }}
  .small {{ display: flex; gap: 24px; align-items: center; margin-top: 24px; }}
  .small svg {{ width: 32px; height: 32px; }} .small .s64 svg {{ width: 64px; height: 64px; }}
</style>
</head>
<body>
<main>
<h1>{name}</h1>
<div class="row"><div class="tile light">{svg}</div><div class="tile dark">{svg}</div></div>
<div class="small"><div>{svg}</div><div class="s64">{svg}</div><span>en petit, comme une icône</span></div>
</main>
</body>
</html>
"""


class DesignAgent(CreativeAgent):
    """Conçoit pages, logos et palettes ; les vérifie, les enregistre et les ouvre dans le navigateur."""

    name = "design"

    def handlers(self) -> dict[str, Handler]:
        return {
            "design_page": self.design_page,
            "design_logo": self.design_logo,
            "design_palette": self.design_palette,
        }

    @staticmethod
    def _request(params: dict) -> str:
        return str(params.get("request") or "").strip()

    def design_page(self, params: dict) -> Reply:
        request = self._request(params)
        if len(request) < 4:
            return Reply(text=f"Pour quel sujet, {TITLE} ? Par exemple : une page d'accueil pour une boulangerie à Colomiers.")
        return self.start_job("la conception de la page", lambda: self._page(request), params, "trois minutes environ")

    def design_logo(self, params: dict) -> Reply:
        request = self._request(params)
        if len(request) < 3:
            return Reply(text=f"Un logo pour qui, {TITLE} ? Par exemple : un logo pour mon club de tennis.")
        return self.start_job("le dessin du logo", lambda: self._logo(request), params, "une minute environ")

    def design_palette(self, params: dict) -> Reply:
        request = self._request(params) or "une interface moderne et élégante"
        return self.start_job("la composition de la palette", lambda: self._palette(request), params, "une trentaine de secondes")

    # ── Fabrication ───────────────────────────────────────────────────────

    def _fix(self, system: str, check, language: str, title: str, content: str, defects: list[str]) -> Optional[Draft]:
        """Seconde passe après la relecture visuelle ; garde la première version si elle échoue."""
        print(f"[ATELIER] Relecture visuelle : {' ; '.join(defects)}", flush=True)
        prompt = FIX_PROMPT.format(title=title, language=language, content=content, defects=" ; ".join(defects))
        try:
            return draft_until_valid(system, prompt, check, language, temperature=0.3)
        except CreationError:
            return None

    def _page(self, request: str, prompt: Optional[str] = None, title: str = "") -> Creation:
        draft = draft_until_valid(PAGE_PROMPT, prompt or f"Sujet de la page : {request}", check_page, "html", temperature=0.5)
        title = title or draft.title or request
        path = self.workshop.save("design", title, "html", draft.content)
        summary = draft.summary
        defects = visual_review("une page web", path, request)
        if defects and (fixed := self._fix(PAGE_PROMPT, check_page, "html", title, draft.content, defects)):
            draft = fixed
            path.write_text(draft.content, encoding="utf-8")
            summary += " Relue et corrigée après un premier rendu."
        return Creation("page", title, summary, path, draft.content, request, self.name, "html")

    def _logo(self, request: str, prompt: Optional[str] = None, title: str = "") -> Creation:
        draft = draft_until_valid(LOGO_PROMPT, prompt or f"Logo pour : {request}", check_logo, "svg", temperature=0.6)
        title = title or draft.title or request
        path = self.workshop.save("design", f"logo {title}", "svg", "")
        preview = path.with_suffix(".html")
        summary = draft.summary

        def publish(svg: str) -> str:
            svg = svg.strip() + "\n"
            path.write_text(svg, encoding="utf-8")
            preview.write_text(render_logo_preview(title, svg), encoding="utf-8")
            return svg

        svg = publish(draft.content)
        # Le relecteur regarde l'aperçu : fond clair, fond sombre et petite taille.
        defects = visual_review("un logo, présenté sur fond clair, sur fond sombre et en petit", preview, request)
        if defects and (fixed := self._fix(LOGO_PROMPT, check_logo, "svg", title, svg, defects)):
            svg = publish(fixed.content)
            summary += " Relu et corrigé après un premier rendu."
        png = export_png(path)
        extra = {"preview": preview, **({"png": png} if png else {})}
        return Creation("logo", title, summary, path, svg, request, self.name, "svg", extra)

    def _palette(self, request: str, prompt: Optional[str] = None) -> Creation:
        problem = ""
        for _attempt in range(2):
            answer = generate(PALETTE_PROMPT, (prompt or f"Palette pour : {request}") + problem, 0.7, max_tokens=700, json_mode=True)
            try:
                data = parse_palette(answer)
                break
            except CreationError as exc:
                problem = f"\n\nTa réponse précédente a été refusée : {exc}. Recommence."
        else:
            raise CreationError(problem.strip())
        content = json.dumps(data, ensure_ascii=False, indent=2)
        path = self.workshop.save("design", f"palette {data['nom']}", "html", render_palette(data))
        names = ", ".join(c["nom"] for c in data["couleurs"][:5])
        summary = f"{data.get('ambiance') or ''} Ses couleurs : {names}.".strip()
        return Creation("palette", data["nom"], summary, path, content, request, self.name, "json")

    def revise(self, creation: Creation, request: str) -> Creation:
        if creation.kind == "palette":
            prompt = f"Palette actuelle :\n{creation.content}\n\nModification demandée : {request}\nRenvoie la palette complète."
            return self._palette(f"{creation.request} — {request}", prompt)
        prompt = REVISE_PROMPT.format(
            title=creation.title, language=creation.language, content=creation.content, request=request
        )
        if creation.kind == "logo":
            return self._logo(f"{creation.request} — {request}", prompt, creation.title)
        return self._page(f"{creation.request} — {request}", prompt, creation.title)

