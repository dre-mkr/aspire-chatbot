"""Handing a conversation to a person, safely."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from app.graph.state import MINOR_BANDS, AspireState
from app.safety import pii
from app.schemas.directives import EscalatedDirective
from app.messages import text_of

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
_ETA: dict[str, str] = {
    "high": "within the hour",
    "normal": "by the end of the next working day",
    "low": "within two working days",
}

#: The reasons a turn escalates, mapped to how urgently a person should see it.
_TRIAGE: dict[str, tuple[Priority, str]] = {
    # The contract (`agents/escalation/contract.py`).
    "safety_or_distress": ("high", "safeguarding"),
    "user_requested_human": ("normal", "general"),
    "account_action_needed": ("high", "servicing"),
    "repeated_failure": ("normal", "comprehension"),
    "complaint": ("high", "complaint"),
    # Pre-contract, for in-flight checkpoints only.
    "safeguarding": ("high", "safeguarding"),
    "distress": ("high", "wellbeing"),
    "user_request": ("normal", "general"),
    "no_context": ("normal", "knowledge_gap"),
    "below_relevance_floor": ("normal", "knowledge_gap"),
    "unattributed_figure": ("normal", "accuracy"),
    "uncited_policy_claim": ("normal", "accuracy"),
    "repeated_clarification": ("normal", "comprehension"),
}


def _is_child(state: AspireState) -> bool:
    """Band alone. This decides who else is TOLD, and never softens."""
    return str(state.get("age_band")) in MINOR_BANDS


def _child_copy(state: AspireState, decision: Triage) -> bool:
    """Whether to write to this reader as a child.

    A signed-out visitor bands as the youngest, because an unknown age has to
    read as the youngest. But the band then chose the WORDING too, and a
    frustrated parent complaining anonymously was told "You have not done
    anything wrong" -- correct for a nine-year-old, wrong for the person who
    was almost certainly there.

    So the reading level and the routing part company. Caps, vocabulary, link
    stripping and games stay at the youngest band for everyone unproven;
    "here is who can help you" assumes an adult may be present when no age was
    ever established.

    Except on safeguarding and wellbeing, where the unknown reader is treated
    as a child regardless. That is what withholds the case number and the SLA
    from someone in distress, and it does not get to depend on whether they
    happened to sign in.
    """
    if not _is_child(state):
        return False
    if decision.category in ("safeguarding", "wellbeing"):
        return True
    return bool(state.get("identity_proven"))


def triage(state: AspireState) -> Triage:
    """How urgent this is, and who else needs to know."""
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

#: Copy per locale, per audience.
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
    if _child_copy(state, decision):
        return _CHILD_MESSAGE.get(locale, _CHILD_MESSAGE["en"])
    eta = _ETA_LOCALISED.get(locale, _ETA)[decision.priority]
    return _ADULT_MESSAGE.get(locale, _ADULT_MESSAGE["en"]).format(
        ticket=ticket_id, eta=eta
    )


# ── the nodes ────────────────────────────────────────────────────────────────


def summarise(state: AspireState) -> dict[str, Any]:
    """A redacted account of the conversation, for the ticket."""
    if state.get("escalation_summary"):
        # Whoever escalated has already written one, redacted at the source.
        return {}

    lines: list[str] = []
    for message in (state.get("messages") or [])[-6:]:
        role = {"human": "user", "ai": "assistant"}.get(
            getattr(message, "type", ""), "system"
        )
        text = text_of(message).strip()
        if text:
            lines.append(f"{role}: {pii.redact_for_summary(text)}")

    return {"escalation_summary": "\n".join(lines)[:4000]}


def make_open_ticket(persist=None):
    """Create the ticket."""

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

        # Asserted rather than assumed.
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
    """Say what happened and what happens next."""
    decision = triage(state)
    ticket_id = str(state.get("escalation_ticket") or "")

    # `user_message` withholds the reference and the wait from a child on purpose.
    # The directive renders both right under that copy, so it has to withhold them
    # too -- a distressed child was being handed a case number and an SLA.
    if _child_copy(state, decision):
        directive = EscalatedDirective(ticket_id="", eta="")
    else:
        directive = EscalatedDirective(
            ticket_id=ticket_id,
            eta=_ETA_LOCALISED.get(str(state.get("locale") or "en"), _ETA)[
                decision.priority
            ],
        )

    return {
        "messages": [AIMessage(content=user_message(state, ticket_id, decision))],
        "ui_directives": [directive],
        "quick_replies": _chips(state, decision),
        "active_agent": "escalate_agent",
    }


def _chips(state: AspireState, decision: Triage) -> list[str]:
    """Somewhere to go next, so the escalation is not a dead end."""
    locale = str(state.get("locale") or "en")
    if _child_copy(state, decision):
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
