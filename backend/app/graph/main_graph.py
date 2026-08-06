"""The top-level graph. Every turn goes through it, in the same order.

    hydrate → guard → safety_in → classify → «agent» → safety_out → persist → END

Three properties are worth stating explicitly, because each of them is a
one-line edit away from being lost:

  1. **`safety_out` has no bypass.** Every path -- including the two refusal
     paths, which produce their text in Python and never touch a model --
     arrives at `safety_out`. `persist` has exactly one incoming edge and it
     comes from `safety_out`, so there is no way to reach the end of a turn
     without being gated.

  2. **The agent set is fixed before the classifier runs.** `guard` writes
     `allowed_agents`; `classify` reads it and can only choose from it. An
     agent excluded by the access matrix is not something the router can be
     talked into.

  3. **`cards` runs BEFORE the classifier.** "Can I join?" and "let's play a
     game" are answered by a card, and both are recognised deterministically
     here rather than by a model deciding to call a tool. The position is the
     whole point: the classifier is free to route a request to play at
     `learn_agent` or `escalate_agent`, so a matcher placed after it never runs
     on the turns it exists for. Measured, before it moved -- "let's play a
     game" escalated to a human, and "can we play true or false" started a
     lesson.

     A card turn goes straight to `safety_out`, which has nothing to gate: the
     node emits a directive and no message, so there is no narration beside the
     card to suppress.

  4. **Handoffs are `Command(goto=..., update=...)`.** An agent that decides
     another agent should take over says so as a value, not by mutating shared
     state and hoping. `agents/qa` uses it when a generation is ungrounded;
     `escalate_agent` is where it goes.

## Stubs

Agents that are not built yet are registered as stubs that say so. The wiring
is the deliverable at this stage: a turn should flow end to end and land in the
right place, and swapping a stub for a real subgraph must be one line in
`AGENT_BUILDERS`.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from app.graph.nodes.cards import make_intent_gate
from app.graph.nodes.classify import make_classify
from app.graph.nodes.guard import guard
from app.graph.nodes.hydrate import make_hydrate
from app.graph.nodes.safety_in import safety_in
from app.graph.nodes.safety_out import make_safety_out
from app.graph.state import AspireState
from app.safety import pii

logger = logging.getLogger(__name__)

#: Every agent the access matrix can name. The graph declares a node for each,
#: whether or not it is implemented, so that `classify` can never route to a
#: node that does not exist.
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


def make_stub(name: str):
    """A placeholder agent that says, in the transcript, that it is one.

    Says it as an ordinary assistant message rather than raising, because the
    point of the stub is to prove the wiring: a turn must reach the right node,
    be gated by `safety_out`, and be persisted. An exception would prove none of
    that.
    """

    async def stub(state: AspireState) -> dict[str, Any]:
        logger.info("Stub agent %s handled a turn for session %s.", name, state.get("session_id"))
        return {
            "messages": [
                AIMessage(content=f"[{name} is not built yet.]")
            ],
            "active_agent": name,
        }

    return stub


#: Real subgraph builders, by agent name. Anything absent gets a stub.
#:
#: A dict of *builders* rather than of built graphs: several of these need a
#: checkpointer or a model, and constructing them at import time would mean a
#: process with no API key could not import this module.
AGENT_BUILDERS: dict[str, Callable[[], Any]] = {}


def register_agent(name: str, builder: Callable[[], Any]) -> None:
    """Register a real subgraph for `name`.

    Called from the subgraph modules' own `__init__`, so that adding an agent is
    a change in that agent's package rather than an edit here. Registering an
    unknown name is refused loudly: it would silently create a node nothing can
    route to.
    """
    if name not in AGENT_NAMES:
        raise ValueError(f"{name!r} is not an agent the access matrix can grant")
    AGENT_BUILDERS[name] = builder


def register_all() -> None:
    """Import every agent package so it can register itself.

    Idempotent and lazily called from `build_main_graph`. An import here that
    fails is logged and the agent falls back to its stub, rather than taking the
    whole graph down: a broken registration subgraph must not stop a child from
    reaching a lesson.
    """
    modules = (
        "app.agents.qa.graph",
        "app.agents.escalate.graph",
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


#: Which agent names each module registers. Used only to skip re-importing, so
#: `register_all` is cheap on every request rather than merely idempotent.
_PROVIDES: dict[str, tuple[str, ...]] = {
    "app.agents.qa.graph": ("qa_agent", "qa_agent_limited", "qa_agent_public"),
    "app.agents.escalate.graph": ("escalate_agent",),
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
#: Matches `memory_window_turns`'s intent: enough for the model to hold a
#: thread, few enough that the prompt cost stays linear.
SUMMARY_AFTER_MESSAGES = 12

#: A summariser: `async (existing_summary, redacted_messages) -> new_summary`.
#: Injected for the same reason the re-prompt is -- so the node is testable
#: without a model and so a deployment can choose not to pay for one.
Summariser = Callable[[str, list[str]], Awaitable[str]]


def make_persist(summarise: Summariser | None = None):
    """Build the closing node: telemetry, mastery, and the rolling summary.

    ## Redaction happens BEFORE summarisation, and that ordering is the point

    The summary is fed back into the prompt on every subsequent turn, forever.
    A date of birth that reaches it is a date of birth in every future request
    to the provider. Summarising first and redacting the result would mean the
    value had already been in a model prompt -- which is the exact thing being
    prevented, arrived at one step too late.

    So every message is passed through `pii.redact_for_summary` first, and what
    the summariser sees is `[collected: date_of_birth]`. That preserves the only
    thing the model needs from the fact -- that it is done, and must not be
    asked for again -- and preserves nothing else.
    """

    async def persist(state: AspireState) -> dict[str, Any]:
        update: dict[str, Any] = {}

        messages = state.get("messages", [])
        if summarise is not None and len(messages) > SUMMARY_AFTER_MESSAGES:
            older = messages[:-SUMMARY_AFTER_MESSAGES]
            redacted = [
                pii.redact_for_summary(_text_of(message))
                for message in older
                if _text_of(message).strip()
            ]
            if redacted:
                try:
                    update["summary"] = await summarise(state.get("summary", ""), redacted)
                except Exception:
                    # A failed summary is a slightly more expensive next turn,
                    # not a failed turn. The reader already has their answer.
                    logger.warning(
                        "Summarising session %s failed; keeping the previous summary.",
                        state.get("session_id"),
                        exc_info=True,
                    )

        # Mastery deltas are written by the learning subgraph's `mastery_update`
        # node, against the database, at the point where the evidence exists.
        # They are NOT recomputed here: a second writer for the same rows is how
        # two subsystems come to disagree about what a child has learned.
        #
        # What this node does record is the turn's telemetry, which is the shape
        # the eval harness reads.
        # The closing summary, published on the custom stream channel so the
        # transport has it whether or not there is a checkpointer to read state
        # back from. See `StreamInterceptor._on_custom`.
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
    """Hand the transport what it needs to close the turn.

    Silent when nothing is streaming -- the tests and the eval harness invoke
    the graph directly, and neither has a stream writer.

    Directives are dumped to plain JSON here rather than at the transport,
    because this is the last place that knows they are pydantic models: the
    custom channel is a dict channel, and a `Decimal` reaching `json.dumps`
    kills the whole stream on a field nobody was looking at.
    """
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

    citations = []
    for citation in state.get("citations") or []:
        citations.append(
            {
                "kb_id": getattr(citation, "kb_id", ""),
                "title": getattr(citation, "title", ""),
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


# ── routing ──────────────────────────────────────────────────────────────────


def _after_guard(state: AspireState) -> str:
    """A refused turn skips straight to the outbound gate.

    Skipping `safety_in` is safe and deliberate: there is no agent to protect
    from the inbound message, because no agent will run. It does NOT skip
    `safety_out` -- the refusal is still an outbound message to a child and is
    still length-capped and vocabulary-checked like any other.
    """
    return "safety_out" if state.get("halt_reason") else "safety_in"


def _after_safety_in(state: AspireState) -> str:
    return "safety_out" if state.get("halt_reason") else "cards"


def _after_cards(state: AspireState) -> str:
    """A card turn is finished. Anything else goes on to be routed.

    Read from `safety_flags["card"]` rather than from the presence of a
    directive, because a directive is not evidence: a later node attaches
    widgets and progress cards to turns that still owe somebody an answer.

    "Which game would you like?" is the third case. It is a real reply and the
    turn is over, but it is not a card -- recognised by `cards` having produced
    a message, which it otherwise never does.
    """
    if (state.get("safety_flags") or {}).get("card"):
        return "safety_out"
    messages = state.get("messages") or []
    if state.get("quick_replies") and getattr(messages[-1], "type", None) == "ai":
        return "safety_out"
    return "classify"


def _to_agent(state: AspireState) -> str:
    agent = state.get("active_agent")
    if agent in AGENT_NAMES:
        return str(agent)
    # `classify` guarantees this cannot happen. Handled anyway, because the
    # alternative is a KeyError inside langgraph's edge resolution, which names
    # neither this file nor the agent.
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
    """Compile the graph for one request.

    Per-request rather than process-wide, because `hydrate` closes over the
    token. That costs a graph compilation per turn -- microseconds, all local --
    and buys the property that a bearer token is never in `configurable` and so
    is never visible to a tool.
    """
    register_all()
    graph = StateGraph(AspireState)

    graph.add_node("hydrate", make_hydrate(token, body))
    graph.add_node("guard", guard)
    graph.add_node("safety_in", safety_in)
    graph.add_node("cards", make_intent_gate())
    graph.add_node("classify", make_classify(classifier_invoke))
    graph.add_node("safety_out", make_safety_out(reprompt))
    graph.add_node("persist", make_persist(summarise))

    for name in AGENT_NAMES:
        # `destinations` declares where a `Command(goto=...)` from this node may
        # land. Without it langgraph cannot draw the graph and, more usefully,
        # cannot catch a handoff to a node that does not exist.
        graph.add_node(
            name,
            _agent_node(name),
            destinations=("escalate_agent", "register_agent", "safety_out"),
        )

    graph.add_edge(START, "hydrate")
    graph.add_edge("hydrate", "guard")
    graph.add_conditional_edges("guard", _after_guard, ["safety_in", "safety_out"])
    graph.add_conditional_edges("safety_in", _after_safety_in, ["cards", "safety_out"])
    graph.add_conditional_edges("cards", _after_cards, ["classify", "safety_out"])
    graph.add_conditional_edges("classify", _to_agent, [*AGENT_NAMES, "safety_out"])

    for name in AGENT_NAMES:
        graph.add_edge(name, "safety_out")

    graph.add_edge("safety_out", "persist")
    graph.add_edge("persist", END)

    return graph.compile(checkpointer=checkpointer)
