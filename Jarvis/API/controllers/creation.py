from __future__ import annotations

from agents.atelier import AtelierAgent, Workshop
from agents.code import CodeAgent
from agents.design import DesignAgent
from agents.document import DocumentAgent
from core.agent import Context
from core.controller import Controller


class CreationController(Controller):
    """Créer : programmes, pages web, logos, palettes, documents, puis les retoucher à la demande.

    Les agents code, design et documents partagent un atelier (agents/atelier.py) : le dossier des
    créations, la dernière en mémoire et le travail en tâche de fond. Le chef d'atelier
    rouvre, liste et fait retoucher les créations par l'agent qui les a faites.
    """

    name = "création"
    description = "code, design, documents"

    def __init__(self, context: Context) -> None:
        self.workshop = Workshop()
        code = CodeAgent(context, self.workshop)
        design = DesignAgent(context, self.workshop)
        documents = DocumentAgent(context, self.workshop)
        makers = [code, design, documents]
        super().__init__([*makers, AtelierAgent(context, self.workshop, makers)])

    def occupied_with(self) -> list[str]:
        return list(self.workshop.busy)
