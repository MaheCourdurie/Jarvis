from __future__ import annotations

from agents.alarms import AlarmAgent
from agents.calendar import CalendarAgent
from agents.mail import MailAgent
from agents.notes import NotesAgent
from agents.travel import TravelAgent
from core.agent import Context
from core.controller import Controller


class OrganisationController(Controller):
    """Organiser la journée : messagerie, agenda, alarmes, notes et listes, trajets."""

    name = "organisation"
    description = "messagerie, agenda, alarmes, notes, trajets"

    def __init__(self, context: Context) -> None:
        super().__init__([
            MailAgent(context), CalendarAgent(context), AlarmAgent(context), NotesAgent(context), TravelAgent(context),
        ])
