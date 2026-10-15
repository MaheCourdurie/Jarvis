"""Jarvis, le chef d'orchestre.

Chaque demande suit le même chemin :

    route HTTP  →  Jarvis  →  contrôleur du domaine  →  agent  →  réponse
                     └── rien de reconnu → contrôleur « savoir » → agent de conversation

Jarvis comprend la phrase (core/intents.py), choisit le contrôleur qui couvre l'action et
applique les règles communes à tous : confirmation avant les gestes importants, pilotage
du poste interdit à distance, liaison Google requise, erreurs dites dans son ton.
Le contrôleur passe l'action à l'agent de son équipe, qui l'exécute.
"""

from __future__ import annotations

import re
import time
from typing import Iterator, Optional

from config import CONFIRM_ACTIONS, OLLAMA_MODEL, REMOTE_SYSTEM_CONTROL, STRICT_ACTIONS_ONLY, WEB_SEARCH_ENABLED
from core.agent import Agent, Context
from core import fallback
from core.controller import Controller
from core.intents import COMMAND_HELP, classify_confirmation, detect_action, extract_recent_email_from_history
from core.messages import ChatRequest
from persona import Reply, TITLE, fold
from services import llm
from services.google_client import GoogleApiError, GoogleConfigError

VERSION = "2.0.0"

LOCAL_CLIENTS = {"web", "hud", "local"}

OUT_OF_SCOPE_REPLY = (
    f"Je crains que cette demande ne sorte de mon périmètre actuel, {TITLE} : "
    "en mode strict, je me limite à la messagerie, à l'agenda, aux alarmes et au pilotage du poste. "
    "Dites « aide » pour la liste des commandes."
)

CAPABILITIES_REPLY = (
    f"Je gère votre messagerie, votre agenda, vos alarmes et vos minuteurs, {TITLE}. "
    "Je pilote ce poste — applications, volume — et je vous renseigne sur l'heure, la météo et "
    "l'état des systèmes. Je cherche sur le web ce que j'ignore, et pour le reste, je suis toujours disposé à converser. "
    "Dites « aide » pour la liste des commandes."
)


def classify_support_request(text: str) -> str | None:
    """Classe les demandes d'aide entre liste des commandes et capacites generales."""
    folded = fold(text).strip(" .!?")

    if re.fullmatch(
        r"(?:help|aide|a l'aide|commandes?|(?:la )?liste des commandes|quelles sont (?:les|tes|vos) commandes)",
        folded,
    ):
        return "commands"

    capability_patterns = [
        r"\bque\s+(?:peux[-\s]?tu|pouvez[-\s]?vous|sais[-\s]?tu|savez[-\s]?vous)\s+faire\b",
        r"\bqu'est[-\s]?ce\s+que\s+(?:tu\s+(?:peux|sais)|vous\s+(?:pouvez|savez))\s+faire\b",
        r"\bquelles?\s+sont\s+(?:tes|vos)\s+(?:capacites|fonctions|fonctionnalites|competences)\b",
        r"\b(?:tes|vos)\s+fonctions\b",
        r"\btu\s+sais\s+faire\s+quoi\b",
    ]
    if any(re.search(pattern, folded) for pattern in capability_patterns):
        return "capabilities"

    return None


def response(reply: Reply, action: str | None = None, source: str = "api") -> dict:
    """Met la réponse d'un agent au format renvoyé par l'API."""
    return {
        "reply": reply.text,
        "speech": reply.spoken,
        "action": action,
        "source": source,
        "pending": reply.pending,
        "data": reply.data or None,
    }


def _elapsed_ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


class Jarvis:
    def __init__(self, context: Context, controllers: list[Controller], conversation: Agent) -> None:
        self.context = context
        self.controllers = controllers
        self.conversation = conversation
        # Pour le journal : « savoir › conversation ».
        self.conversation_path = " › ".join(
            [c.name for c in controllers if conversation in c.agents][:1] + [conversation.name]
        )
        # Tables de routage : chaque action relève d'un seul contrôleur, et d'un seul agent.
        self.dispatch: dict[str, Controller] = {}
        self.routes: dict[str, Agent] = {}
        for controller in controllers:
            for action in controller.actions:
                if action in self.dispatch:
                    raise ValueError(
                        f"L'action « {action} » est revendiquée par {self.dispatch[action].name} et {controller.name}."
                    )
                self.dispatch[action] = controller
                self.routes[action] = controller.agent_for(action)

    @property
    def agents(self) -> list[Agent]:
        return [agent for controller in self.controllers for agent in controller.agents]

    def start(self) -> None:
        for controller in self.controllers:
            controller.start()

    # ── Exécution d'une action ────────────────────────────────────────────

    def run(self, action_payload: dict) -> Reply:
        """Confie l'action au contrôleur du domaine (ou y répond lui-même : aide, politesses)."""
        action = action_payload.get("action")
        params = action_payload.get("params") or {}

        if action == "smalltalk":
            return action_payload["reply"]
        if action == "help":
            return Reply(text=COMMAND_HELP, speech=f"La liste des commandes est à l'écran, {TITLE}.")
        if action == "command_error":
            return Reply(text=str(action_payload.get("message", "Commande invalide.")))
        if action == "misses":
            entries = fallback.recent_misses()
            if not entries:
                return Reply(text=f"Je n'ai rien noté d'incompris, {TITLE}.")
            lines = [f"- « {item['phrase']} » → {item['modele']}" for item in entries]
            return Reply(
                text=f"Les phrases que mon routeur n'a pas reconnues, {TITLE} (à m'apprendre) :\n" + "\n".join(lines),
                speech=f"J'ai noté {len(entries)} phrases incomprises, {TITLE}. La liste est à l'écran.",
            )

        agent = self.routes.get(action)
        if agent is None:
            return Reply(text=f"Cette action ne fait pas partie de mes attributions, {TITLE}.")
        if agent.needs_google and not self.context.google.is_configured():
            # Inutile de rédiger un mail ou de demander une confirmation si Google n'est pas relié.
            raise GoogleConfigError("liaison Google non établie")

        reply = self.dispatch[action].run(action, params)
        if action in agent.writes and reply.pending is None:
            self.context.dashboard.invalidate()
        return reply

    def execute(self, action_payload: dict) -> dict:
        """Exécute une action et traduit les erreurs Google dans le ton de Jarvis."""
        action = action_payload.get("action")
        agent = self.routes.get(action)
        source = "google" if agent is not None and agent.needs_google else "api"

        try:
            reply = self.run(action_payload)
        except GoogleConfigError:
            missing = ", ".join(self.context.google.status().get("missing_keys", []))
            reply = Reply(
                text=(
                    f"La liaison Google n'est pas établie, {TITLE}. "
                    "Connectez votre compte depuis le panneau « Liaisons » du HUD, puis redemandez-moi."
                    + (f"\nÉléments manquants : {missing}" if missing else "")
                ),
                speech=f"La liaison Google n'est pas établie, {TITLE}. Connectez votre compte, puis redemandez-moi.",
                data={"google_required": True},
            )
            return response(reply, action, "api")
        except GoogleApiError as exc:
            reply = Reply(
                text=f"Google a refusé la demande, {TITLE} : {exc}",
                speech=f"Google a refusé la demande, {TITLE}. Le détail est à l'écran.",
            )
        return response(reply, action, source)

    def allows(self, action: str, request: ChatRequest) -> bool:
        """Le pilotage du poste n'obéit qu'au poste lui-même (sauf JARVIS_REMOTE_SYSTEM_CONTROL=1)."""
        agent = self.routes.get(action)
        if agent is None or action not in agent.local_only:
            return True
        return REMOTE_SYSTEM_CONTROL or request.client.lower() in LOCAL_CLIENTS

    def guarded(self, request: ChatRequest, action_payload: dict) -> dict:
        """Exécute une action, sauf si elle pilote le poste et vient d'un client distant."""
        action = action_payload.get("action")
        if not self.allows(action, request):
            reply = Reply(text=f"Le pilotage du poste n'est possible que depuis le poste lui-même, {TITLE}.")
            return response(reply, action)
        agent = self.routes.get(action)
        if agent is not None and agent.needs_origin:
            params = {**(action_payload.get("params") or {}), "remote": request.client.lower() not in LOCAL_CLIENTS}
            action_payload = {**action_payload, "params": params}
        return self.execute(action_payload)

    def run_phrase(self, text: str, remote: bool = False) -> dict:
        """Exécute une phrase comme si on la disait (étapes des routines), sans conversation."""
        action_payload = detect_action(text)
        if action_payload is None or action_payload.get("action") in {"web_answer", "run_routine"}:
            return response(Reply(text=f"Je n'ai pas compris l'étape « {text} »"))
        request = ChatRequest(message=text, client="remote" if remote else "local")
        return self.guarded(request, action_payload)

    def _awaits_confirmation(self, action: Optional[str]) -> bool:
        agent = self.routes.get(action)
        return agent is not None and action in agent.confirmable

    # ── Compréhension de la demande ───────────────────────────────────────

    def resolve(self, request: ChatRequest) -> tuple[Optional[dict], Optional[dict]]:
        """Traite tout ce qui ne demande pas le modèle de langage.

        Retourne (réponse, None) si un agent a répondu. Sinon (None, plan) : la demande
        revient à l'agent de conversation, et le plan précise s'il faut d'abord chercher
        sur le web ({"text": ..., "search": bool, "query": requête éventuelle}).
        """
        text = request.message.strip()

        # 1) Réponse à une demande de confirmation (« Dois-je l'envoyer ? » → « oui »).
        pending = request.pending or {}
        if self._awaits_confirmation(pending.get("action")):
            decision = classify_confirmation(text)
            if decision == "yes":
                params = dict(pending.get("params") or {})
                params.pop("confirm", None)
                return self.guarded(request, {"action": pending["action"], "params": params}), None
            if decision == "no":
                return response(Reply(text=f"Très bien, {TITLE}. Je n'en fais rien."), "cancelled"), None

        # 2) Action reconnue par le routeur d'intentions.
        action_payload = detect_action(text, fallback_email=extract_recent_email_from_history(request.history))
        search_plan = None

        if action_payload is not None and action_payload.get("action") == "web_answer":
            # Jarvis cherche lui-même : la réponse sera rédigée par le modèle à partir des résultats.
            search_plan = {"text": text, "search": True, "query": (action_payload.get("params") or {}).get("query")}
        elif action_payload is not None:
            if not CONFIRM_ACTIONS and isinstance(action_payload.get("params"), dict):
                action_payload["params"].pop("confirm", None)
            return self.guarded(request, action_payload), None

        # 3) Demandes d'aide.
        support_kind = classify_support_request(text)
        if support_kind == "commands":
            return response(self.run({"action": "help"}), "help"), None
        if support_kind == "capabilities":
            return response(Reply(text=CAPABILITIES_REPLY)), None

        model_online, _reason = llm.ollama_status()

        # 4) Un ordre que le routeur n'a pas reconnu : le modèle choisit l'agent, et la phrase
        #    est notée pour être apprise.
        if search_plan is None and fallback.looks_like_command(text):
            guess = fallback.guess_action(text, set(self.routes)) if model_online else None
            fallback.record_miss(text, guess["action"] if guess else None)
            if guess is not None:
                print(f"[JARVIS] Routage de secours : « {text} » → {guess['action']}", flush=True)
                return self.guarded(request, guess), None

        # 5) Conversation : réservée au modèle, sauf en mode strict.
        if STRICT_ACTIONS_ONLY and search_plan is None:
            return response(Reply(text=OUT_OF_SCOPE_REPLY)), None

        if search_plan is not None and (not model_online or not WEB_SEARCH_ENABLED):
            # Recherche désactivée, ou pas de modèle pour rédiger la réponse : Jarvis ouvre
            # simplement la recherche dans le navigateur.
            query = search_plan["query"] or self.conversation.web.fallback_query(text)
            return self.guarded(request, {"action": "web_search", "params": {"query": query, "engine": "web"}}), None
        if not model_online:
            reply = Reply(
                text=(
                    f"Mes fonctions conversationnelles sont hors ligne, {TITLE} : le modèle « {OLLAMA_MODEL} » "
                    "est introuvable dans Ollama. Lancez ./run_jarvis.sh create pour le rétablir. "
                    "Mes modules (agenda, messagerie, alarmes, poste) restent opérationnels."
                ),
                speech=(
                    f"Mes fonctions conversationnelles sont hors ligne, {TITLE}. "
                    "Mes autres modules restent opérationnels."
                ),
            )
            return response(reply), None

        return None, search_plan or {"text": text, "search": False, "query": None}

    # ── Réponse complète ou en flux ───────────────────────────────────────

    def stream(self, request: ChatRequest) -> Iterator[dict]:
        """Produit la réponse en événements : les phrases du modèle arrivent une à une, puis "final"."""
        answered, plan = self.resolve(request)
        if answered is not None:
            yield {"type": "final", **answered}
            return

        yield {"type": "start", "source": "ollama"}
        sentences: list[str] = []
        data: dict = {}
        pending = None
        start = time.perf_counter()
        first_sentence_ms = None
        # Le modèle termine d'abord une création : on le dit, plutôt que de rester muet.
        occupied = [label for controller in self.controllers for label in controller.occupied_with()]
        if occupied:
            notice = f"Je termine d'abord {occupied[0]}, {TITLE} ; je suis à vous dans un instant."
            yield {"type": "sentence", "text": notice}
        try:
            events = self.conversation.reply(
                request.history,
                plan["text"],
                request.temperature,
                plan,
                offer_browser=self.allows("web_search", request),
            )
            for event in events:
                if event["type"] == "sentence":
                    if first_sentence_ms is None:
                        first_sentence_ms = _elapsed_ms(start)
                    sentences.append(event["text"])
                    yield event
                elif event["type"] == "sources":
                    data = {"sources": event["sources"], "query": event["query"]}
                elif event["type"] == "pending":
                    pending = event["pending"]
                else:
                    yield event
        except Exception as exc:
            if not sentences:
                yield {"type": "final", **self._llm_error(exc)}
                return
            print(f"[LLM] Flux interrompu: {exc}", flush=True)

        print(
            f"[JARVIS] {self.conversation_path}{' + web' if data else ''} › "
            f"1re phrase {first_sentence_ms} ms, réponse {_elapsed_ms(start)} ms",
            flush=True,
        )
        answer = " ".join(([notice] if occupied else []) + sentences)
        yield {
            "type": "final",
            "reply": answer,
            "speech": answer,
            "action": "web_answer" if data else None,
            "source": "web" if data else "ollama",
            "pending": pending,
            "data": data or None,
            "streamed": True,
        }

    def answer(self, request: ChatRequest) -> dict:
        """Réponse d'un seul bloc (clients sans flux, comme Discord)."""
        final: dict = {}
        for event in self.stream(request):
            final = event
        final.pop("type", None)
        final.pop("streamed", None)
        # Sans interface pour les afficher, les sources sont ajoutées au texte.
        found = (final.get("data") or {}).get("sources") or []
        if found:
            final["reply"] += "\nSources : " + ", ".join(source["url"] for source in found)
        return final

    @staticmethod
    def _llm_error(exc: Exception) -> dict:
        print(f"[LLM] Erreur: {exc}", flush=True)
        llm.forget_ollama_status()
        reply = Reply(
            text=f"Je rencontre une difficulté avec mon modèle de langage, {TITLE} : {exc}",
            speech=f"Je rencontre une difficulté avec mon modèle de langage, {TITLE}.",
        )
        return response(reply)
