"""The top-level graph."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from app.context.resolver import make_resolve_context
from app.graph.nodes.cards import make_intent_gate
from app.graph.nodes.classify import make_classify
from app.graph.nodes.guard import guard
from app.graph.nodes.hydrate import make_hydrate
from app.graph.nodes.safety_in import safety_in
from app.graph.nodes.safety_out import make_safety_out
from app.graph.state import AspireState
from app.safety import pii
from app.messages import text_of

logger = logging.getLogger(__name__)

#: Every agent the access matrix can name.
AGENT_NAMES: tuple[str, ...] = (
    "learn_agent",
    "learning_preview",
    "learning_sample",
    "qa_agent",
    "qa_agent_limited",
    "qa_agent_public",
    "register_agent",
    "register_agent_step1",
    "servicing_agent",
    "escalate_agent",
)


#: What an unbuilt agent says.
_NOT_BUILT: dict[str, str] = {
    "en": (
        "I cannot help with that one here yet. If it is about your account, the "
        "ASPIRE team can sort it out. Is there something about saving or the "
        "programme I can help with instead?"
    ),
    "es": (
        "Todavía no puedo ayudarte con eso aquí. Si es sobre tu cuenta, el equipo "
        "de ASPIRE puede resolverlo. ¿Hay algo sobre ahorro o el programa en lo "
        "que sí pueda ayudarte?"
    ),
    "fr": (
        "Je ne peux pas encore t'aider avec cela ici. Si cela concerne ton compte, "
        "l'équipe ASPIRE peut s'en occuper. Puis-je t'aider avec l'épargne ou le "
        "programme à la place?"
    ),
}


def make_stub(name: str):
    """A placeholder agent, which must not read as a placeholder."""

    async def stub(state: AspireState) -> dict[str, Any]:
        # WARNING, not INFO.
        logger.warning(
            "Stub agent %s handled a turn for session %s; the reader was "
            "deflected. Routing should have excluded it.",
            name,
            state.get("session_id"),
        )
        locale = str(state.get("locale") or "en")
        return {
            "messages": [
                AIMessage(content=_NOT_BUILT.get(locale, _NOT_BUILT["en"]))
            ],
            "active_agent": name,
        }

    return stub


#: Real subgraph builders, by agent name.
AGENT_BUILDERS: dict[str, Callable[[], Any]] = {}


def register_agent(name: str, builder: Callable[[], Any]) -> None:
    """Register a real subgraph for `name`."""
    if name not in AGENT_NAMES:
        raise ValueError(f"{name!r} is not an agent the access matrix can grant")
    AGENT_BUILDERS[name] = builder


def register_all() -> None:
    """Import every agent package so it can register itself."""
    modules = (
        "app.agents.qa.graph",
        "app.agents.escalation.graph",
        "app.agents.learn.graph",
        "app.agents.register.graph",
    )
    for path in modules:
        if any(name in AGENT_BUILDERS for name in _PROVIDES.get(path, ())):
            continue
        try:
            module = __import__(path, fromlist=["register"])
            module.register()
        except Exception:
            logger.warning(
                "Could not register %s; its agents fall back to stubs.",
                path,
                exc_info=True,
            )


#: Which agent names each module registers.
_PROVIDES: dict[str, tuple[str, ...]] = {
    "app.agents.qa.graph": ("qa_agent", "qa_agent_limited", "qa_agent_public"),
    "app.agents.escalation.graph": ("escalate_agent",),
    "app.agents.learn.graph": ("learn_agent", "learning_preview", "learning_sample"),
    "app.agents.register.graph": ("register_agent", "register_agent_step1"),
}


def _agent_node(name: str):
    builder = AGENT_BUILDERS.get(name)
    if builder is None:
        return make_stub(name)
    return builder()


# ── persist ──────────────────────────────────────────────────────────────────

#: How many messages the rolling summary keeps verbatim before compressing.
SUMMARY_AFTER_MESSAGES = 12

#: A summariser: `async (existing_summary, redacted_messages) -> new_summary`.
Summariser = Callable[[str, list[str]], Awaitable[str]]


def make_persist(summarise: Summariser | None = None):
    """Build the closing node: telemetry, mastery, and the rolling summary."""

    async def persist(state: AspireState) -> dict[str, Any]:
        update: dict[str, Any] = {}

        messages = state.get("messages", [])
        if summarise is not None and len(messages) > SUMMARY_AFTER_MESSAGES:
            older = messages[:-SUMMARY_AFTER_MESSAGES]
            redacted = [
                pii.redact_for_summary(text_of(message))
                for message in older
                if text_of(message).strip()
            ]
            if redacted:
                try:
                    update["summary"] = await summarise(state.get("summary", ""), redacted)
                except Exception:
                    # A failed summary is a slightly more expensive next turn, not a failed turn.
                    logger.warning(
                        "Summarising session %s failed; keeping the previous summary.",
                        state.get("session_id"),
                        exc_info=True,
                    )

        # Mastery deltas are written by the learning subgraph's `mastery_update` node, not here.
        _publish_turn(state)

        flags = state.get("safety_flags") or {}
        logger.info(
            "turn session=%s agent=%s directives=%d chips=%d flags=%s",
            state.get("session_id"),
            state.get("active_agent"),
            len(state.get("ui_directives") or []),
            len(state.get("quick_replies") or []),
            sorted(key for key in flags if key != "route"),
        )
        return update

    return persist


def _publish_turn(state: AspireState) -> None:
    """Hand the transport what it needs to close the turn."""
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
    except Exception:
        return

    from app.schemas.directives import directive_payload

    directives = []
    for directive in state.get("ui_directives") or []:
        directives.append(
            directive if isinstance(directive, dict) else directive_payload(directive)
        )

    # Every field the panel renders: the only crossing citations make to the wire.
    citations = []
    for citation in state.get("citations") or []:
        citations.append(
            {
                "kb_id": getattr(citation, "kb_id", ""),
                "title": getattr(citation, "title", ""),
                "question": getattr(citation, "question", ""),
                "snippet": getattr(citation, "snippet", ""),
            }
        )

    writer(
        {
            "turn": {
                "active_agent": state.get("active_agent"),
                "speak": bool(state.get("speak", False)),
                "quick_replies": list(state.get("quick_replies") or []),
                "ui_directives": directives,
                "citations": citations,
                "halt_reason": state.get("halt_reason"),
            }
        }
    )


# ── routing ──────────────────────────────────────────────────────────────────


def _after_guard(state: AspireState) -> str:
    """A refused turn skips straight to the outbound gate."""
    return "safety_out" if state.get("halt_reason") else "safety_in"


#: The two inbound safety signals, in the order they are checked.
_SAFETY_FLAGS: tuple[str, ...] = ("safeguarding", "distress")


def safety_signal(state: AspireState) -> str | None:
    """Which inbound safety flag this turn raised, or None."""
    flags = state.get("safety_flags") or {}
    return next((name for name in _SAFETY_FLAGS if flags.get(name)), None)


def _after_safety_in(state: AspireState) -> str:
    """Where a checked message goes: a person, a refusal, or the ordinary path."""
    if safety_signal(state) is not None:
        return "escalate_agent"
    return "safety_out" if state.get("halt_reason") else "resolve_context"


def _after_cards(state: AspireState) -> str:
    """A card turn is finished."""
    flags = state.get("safety_flags") or {}
    # An explicit request for a person, matched deterministically in `cards`.
    if flags.get("asked_for_human"):
        return "escalate_agent"
    if flags.get("card"):
        return "safety_out"
    messages = state.get("messages") or []
    if state.get("quick_replies") and getattr(messages[-1], "type", None) == "ai":
        return "safety_out"
    return "classify"


#: The agents `classify` may route to.
ROUTABLE_AGENTS: tuple[str, ...] = tuple(
    name for name in AGENT_NAMES if name != "escalate_agent"
)


def _to_agent(state: AspireState) -> str:
    agent = state.get("active_agent")
    if agent in ROUTABLE_AGENTS:
        return str(agent)
    # `classify` guarantees this cannot happen.
    logger.error(
        "No routable agent for session %s (active_agent=%r); going straight out.",
        state.get("session_id"),
        agent,
    )
    return "safety_out"


def build_main_graph(
    *,
    token: str | None,
    body: dict[str, Any] | None = None,
    reprompt=None,
    classifier_invoke=None,
    summarise: Summariser | None = None,
    checkpointer: Any | None = None,
):
    """Compile the graph for one request."""
    register_all()
    graph = StateGraph(AspireState)

    graph.add_node("hydrate", make_hydrate(token, body))
    graph.add_node("guard", guard)
    graph.add_node("safety_in", safety_in)
    # Before routing, so `classify` and every agent share one resolved context.
    graph.add_node("resolve_context", make_resolve_context())
    graph.add_node("cards", make_intent_gate())
    graph.add_node("classify", make_classify(classifier_invoke))
    graph.add_node("safety_out", make_safety_out(reprompt))
    graph.add_node("persist", make_persist(summarise))

    for name in AGENT_NAMES:
        # `destinations` declares where a `Command(goto=...)` from this node may land.
        graph.add_node(
            name,
            _agent_node(name),
            destinations=(
                *(peer for peer in AGENT_NAMES if peer != name),
                "safety_out",
            ),
        )

    graph.add_edge(START, "hydrate")
    graph.add_edge("hydrate", "guard")
    graph.add_conditional_edges("guard", _after_guard, ["safety_in", "safety_out"])
    graph.add_conditional_edges(
        "safety_in",
        _after_safety_in,
        ["resolve_context", "safety_out", "escalate_agent"],
    )
    graph.add_edge("resolve_context", "cards")
    graph.add_conditional_edges(
        "cards", _after_cards, ["classify", "safety_out", "escalate_agent"]
    )
    graph.add_conditional_edges(
        "classify", _to_agent, [*ROUTABLE_AGENTS, "safety_out"]
    )

    for name in AGENT_NAMES:
        graph.add_edge(name, "safety_out")

    graph.add_edge("safety_out", "persist")
    graph.add_edge("persist", END)

    return graph.compile(checkpointer=checkpointer)
