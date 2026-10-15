from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from persona import Reply


@dataclass
class Context:
    """Ressources partagées par Jarvis et ses agents, créées une seule fois au démarrage.

    Les agents lisent ces ressources au moment d'agir (jamais de copie) : remplacer
    le client Google ici suffit à le remplacer partout.
    """

    google: Any
    alarms: Any
    dashboard: Any

    @property
    def timezone(self) -> Any:
        return self.google.timezone


Handler = Callable[[dict], Reply]


class Agent:
    """Spécialiste d'un domaine : il déclare ses actions et sait les exécuter.

    Jarvis (core/jarvis.py) comprend la demande, choisit l'agent qui possède l'action,
    applique les règles communes (confirmation, accès distant, liaison Google), puis
    lui confie l'exécution. Un agent ne connaît ni HTTP ni les autres agents.
    """

    name = "agent"
    # Toutes les actions de l'agent passent par Google : rien n'est tenté sans la liaison.
    needs_google = False
    # Actions qui modifient l'agenda ou la messagerie : le tableau de bord est relu ensuite.
    writes: frozenset[str] = frozenset()
    # Actions qui demandent un « oui » avant d'être exécutées.
    confirmable: frozenset[str] = frozenset()
    # Actions qui pilotent ce poste : refusées aux clients distants (téléphone, Discord).
    local_only: frozenset[str] = frozenset()
    # L'agent reçoit params["remote"] : vrai si la demande vient d'un autre appareil
    # (une création est alors enregistrée sur le Mac sans y être ouverte).
    needs_origin = False

    def __init__(self, context: Context) -> None:
        self.context = context
        self._handlers = self.handlers()

    def handlers(self) -> dict[str, Handler]:
        """Associe chaque action de l'agent à la fonction qui l'exécute."""
        raise NotImplementedError

    @property
    def actions(self) -> frozenset[str]:
        return frozenset(self._handlers)

    def run(self, action: str, params: dict) -> Reply:
        return self._handlers[action](params)

    def start(self) -> None:
        """Lance les tâches de fond de l'agent (appelé une fois au démarrage de l'API)."""
