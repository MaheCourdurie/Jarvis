"""Agent traduction : « comment on dit… en anglais ? », « traduis… en espagnol »."""

from __future__ import annotations

from core.agent import Agent, Handler
from persona import Reply, TITLE
from services import llm

PROMPT = (
    "Tu es un traducteur professionnel. Traduis fidèlement le texte en {language}, dans un registre naturel. "
    "Réponds uniquement par la traduction, sans guillemets ni explication."
)


class TranslateAgent(Agent):
    """Traduit un mot, une phrase ou un court texte."""

    name = "traduction"

    def handlers(self) -> dict[str, Handler]:
        return {"translate": self.translate}

    def translate(self, params: dict) -> Reply:
        text = str(params.get("text") or "").strip(" «»\"'")
        language = str(params.get("language") or "anglais").strip()
        if not text:
            return Reply(text=f"Que dois-je traduire, {TITLE} ?")
        try:
            translation = llm.complete(PROMPT.format(language=language), text, 0.2, 400, timeout=60)
        except Exception as exc:
            print(f"[TRADUCTION] {exc}", flush=True)
            return Reply(text=f"Je n'ai pas réussi à traduire, {TITLE}.")
        translation = llm.clean_reply(translation).strip(" «»\"")
        return Reply(
            text=f"En {language} : « {translation} »",
            speech=f"En {language}, {TITLE} : {translation}",
            data={"translation": translation, "language": language},
        )
