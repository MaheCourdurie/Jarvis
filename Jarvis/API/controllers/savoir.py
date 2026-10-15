from __future__ import annotations

from agents.conversation import ConversationAgent
from agents.memory import MemoryAgent
from agents.translate import TranslateAgent
from agents.vision import VisionAgent
from agents.web import WebAgent
from core.agent import Context
from core.controller import Controller


class SavoirController(Controller):
    """Répondre, chercher, retenir : web, conversation, mémoire, traduction, vision.

    L'agent de conversation ne possède aucune action : Jarvis lui confie tout ce
    qu'aucun autre agent n'a pris. Il appelle l'agent web s'il lui manque une information,
    et connaît ce que l'agent mémoire a retenu de l'utilisateur.
    """

    name = "savoir"
    description = "recherche web, conversation, mémoire, traduction, vision"

    def __init__(self, context: Context) -> None:
        self.web = WebAgent(context)
        self.memory = MemoryAgent(context)
        self.conversation = ConversationAgent(context, self.web, self.memory)
        super().__init__([self.web, self.conversation, self.memory, TranslateAgent(context), VisionAgent(context)])
