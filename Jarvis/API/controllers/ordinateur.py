from __future__ import annotations

from agents.files import FilesAgent
from agents.info import InfoAgent
from agents.music import MusicAgent
from agents.system import SystemAgent
from core.agent import Context
from core.controller import Controller


class OrdinateurController(Controller):
    """Le poste et l'instant présent : réglages du Mac, musique, fichiers, heure, météo, briefing."""

    name = "ordinateur"
    description = "pilotage du poste, informations, musique, fichiers"

    def __init__(self, context: Context) -> None:
        super().__init__([SystemAgent(context), InfoAgent(context), MusicAgent(context), FilesAgent(context)])
