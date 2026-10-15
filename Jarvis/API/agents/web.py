from __future__ import annotations

import re

from agents.system import handle_web_search
from core.agent import Agent, Handler
from persona import Reply, TITLE
from services import llm, web_search

SUMMARY_PROMPT = (
    "Tu résumes une page web en français pour J.A.R.V.I.S. : 3 à 5 phrases simples, les faits essentiels "
    "d'abord, sans inventer ce qui n'est pas dans le texte. Pas de titre, pas de liste."
)


class WebAgent(Agent):
    """Le réseau : lit les pages web pour répondre, ou ouvre la recherche dans le navigateur."""

    name = "web"
    # Ouvrir le navigateur pilote le poste ; on le propose aussi quand la recherche échoue.
    local_only = frozenset({"web_search"})
    confirmable = frozenset({"web_search"})

    def handlers(self) -> dict[str, Handler]:
        return {"web_search": handle_web_search, "summarize_url": self.summarize_url}

    def summarize_url(self, params: dict) -> Reply:
        """« Résume cette page : https://… »"""
        url = str(params.get("url") or "").strip()
        if not re.match(r"https?://", url):
            url = "https://" + url if url else ""
        if not url:
            return Reply(text=f"Quelle page dois-je résumer, {TITLE} ?")
        try:
            text = web_search.page_text(web_search.fetch_page(url))
        except web_search.WebSearchError as exc:
            return Reply(text=f"Je ne parviens pas à lire cette page, {TITLE} ({exc}).")
        if len(text) < 80:
            return Reply(text=f"Cette page ne contient presque pas de texte lisible, {TITLE}.")
        try:
            summary = llm.complete(SUMMARY_PROMPT, f"Page {url} :\n{text}", 0.2, 400, timeout=90)
        except Exception as exc:
            print(f"[WEB] Résumé impossible: {exc}", flush=True)
            return Reply(text=f"Je n'ai pas réussi à résumer cette page, {TITLE}.")
        summary = llm.clean_reply(summary)
        return Reply(text=f"{summary}\n\nSource : {url}", speech=summary, data={"sources": [{"title": url, "url": url}]})

    def research(self, query: str) -> list[web_search.WebResult]:
        """Cherche et lit les meilleures pages (lève WebSearchError si le réseau ne répond pas)."""
        return web_search.gather(query)

    @staticmethod
    def fallback_query(text: str) -> str:
        return web_search.clean_query(text)
