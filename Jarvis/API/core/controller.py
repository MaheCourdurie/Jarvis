from __future__ import annotations

import time

from core.agent import Agent
from persona import Reply


class Controller:
    """Chef d'équipe : regroupe les agents d'un même domaine et leur répartit le travail.

    Jarvis confie une action au contrôleur du domaine, qui la passe à l'agent compétent.
    Un nouvel agent rejoint l'équipe de son contrôleur (controllers/*.py) : Jarvis n'a
    rien à savoir de lui.
    """

    name = "contrôleur"
    description = ""

    def __init__(self, agents: list[Agent]) -> None:
        self.agents = agents
        self.routes: dict[str, Agent] = {}
        for agent in agents:
            for action in agent.actions:
                if action in self.routes:
                    raise ValueError(f"L'action « {action} » est revendiquée par {self.routes[action].name} et {agent.name}.")
                self.routes[action] = agent

    @property
    def actions(self) -> frozenset[str]:
        return frozenset(self.routes)

    def agent_for(self, action: str) -> Agent | None:
        return self.routes.get(action)

    def run(self, action: str, params: dict) -> Reply:
        agent = self.routes[action]
        start = time.perf_counter()
        reply = agent.run(action, params)
        elapsed = round((time.perf_counter() - start) * 1000)
        print(f"[JARVIS] {self.name} › {agent.name} › {action} ({elapsed} ms)", flush=True)
        return reply

    def start(self) -> None:
        for agent in self.agents:
            agent.start()

    def occupied_with(self) -> list[str]:
        """Travaux longs en cours qui occupent le modèle (la conversation devra attendre)."""
        return []
