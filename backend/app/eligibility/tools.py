"""The agent's only route into the eligibility flow.

One tool, and it does one thing: put the card on screen. Everything after that
happens between the card and `app.eligibility.router`, which is what keeps the
answers out of the model entirely — an age band tapped into this card never
enters a prompt, never reaches the checkpointer, and never reaches the summary
job.

The tool description is prompt text, not documentation: the agent reasons over
it when deciding whether to call, so it is written for the model. The trigger
breadth in it is deliberate — "am I too old", "can I join", "¿puedo participar?"
and "suis-je trop âgé" are the same question, and someone asking it in French
should not get prose while an English speaker gets the flow.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.eligibility.engine import EligibilityError, get_engine
from app.eligibility.models import Language

logger = logging.getLogger(__name__)


def _session_id(config: RunnableConfig) -> str:
    """The conversation's thread id, set by /chat. Never model-supplied."""
    session_id = (config.get("configurable") or {}).get("thread_id")
    if not session_id:
        raise EligibilityError("This conversation has no session to attach a check to.")
    return str(session_id)


def _language(value: str | None, config: RunnableConfig) -> Language:
    raw = value or (config.get("configurable") or {}).get("language") or "en"
    try:
        return Language(str(raw).lower())
    except ValueError:
        return Language.EN


@tool
def start_eligibility_check(
    config: RunnableConfig, language: str | None = None
) -> dict[str, Any]:
    """Start the guided ASPIRE eligibility check. Call this INSTEAD of answering.

    Call it whenever someone asks whether they, or a child, can join ASPIRE, or
    what they need in order to apply. All of these are the same question:

      "Who is eligible for ASPIRE?"        "Am I eligible?"
      "Can I join?"                        "Can my son sign up?"
      "Am I too old?"  "Am I too young?"   "Do I qualify?"
      "How can I apply?"                   "How do I sign up?"
      "What do I need to apply?"           "What documents do I need?"
      "¿Quién puede participar?"           "¿Puedo inscribirme?"
      "¿Soy demasiado mayor?"              "¿Cómo me inscribo?"
      "Qui peut participer ?"              "Puis-je m'inscrire ?"
      "Suis-je trop âgé ?"                 "Comment s'inscrire ?"

    Prefer the check over prose. Six tapped questions give a personalised
    answer with the right document list; a paragraph gives everyone the same one
    and leaves them to work out which parts apply to them.

    ON SUCCESS, REPLY WITH NOTHING. The card already shows the first question,
    the progress and the controls, so any sentence you add is a second copy of
    what is on screen. Do not greet, do not introduce it, and do not preview the
    questions. An empty reply is the correct reply and the only correct one.

    Do NOT answer the eligibility question yourself alongside this, and do not
    state any rule about age, citizenship, residency or school in the same turn.
    The card holds the audited rules; anything you add is unaudited.

    If it DECLINES there is no card, so answer the question normally, from the
    knowledge base:
      already_running - a check is already open in this conversation

    A question about ONE detail ("what is the minimum age?", "does Nevis
    count?") is an ordinary question and gets an ordinary searched answer. This
    is for someone working out whether they can join, not for a lookup.
    """
    try:
        get_engine().start(_session_id(config), _language(language, config))
    except EligibilityError as error:
        return {"ok": False, "reason": error.reason, "detail": str(error)}

    return {
        "ok": True,
        "started": True,
        # Enough for /chat to build the history line and for the client to open
        # the card. Deliberately not the question text: the card renders that,
        # and putting it here would invite the model to read it out.
        "check": "aspire_eligibility",
    }


ELIGIBILITY_TOOLS = [start_eligibility_check]
