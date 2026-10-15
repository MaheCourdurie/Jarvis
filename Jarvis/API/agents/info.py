from __future__ import annotations

from agents.briefing import build_briefing
from agents.system import handle_date, handle_time
from core.agent import Agent, Handler
from services.weather import handle_air_quality, handle_sun, handle_weather


class InfoAgent(Agent):
    """Renseignements immédiats : heure, date, météo sur 7 jours, soleil, qualité de l'air, briefing."""

    name = "informations"

    def handlers(self) -> dict[str, Handler]:
        return {
            "time": lambda params: handle_time(self.context.timezone),
            "date": lambda params: handle_date(self.context.timezone),
            "weather": handle_weather,
            "sun": handle_sun,
            "air_quality": handle_air_quality,
            "briefing": lambda params: build_briefing(self.context.dashboard, kind="full"),
        }
