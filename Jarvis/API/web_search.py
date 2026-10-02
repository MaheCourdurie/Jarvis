"""Recherche sur le web : Jarvis interroge un moteur, lit les pages et en garde les passages utiles.

Aucune clé d'API : les résultats viennent de DuckDuckGo (interface HTML).
Le texte des pages est un contenu non fiable : il est transmis au modèle comme une
donnée, et le modèle ne peut de toute façon déclencher aucune action.
"""

from __future__ import annotations

import html
import ipaddress
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests

from config import STT_LANGUAGE
from persona import fold


SEARCH_URL = "https://html.duckduckgo.com/html/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15"
)
MAX_RESULTS = 6
PAGES_TO_READ = 3
SEARCH_TIMEOUT = 8.0
PAGE_TIMEOUT = 5.0
# Lecture des pages : 0,1 à 1,5 s d'ordinaire, parfois bien plus. Au-delà de ce délai, Jarvis
# répond sans la page (avec l'extrait du moteur) plutôt que de faire attendre son utilisateur.
READ_DEADLINE = 2.5
MAX_PAGE_BYTES = 800_000
MAX_REDIRECTS = 4
EXTRACT_CHARS = 1400          # texte conservé par page (moins, et des horaires se perdent)
CACHE_SECONDS = 300

STOPWORDS = {
    "les", "des", "une", "aux", "pour", "dans", "sur", "avec", "sans", "que", "qui", "quoi", "quel", "quelle",
    "quels", "quelles", "est", "sont", "ont", "the", "and", "pas", "plus", "moi", "mon", "mes", "ton", "tes",
    "son", "ses", "ce", "cet", "cette", "ces", "par", "ou", "et", "du", "de", "la", "le", "un", "il", "elle",
    "y", "a", "au", "en", "me", "te", "se", "ne", "quand", "comment", "combien", "jarvis",
}
# Mots qui signalent le passage recherché, selon le sujet de la question.
TOPIC_HINTS = [
    (
        re.compile(r"horaire|ouvert|ouvre|ferme|heure"),
        ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche", "ouvert", "ferme", "horaires", "7j"],
    ),
    (re.compile(r"prix|tarif|coute|combien|abonnement"), ["€", "eur", "prix", "tarif", "mois"]),
]
# Balises qui ouvrent une nouvelle ligne de texte. Les cellules et les <span> restent sur la
# ligne en cours : une ligne de tableau donne ainsi « Lundi 08:30 21:00 ».
BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article",
    "table", "ul", "ol", "dl", "dd", "dt", "blockquote", "title",
}
SKIPPED_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "form", "button", "select", "iframe", "template"}


class WebSearchError(Exception):
    pass


@dataclass
class WebResult:
    title: str
    url: str
    site: str
    snippet: str
    extract: str = ""


_lock = threading.Lock()
_cache: dict[str, tuple[float, list[WebResult]]] = {}


def _clean_markup(value: str) -> str:
    """Retire les balises et décode les entités d'un fragment HTML."""
    text = html.unescape(re.sub(r"<[^>]+>", "", value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _site_name(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def parse_results(page: str) -> list[WebResult]:
    """Extrait les résultats (titre, adresse, extrait) de la page de DuckDuckGo."""
    results: list[WebResult] = []
    blocks = re.split(r'<div[^>]+class="[^"]*\bresult\b[^"]*"', page)[1:]
    for block in blocks:
        link = re.search(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, flags=re.S)
        if not link:
            continue
        href = html.unescape(link.group(1))
        # Les liens passent par une redirection : l'adresse réelle est dans le paramètre uddg.
        target = parse_qs(urlparse(href).query).get("uddg", [href])[0]
        url = unquote(target)
        if url.startswith("//"):
            url = "https:" + url
        site = _site_name(url)
        if not url.startswith(("http://", "https://")) or not site or site.endswith("duckduckgo.com"):
            continue  # publicité ou lien interne au moteur

        snippet = re.search(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', block, flags=re.S)
        results.append(
            WebResult(
                title=_clean_markup(link.group(2)),
                url=url,
                site=site,
                snippet=_clean_markup(snippet.group(1)) if snippet else "",
            )
        )
        if len(results) >= MAX_RESULTS:
            break
    return results


def search(query: str) -> list[WebResult]:
    """Interroge le moteur de recherche et renvoie les premiers résultats."""
    language = (STT_LANGUAGE or "fr")[:2]
    try:
        response = requests.post(
            SEARCH_URL,
            data={"q": query, "kl": f"{language}-{language}"},
            headers={"User-Agent": USER_AGENT, "Accept-Language": f"{language},en;q=0.5"},
            timeout=SEARCH_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise WebSearchError(f"moteur de recherche injoignable: {exc}") from exc

    if response.status_code != 200:
        raise WebSearchError(f"le moteur de recherche a répondu {response.status_code}")

    results = parse_results(response.text)
    if not results:
        raise WebSearchError("aucun résultat exploitable")
    return results


# ── Lecture des pages ──────────────────────────────────────────────────────

def is_public_url(url: str) -> bool:
    """Refuse tout ce qui n'est pas une page web publique (réseau local, adresses internes)."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, None)}
    except OSError:
        return False
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return bool(addresses)


def fetch_page(url: str) -> str:
    """Télécharge une page HTML publique (taille et redirections bornées)."""
    for _ in range(MAX_REDIRECTS):
        if not is_public_url(url):
            raise WebSearchError(f"adresse refusée: {url}")
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "fr,en;q=0.5"},
            timeout=PAGE_TIMEOUT,
            stream=True,
            allow_redirects=False,
        )
        # Les redirections sont suivies à la main pour revalider chaque adresse.
        if response.status_code in {301, 302, 303, 307, 308} and response.headers.get("Location"):
            url = urljoin(url, response.headers["Location"])
            response.close()
            continue
        if response.status_code != 200:
            raise WebSearchError(f"HTTP {response.status_code}")

        content_type = response.headers.get("Content-Type", "").lower()
        if "html" not in content_type and "text/plain" not in content_type:
            raise WebSearchError(f"contenu non textuel: {content_type}")

        data = b""
        for chunk in response.iter_content(65536):
            data += chunk
            if len(data) >= MAX_PAGE_BYTES:
                break
        response.close()

        charset = re.search(r"charset=([\w-]+)", content_type)
        if not charset:
            charset = re.search(rb'<meta[^>]+charset=["\']?([\w-]+)', data[:4096], flags=re.I)
        encoding = charset.group(1) if charset else "utf-8"
        if isinstance(encoding, bytes):
            encoding = encoding.decode("ascii", "replace")
        try:
            return data.decode(encoding, errors="replace")
        except LookupError:
            return data.decode("utf-8", errors="replace")
    raise WebSearchError("trop de redirections")


class _TextExtractor(HTMLParser):
    """Garde le texte visible d'une page, une ligne par bloc."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._current: list[str] = []
        self._skip_depth = 0

    def _flush(self) -> None:
        line = re.sub(r"\s+", " ", "".join(self._current)).strip()
        self._current = []
        if line and (not self.lines or self.lines[-1] != line):
            self.lines.append(line)

    def handle_starttag(self, tag, attrs):
        if tag in SKIPPED_TAGS:
            self._skip_depth += 1
        elif tag in BLOCK_TAGS:
            self._flush()
        else:
            self._current.append(" ")  # deux balises voisines ne doivent pas coller leurs mots

    def handle_endtag(self, tag):
        if tag in SKIPPED_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in BLOCK_TAGS:
            self._flush()
        else:
            self._current.append(" ")

    def handle_data(self, data):
        if not self._skip_depth:
            self._current.append(data)

    def text_lines(self) -> list[str]:
        self._flush()
        return self.lines


def _keywords(query: str) -> list[str]:
    """Mots significatifs de la question, complétés par ceux qui signalent la réponse attendue."""
    folded = fold(query)
    words = [word for word in re.findall(r"[a-z0-9€]+", folded) if len(word) >= 3 and word not in STOPWORDS]
    for pattern, hints in TOPIC_HINTS:
        if pattern.search(folded):
            words.extend(hints)
    return list(dict.fromkeys(words))


def extract_passages(page: str, query: str, budget: Optional[int] = None) -> str:
    """Retient, dans une page, les lignes en rapport avec la question (et leur voisinage)."""
    budget = budget or EXTRACT_CHARS
    parser = _TextExtractor()
    try:
        parser.feed(page)
    except Exception:
        return ""
    lines = [line[:320] for line in parser.text_lines() if len(line) >= 2]
    if not lines:
        return ""

    keywords = _keywords(query)
    scores = []
    for line in lines:
        folded = fold(line)
        scores.append(sum(1 for word in keywords if word in folded))

    # Les lignes les plus pertinentes d'abord, chacune avec un peu de contexte autour.
    ranked = sorted((index for index, score in enumerate(scores) if score), key=lambda index: (-scores[index], index))
    keep: set[int] = set()
    used = 0
    for index in ranked:
        for neighbour in range(max(0, index - 1), min(len(lines), index + 6)):
            if neighbour not in keep:
                if used + len(lines[neighbour]) > budget:
                    break
                keep.add(neighbour)
                used += len(lines[neighbour]) + 1
        if used >= budget * 0.9:
            break

    if not keep:  # aucun mot de la question dans la page : on garde son début
        for index, line in enumerate(lines):
            if used + len(line) > budget // 2:
                break
            keep.add(index)
            used += len(line) + 1

    return "\n".join(lines[index] for index in sorted(keep))


def _read(result: WebResult, query: str) -> str:
    try:
        return extract_passages(fetch_page(result.url), query)
    except Exception as exc:
        print(f"[WEB] Lecture impossible ({result.site}): {exc}", flush=True)
        return ""


def gather(query: str) -> list[WebResult]:
    """Cherche, puis lit en parallèle les premières pages pour en extraire les passages utiles."""
    key = query.strip().lower()
    with _lock:
        cached = _cache.get(key)
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1]

    results = search(query)
    pool = ThreadPoolExecutor(max_workers=PAGES_TO_READ)
    futures = {pool.submit(_read, result, query): result for result in results[:PAGES_TO_READ]}
    done, _late = wait(futures, timeout=READ_DEADLINE)
    for future in done:
        futures[future].extract = future.result()
    # Les pages trop lentes sont abandonnées : les extraits du moteur suffiront.
    pool.shutdown(wait=False, cancel_futures=True)

    with _lock:
        _cache[key] = (time.time(), results)
    return results


def format_for_model(query: str, results: list[WebResult]) -> str:
    """Met en forme les résultats pour le modèle de langage."""
    blocks = [f"Résultats de la recherche web pour « {query} » (fournis par ton module de recherche) :"]
    for number, result in enumerate(results, start=1):
        block = f"[{number}] {result.title} — {result.site}"
        if result.snippet:
            block += f"\n{result.snippet}"
        if result.extract:
            block += f"\nExtrait de la page :\n{result.extract}"
        blocks.append(block)
    return "\n\n".join(blocks)


def sources(results: list[WebResult], limit: int = 3) -> list[dict]:
    """Sources affichées par le HUD sous la réponse."""
    return [{"title": result.title, "url": result.url, "site": result.site} for result in results[:limit]]


def clean_query(text: str) -> str:
    """Transforme une demande orale en requête (« cherche … sur internet » → « … »)."""
    query = (text or "").strip().strip(" .!?")
    query = re.sub(
        r"^(?:(?:peux|pourrais|pouvez|pourriez)[- ](?:tu|vous)\s+)?(?:me\s+)?"
        r"(?:(?:fais|lance)(?:[- ]moi)?\s+une\s+recherche(?:\s+(?:web|internet))?\s+(?:sur|pour|de)\s+"
        r"|(?:cherche|recherche|chercher|rechercher|trouve|trouver|regarde|renseigne[- ]toi sur)(?:[- ]moi)?\s+)",
        "",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(r"\s+(?:sur|dans)\s+(?:google|internet|le web|le net|la toile)$", "", query, flags=re.IGNORECASE)
    return query.strip() or (text or "").strip()
