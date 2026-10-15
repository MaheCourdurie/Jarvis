from __future__ import annotations

from agents.routines import RoutineAgent
from core.agent import Context
from core.controller import Controller


class RoutinesController(Controller):
    """Enchaîner plusieurs demandes d'un mot : « mode travail », « routine bonne nuit »."""

    name = "routines"
    description = "routines"

    def __init__(self, context: Context) -> None:
        self.routines = RoutineAgent(context)
        super().__init__([self.routines])
