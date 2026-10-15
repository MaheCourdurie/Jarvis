from __future__ import annotations

from agents.home import HomeAgent
from core.agent import Context
from core.controller import Controller


class MaisonController(Controller):
    """La maison connectée, à travers les Raccourcis de l'utilisateur."""

    name = "maison"
    description = "maison connectée"

    def __init__(self, context: Context) -> None:
        super().__init__([HomeAgent(context)])
