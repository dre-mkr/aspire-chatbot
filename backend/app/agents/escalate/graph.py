"""Handing a conversation to a person, safely.

    summarise → triage → open_ticket → tell_the_user

Four things it must get right, and one thing it must never do.

## Never connect a child to an external channel

A distressed nine-year-old does not get a phone number, an e-mail address or a
live-chat handoff. They get told that a grown-up who helps with ASPIRE will
look at this, and the ticket is raised against the GUARDIAN's record and the
staff queue at high priority. That is the whole rule, and `_is_child` is where
it is decided.

The reason is not squeamishness. An external channel is unmonitored, unlogged
and unbounded -- it is precisely the surface a safeguarding process exists to
avoid, and offering one to a child in difficulty is worse than offering
nothing.

## The summary is redacted before it is written, not after

A ticket is read by staff, exported to a case system and joined to a record.
It is the last place a national ID should end up and the easiest place for one
to arrive unnoticed. `pii.redact_for_summary` runs on the way in, so the ticket
row cannot contain a value even if the conversation did.

## The user is told what happens next, specifically

"Someone will be in touch" is not an answer. A ticket id, a realistic window,
and what to do in the meantime are.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from app.graph.state import MINOR_BANDS, AspireState
from app.safety import pii
from app.schemas.directives import EscalatedDirective, directive_payload

logger = logging.getLogger(__name__)

Priority = Literal["low", "normal", "high"]


@dataclass(frozen=True, slots=True)
class Triage:
    priority: Priority
    category: str
    eta: str
    #: Whether a guardian record must be notified as well as the staff queue.
    notify_guardian: bool


#: How long each priority actually takes, written as a person would say it.
#: These are promises; keeping them shorter than the team can meet is how a
#: support channel loses trust in a fortnight.
_ETA: dict[str, str] = {
    "high": "within the hour",
    "normal": "by the end of the next working day",
    "low": "within two working days",
}

#: The reasons a turn escalates, mapped to how urgently a person should see it.
#:
#: `safeguarding` is the only automatic high, and it is high regardless of who
#: raised it or what else is going on in the conversation.
_TRIAGE: dict[str, tuple[Priority, str]] = {
    "safeguarding": ("high", "safeguarding"),
    "distress": ("high", "wellbeing"),
    "user_request": ("normal", "general"),
    "no_context": ("normal", "knowledge_gap"),
    "below_relevance_floor": ("normal", "knowledge_gap"),
    "unattributed_figure": ("normal", "accuracy"),
    "uncited_policy_claim": ("normal", "accuracy"),
    "repeated_clarification": ("normal", "comprehension"),
    "complaint": ("high", "complaint"),
}

#: Three failed clarifications in a row is an escalation trigger in its own
#: right. A person asked to rephrase three times has been told three times that
#: the assistant cannot help, without being told it.
CLARIFICATION_LIMIT = 3


def _is_child(state: AspireState) -> bool:
    return str(state.get("age_band")) in MINOR_BANDS


def triage(state: AspireState) -> Triage:
    """How urgent this is, and who else needs to know.

    A child's escalation is never routed outward, and a child's escalation for
    a safety reason also notifies the guardian record. Both facts are decided
    here so there is one place to read them.
    """
    flags = state.get("safety_flags") or {}
    reason = str(state.get("escalation_reason") or "user_request")

    if flags.get("safeguarding"):
        reason = "safeguarding"
    elif flags.get("distress"):
        reason = "distress"

    priority, category = _TRIAGE.get(reason, ("normal", "general"))
    return Triage(
        priority=priority,
        category=category,
        eta=_ETA[priority],
        notify_guardian=_is_child(state) and category in ("safeguarding", "wellbeing"),
    )


# ── what the user is told ────────────────────────────────────────────────────

#: Copy per locale, per audience. Children and adults are told different things
#: because different things are true for them: an adult may be contacted
#: directly, a child will not be.
_CHILD_MESSAGE: dict[str, str] = {
    "en": (
        "Thank you for telling me. A grown-up who helps with ASPIRE is going to "
        "look at this. You have not done anything wrong."
    ),
    "es": (
        "Gracias por contármelo. Una persona adulta de ASPIRE va a ver esto. "
        "No has hecho nada malo."
    ),
    "fr": (
        "Merci de me l'avoir dit. Une grande personne d'ASPIRE va regarder cela. "
        "Tu n'as rien fait de mal."
    ),
}

_ADULT_MESSAGE: dict[str, str] = {
    "en": (
        "I have passed this to the ASPIRE team. Your reference is {ticket}, and "
        "someone will come back to you {eta}."
    ),
    "es": (
        "He pasado esto al equipo de ASPIRE. Tu referencia es {ticket} y alguien "
        "te responderá {eta}."
    ),
    "fr": (
        "J'ai transmis cela à l'équipe ASPIRE. Ta référence est {ticket} et "
        "quelqu'un te répondra {eta}."
    ),
}

_ETA_LOCALISED: dict[str, dict[str, str]] = {
    "en": _ETA,
    "es": {
        "high": "en menos de una hora",
        "normal": "antes del final del próximo día hábil",
        "low": "en dos días hábiles",
    },
    "fr": {
        "high": "dans l'heure",
        "normal": "avant la fin du prochain jour ouvrable",
        "low": "sous deux jours ouvrables",
    },
}


def user_message(state: AspireState, ticket_id: str, decision: Triage) -> str:
    """What to say. Never a phone number or an address for a child."""
    locale = str(state.get("locale") or "en")
    if _is_child(state):
        return _CHILD_MESSAGE.get(locale, _CHILD_MESSAGE["en"])
    eta = _ETA_LOCALISED.get(locale, _ETA)[decision.priority]
    return _ADULT_MESSAGE.get(locale, _ADULT_MESSAGE["en"]).format(
        ticket=ticket_id, eta=eta
    )


# ── the nodes ────────────────────────────────────────────────────────────────


def summarise(state: AspireState) -> dict[str, Any]:
    """A redacted account of the conversation, for the ticket.

    Deterministic, and NOT a model call. Two reasons: a summariser is one more
    thing that can fail on a turn that is already failing, and a model asked to
    summarise a distressed child's message will paraphrase it -- which loses the
    words a safeguarding reviewer needs to see.

    So it takes the last few turns verbatim and redacts them. Verbatim and
    redacted is the right combination here: the reviewer sees what was actually
    said, and sees `[collected: phone]` where a number was.
    """
    if state.get("escalation_summary"):
        # Whoever escalated has already written one, redacted at the source.
        return {}

    lines: list[str] = []
    for message in (state.get("messages") or [])[-6:]:
        role = {"human": "user", "ai": "assistant"}.get(
            getattr(message, "type", ""), "system"
        )
        text = _text_of(message).strip()
        if text:
            lines.append(f"{role}: {pii.redact_for_summary(text)}")

    return {"escalation_summary": "\n".join(lines)[:4000]}


def make_open_ticket(persist=None):
    """Create the ticket. `persist` is `async (dict) -> None`.

    Injected so this subgraph runs without a database -- and so that a database
    failure cannot swallow an escalation. The ticket id is minted here, before
    persistence is attempted, so the user is given a reference even when the
    write fails; a support conversation can then find it in the log.
    """

    async def open_ticket(state: AspireState) -> dict[str, Any]:
        decision = triage(state)
        ticket_id = f"ASP-{uuid.uuid4().hex[:8].upper()}"

        row = {
            "id": ticket_id,
            "session_id": state.get("session_id"),
            "user_id": state.get("user_id"),
            "summary": state.get("escalation_summary") or "",
            "priority": decision.priority,
            "category": decision.category,
            "status": "open",
            "notify_guardian": decision.notify_guardian,
            "age_band": state.get("age_band"),
            "locale": state.get("locale"),
        }

        # Asserted rather than assumed. `summarise` and every escalating caller
        # redact, but this is the last point before the value is written to a
        # table that gets exported -- and the cost of the check is a regex pass.
        leaked = pii.kinds_in(row["summary"])
        if leaked:
            logger.error(
                "PII (%s) reached a ticket summary for session %s; redacting again.",
                ", ".join(leaked),
                state.get("session_id"),
            )
            row["summary"] = pii.redact_for_summary(row["summary"])

        if persist is not None:
            try:
                await persist(row)
            except Exception:
                # The reference has already been minted and is about to be shown.
                # Losing the row is our problem; refusing the escalation is the
                # user's, and they are the one who needs a person.
                logger.exception("Could not persist ticket %s", ticket_id)

        logger.warning(
            "escalation ticket=%s priority=%s category=%s guardian=%s session=%s",
            ticket_id,
            decision.priority,
            decision.category,
            decision.notify_guardian,
            state.get("session_id"),
        )

        return {
            "escalation_ticket": ticket_id,
            "escalation_priority": decision.priority,
        }

    return open_ticket


def tell_the_user(state: AspireState) -> dict[str, Any]:
    """Say what happened and what happens next.

    The `escalated` directive carries the ticket id and the window so the client
    can render them as a card rather than leaving them buried in a sentence --
    a reference number a person has to copy out of prose is a reference number
    they will get wrong.
    """
    decision = triage(state)
    ticket_id = str(state.get("escalation_ticket") or "")

    directive = EscalatedDirective(
        ticket_id=ticket_id,
        eta=_ETA_LOCALISED.get(str(state.get("locale") or "en"), _ETA)[decision.priority],
    )

    return {
        "messages": [AIMessage(content=user_message(state, ticket_id, decision))],
        "ui_directives": [directive],
        "quick_replies": _chips(state),
        "active_agent": "escalate_agent",
    }


def _chips(state: AspireState) -> list[str]:
    """Somewhere to go next, so the escalation is not a dead end."""
    locale = str(state.get("locale") or "en")
    if _is_child(state):
        return {
            "en": ["Okay", "Back to my lesson"],
            "es": ["Vale", "Volver a mi lección"],
            "fr": ["D'accord", "Retour à ma leçon"],
        }.get(locale, ["Okay", "Back to my lesson"])
    return {
        "en": ["Thanks", "Something else"],
        "es": ["Gracias", "Otra cosa"],
        "fr": ["Merci", "Autre chose"],
    }.get(locale, ["Thanks", "Something else"])


def _text_of(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def build_escalate_graph(*, persist=None):
    graph = StateGraph(AspireState)
    graph.add_node("summarise", summarise)
    graph.add_node("open_ticket", make_open_ticket(persist))
    graph.add_node("tell_the_user", tell_the_user)

    graph.add_edge(START, "summarise")
    graph.add_edge("summarise", "open_ticket")
    graph.add_edge("open_ticket", "tell_the_user")
    graph.add_edge("tell_the_user", END)
    return graph.compile()


# ── production wiring ────────────────────────────────────────────────────────


async def _persist(row: dict[str, Any]) -> None:
    from sqlalchemy import text as sql

    from app.db import session

    async with session() as db:
        if db is None:
            return
        await db.execute(
            sql(
                """
                INSERT INTO tickets (
                    id, session_id, user_id, summary, priority, category,
                    status, notify_guardian, age_band, locale
                ) VALUES (
                    :id, :session_id, :user_id, :summary, :priority, :category,
                    :status, :notify_guardian, :age_band, :locale
                )
                ON CONFLICT (id) DO NOTHING
                """
            ),
            row,
        )
        await db.commit()


def build_production_escalate():
    return build_escalate_graph(persist=_persist)


def register() -> None:
    from app.graph.main_graph import register_agent

    register_agent("escalate_agent", build_production_escalate)
