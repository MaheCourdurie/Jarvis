from __future__ import annotations

import random
from typing import Any, Iterator

from agents.briefing import live_context
from agents.web import WebAgent
from config import WEB_SEARCH_ENABLED
from core.agent import Agent, Handler
from persona import TITLE
from services import llm, web_search

# Ce que Jarvis dit pendant qu'il interroge le web.
SEARCH_NOTICES = [
    "Un instant, {t}, je consulte le réseau.",
    "Je me renseigne, {t}.",
    "Je cherche cela pour vous, {t}.",
]


class ConversationAgent(Agent):
    """Conversation libre avec le modèle local, qui fait appel à l'agent web s'il lui manque une information.

    Il ne possède aucune action : Jarvis lui confie tout ce qu'aucun autre agent n'a pris.
    """

    name = "conversation"

    def __init__(self, context, web: WebAgent, memory=None) -> None:
        super().__init__(context)
        self.web = web
        self.memory = memory

    def handlers(self) -> dict[str, Handler]:
        return {}

    def reply(
        self,
        history: list[Any],
        text: str,
        temperature: float,
        plan: dict,
        offer_browser: bool,
    ) -> Iterator[dict]:
        """Fait répondre le modèle, en cherchant d'abord sur le web si la question le demande.

        Produit des événements : {"type": "sentence"}, {"type": "status"}, {"type": "sources"}
        et {"type": "pending"}. La recherche est décidée soit par le routeur (plan["search"]),
        soit par le modèle lui-même, qui appelle alors l'outil recherche_web.
        """
        context = live_context(self.context.dashboard, text)
        remembered = self.memory.as_context() if self.memory is not None else ""
        if remembered:
            context = f"{context}\n{remembered}"
        tools_ok = WEB_SEARCH_ENABLED and llm.supports_tools()
        notice = {"type": "sentence", "text": random.choice(SEARCH_NOTICES).format(t=TITLE)}
        query = plan.get("query")

        if plan.get("search"):
            yield {"type": "status", "label": "Recherche web"}
            yield notice
            if not query:
                query = llm.search_query(history, text) or self.web.fallback_query(text)
        else:
            spoke = False
            stream = llm.chat_stream(
                history,
                text,
                temperature,
                f"{llm.TOOLS_HINT}\n\n{context}" if tools_ok else context,
                tools=[llm.WEB_TOOL] if tools_ok else None,
            )
            for item in stream:
                if isinstance(item, llm.ToolCall):
                    query = str(item.arguments.get("requete") or "").strip() or self.web.fallback_query(text)
                    yield {"type": "status", "label": "Recherche web"}
                    if not spoke:
                        yield notice
                    break
                spoke = True
                yield {"type": "sentence", "text": item}
            if not query:
                return

        try:
            results = self.web.research(query)
        except web_search.WebSearchError as exc:
            print(f"[WEB] Recherche impossible ({query}): {exc}", flush=True)
            if not offer_browser:
                yield {"type": "sentence", "text": f"Le réseau de recherche ne répond pas pour le moment, {TITLE}."}
            else:
                yield {
                    "type": "sentence",
                    "text": f"Le réseau de recherche ne répond pas, {TITLE}. Dois-je ouvrir la recherche dans votre navigateur ?",
                }
                yield {"type": "pending", "pending": {"action": "web_search", "params": {"query": query, "engine": "web"}}}
            return

        yield {"type": "sources", "query": query, "sources": web_search.sources(results)}
        answer_context = f"{context}\n\n{web_search.format_for_model(query, results)}\n\n{llm.WEB_ANSWER_RULES}"
        # Prompt réduit et historique court : le modèle a moins à lire et commence à parler plus tôt.
        answer = llm.chat_stream(
            history,
            text,
            llm.WEB_TEMPERATURE,
            answer_context,
            system=llm.WEB_PERSONA,
            history_limit=llm.WEB_HISTORY_MESSAGES,
        )
        for sentence in answer:
            yield {"type": "sentence", "text": sentence}
