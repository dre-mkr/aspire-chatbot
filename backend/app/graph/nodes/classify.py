"""Which agent answers this turn. A small model, a short list, and a bias.

The classifier is deliberately the least powerful component in the graph. It
receives the names and one-line descriptions of the agents `guard` decided this
caller may reach, and nothing else. It does not see the persona, the age band,
the account status, or the access matrix -- so a successful prompt injection
against it can at worst move the turn between agents this caller was already
entitled to.

That containment is the design. Everything else here is tuning.

## Stickiness, and why it is not symmetric

A conversation with an `active_agent` stays in it unless the classifier
proposes something else *and* is confident about it. The threshold is 0.75 by
default and it applies only to the leave case: staying is free, leaving costs
0.75 of confidence.

The asymmetry is not caution for its own sake. Mid-registration, a parent
answering "March" to "what month was she born?" is a one-word turn with no
registration vocabulary in it -- to a classifier looking at that message alone,
it is not obviously about registration at all. Mid-lesson, "I don't know" is
the same shape. If an ambiguous turn could yank the conversation, the two
longest and most valuable flows in the product would be the two most fragile.

The escape hatch is that "help me, I want a person" is not an ambiguous turn.
It scores high, it clears the threshold, and it leaves.

## Why not a bigger model

Routing between at most six known names is a short-context classification job.
A frontier model would put a second expensive call in front of every turn, and
`tests/graph/test_classify.py` measures whether the small one is good enough
against a labelled set rather than assuming either way.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from app.config import get_settings
from app.graph.state import AspireState

logger = logging.getLogger(__name__)

#: One line each. This is the entire description the classifier receives, and
#: it is written for a small model: what the agent is FOR, and the shape of a
#: message that belongs to it.
#:
#: Kept short on purpose. A paragraph per agent is 600 tokens on every turn and
#: measurably increases the rate at which a small model talks itself into the
#: most elaborately described option.
AGENT_DESCRIPTIONS: dict[str, str] = {
    "learn_agent": (
        "Teaching a money lesson step by step: explaining, asking a check "
        "question, playing a learning game, or continuing a lesson already "
        "under way."
    ),
    "learning_preview": (
        "A guardian looking at what their child is being taught, rather than "
        "being taught themselves."
    ),
    "learning_sample": (
        "A signed-out visitor trying a short taste of a lesson."
    ),
    "qa_agent": (
        "Answering a factual question about ASPIRE from the knowledge base: "
        "eligibility, documents, deadlines, branches, how the programme works."
    ),
    "qa_agent_limited": (
        "The same factual questions, for a younger reader, over the part of the "
        "knowledge base that is written for them."
    ),
    "qa_agent_public": (
        "The same factual questions, for a signed-out visitor, over public "
        "information only."
    ),
    "register_agent": (
        "Filling in an ASPIRE application: collecting a guardian's and a "
        "child's details, uploading documents, reviewing and submitting."
    ),
    "register_agent_step1": (
        "Starting an application before signing in -- the first few questions "
        "only."
    ),
    "servicing_agent": (
        "Something about an account that already exists: balance, statements, "
        "changing details, a payment that has not arrived."
    ),
    "escalate_agent": (
        "The person needs a human: they asked for one, they are upset or in "
        "difficulty, or the question is outside what this assistant can answer."
    ),
}

_SYSTEM = (
    "You route one message to one handler. Choose from the list you are given "
    "and nothing else. Reply with JSON only: "
    '{"agent": "<name from the list>", "confidence": <0.0-1.0>, "reason": '
    '"<six words or fewer>"}. '
    "Confidence is how sure you are that the message belongs to that handler "
    "rather than another one on the list. Use a value below 0.5 when the "
    "message is short, ambiguous, or could belong to two of them."
)


class Classification(BaseModel):
    """What the classifier returns, after validation.

    `agent` is guaranteed to be in `allowed_agents` by the time this leaves
    `classify` -- see `_coerce`. It is not guaranteed to be what the model said.
    """

    agent: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    #: True when the model's choice was discarded. Recorded rather than logged
    #: only, because the *rate* is the number that says whether the prompt needs
    #: work, and a rate needs a counter rather than a grep.
    coerced: bool = False
    #: True when stickiness kept the turn in `active_agent` against a differing
    #: proposal.
    sticky: bool = False


def agent_menu(allowed: list[str]) -> str:
    """The list the classifier is shown. Only agents the guard permitted.

    An agent with no description is listed by name alone rather than dropped.
    Dropping it would make a permitted agent unreachable, which is a silent
    capability loss; listing it bare is merely a worse description.
    """
    lines = []
    for agent in allowed:
        description = AGENT_DESCRIPTIONS.get(agent, "")
        lines.append(f"- {agent}: {description}" if description else f"- {agent}")
    return "\n".join(lines)


def _parse(raw: str) -> tuple[str, float, str] | None:
    """Read the model's JSON, tolerating the wrappers small models add.

    A fenced block, a leading "Here is the JSON:", a trailing full stop -- all
    of them happen, and none of them is worth a retry. The first `{...}` in the
    string is taken.
    """
    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    agent = str(data.get("agent") or "").strip()
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    return agent, max(0.0, min(1.0, confidence)), str(data.get("reason") or "")[:120]


def _coerce(
    proposed: str, confidence: float, reason: str, state: AspireState
) -> Classification:
    """Turn the model's answer into a decision that is certainly permitted.

    Three rungs, in order:

      1. The proposal, if it is on the allowed list.
      2. `active_agent`, if it is still allowed -- an ongoing flow beats a
         hallucinated name.
      3. The first allowed agent, which the matrix rows order deliberately:
         `learn_agent` for a child, `qa_agent` for an adult, and the anonymous
         row leads with public Q&A. Never `escalate_agent`, which sits last in
         every row precisely so that a fallback does not open a ticket.
    """
    allowed = list(state.get("allowed_agents") or [])
    active = state.get("active_agent")

    if proposed in allowed:
        return Classification(agent=proposed, confidence=confidence, reason=reason)

    if proposed:
        # WARNING: a name outside the list is either a hallucination or an
        # attempt, and the rate of it is worth watching. The name is logged
        # because it is a bounded, model-produced token rather than free user
        # text -- and knowing WHICH name a small model invents is how the
        # description that invites it gets fixed.
        logger.warning(
            "Classifier proposed %r for session %s, which is not in %s; coercing.",
            proposed[:40],
            state.get("session_id"),
            allowed,
        )

    if active in allowed:
        return Classification(
            agent=str(active), confidence=confidence, reason=reason, coerced=True
        )
    return Classification(
        agent=allowed[0], confidence=confidence, reason=reason, coerced=True
    )


def apply_stickiness(decision: Classification, state: AspireState) -> Classification:
    """Keep an ongoing flow unless the proposal clears the threshold.

    Only applies when there IS an active agent, when it is still allowed, and
    when the proposal differs from it. Note the threshold is compared against
    `>`, not `>=`: a model that emits exactly 0.75 for everything -- which small
    models do -- should not thereby defeat the mechanism.
    """
    active = state.get("active_agent")
    if not active or active not in (state.get("allowed_agents") or []):
        return decision
    if decision.agent == active:
        return decision

    threshold = get_settings().classifier_stickiness_threshold
    if decision.confidence > threshold:
        return decision

    logger.info(
        "Staying in %s for session %s: %s proposed at %.2f, below the %.2f "
        "stickiness threshold.",
        active,
        state.get("session_id"),
        decision.agent,
        decision.confidence,
        threshold,
    )
    return Classification(
        agent=str(active),
        confidence=decision.confidence,
        reason=decision.reason,
        sticky=True,
    )


def resolve_classifier_model() -> str:
    """Which model actually runs the router here.

    `CLASSIFIER_MODEL` names a Haiku-class model, and the default names one from
    Anthropic. A deployment configured only for OpenAI would then have a router
    it cannot call -- and the failure would arrive as an authentication error on
    the first turn, which reads as "the assistant is down".

    So: if the configured classifier's provider has no key, fall back to the
    deployment's own `chat_model` and say so once. That is a worse trade than a
    small model (it is the answer model, and it costs answer-model money for a
    routing decision) and a much better one than a router that does not run.
    The right fix in that deployment is to set `CLASSIFIER_MODEL` to a small
    model of its own provider; the log line says which.
    """
    settings = get_settings()
    configured = settings.classifier_model
    provider = configured.split(":", 1)[0].lower()

    has_key = {
        "anthropic": bool(settings.anthropic_api_key),
        "openai": bool(settings.openai_api_key),
    }.get(provider)

    if has_key is False:
        logger.warning(
            "CLASSIFIER_MODEL is %r but there is no %s key; routing will use "
            "CHAT_MODEL (%s) instead. Set CLASSIFIER_MODEL to a small model of "
            "your own provider -- routing does not need the answer model.",
            configured,
            provider,
            settings.chat_model,
        )
        return settings.chat_model
    return configured


def build_classifier_model():
    """The Haiku-class model this node uses.

    Separate from `agent.build_chat_model` and configured by its own setting, so
    that swapping the answer model cannot silently re-tune the router. Built
    lazily and cached by the caller rather than at import, so a process with no
    API key can still import this module -- the tests do.
    """
    from langchain.chat_models import init_chat_model

    settings = get_settings()
    chosen = resolve_classifier_model()
    kwargs: dict[str, Any] = {}
    # Zero temperature where the provider accepts it. Routing is not a place
    # for variety: the same message on two turns should route the same way.
    # The GPT-5 family rejects any temperature but its own default and errors on
    # the request, so it is omitted there -- the same rule `agent.py` follows.
    if not chosen.startswith("openai:gpt-5"):
        kwargs["temperature"] = settings.classifier_temperature
    return init_chat_model(chosen, **kwargs)


#: State flags that mean "this turn is a reply to something an agent showed".
#:
#: Each is written by the client through its own endpoint and lands on
#: `safety_flags` rather than in `messages` -- putting them in the transcript
#: would have the model read `widget_interaction {...}` back as dialogue on
#: every later turn.
CONTINUATION_FLAGS: tuple[str, ...] = ("widget_interaction", "game_result")

#: Where a continuation goes when the checkpoint has no active agent to resume
#: -- a restarted process, an expired thread.
#:
#: Three names rather than one, because the learning agent has three forms and
#: which of them a caller may reach is exactly what the access matrix decides:
#: `learn_agent` for an account holder, `learning_sample` for an anonymous
#: visitor, `learning_preview` for a guardian looking in. A single `learn_agent`
#: fallback was tried and sent every anonymous interaction to the router, which
#: had an empty message to work with and escalated it.
#:
#: Tried in order and filtered against `allowed`, so this never reaches past the
#: matrix. If none is granted, the continuation falls through to the ordinary
#: router rather than inventing a route.
CONTINUATION_FALLBACKS: tuple[str, ...] = (
    "learn_agent",
    "learning_sample",
    "learning_preview",
)


def _continues_an_agent(state: AspireState, allowed: list[str]) -> str | None:
    """The agent this continuation belongs to, or None if it is not one.

    Returns None rather than raising for a flag whose agent is not allowed: the
    access matrix is the authority, and a continuation is not a reason to reach
    past it. The turn then goes through the ordinary router, which will do
    something sensible with an empty message.
    """
    flags = state.get("safety_flags") or {}
    if not any(flags.get(name) for name in CONTINUATION_FLAGS):
        return None

    active = state.get("active_agent")
    if active in allowed:
        return str(active)
    for fallback in CONTINUATION_FALLBACKS:
        if fallback in allowed:
            return fallback
    logger.warning(
        "A continuation arrived for session %s but neither %r nor any of %s is "
        "allowed; routing it normally.",
        state.get("session_id"),
        active,
        ", ".join(CONTINUATION_FALLBACKS),
    )
    return None


def make_classify(invoke=None):
    """Build the node.

    `invoke` is `async (system, user) -> str`. Injected so the tests and the
    eval harness can drive a recorded transcript, and so this module has no
    import-time dependency on a provider SDK.
    """

    async def classify(state: AspireState) -> dict[str, Any]:
        allowed = list(state.get("allowed_agents") or [])
        if not allowed:
            # `guard` has already halted the turn; reaching here means the graph
            # was wired wrong. Fail closed rather than picking something.
            return {"active_agent": None, "halt_reason": "access_denied"}

        active = state.get("active_agent")

        # ── a reply to something an agent showed, not a new question ────────
        #
        # A widget interaction and a game result arrive on `safety_flags` with
        # NO message -- the child moved a slider or finished a round; they did
        # not say anything. So there is nothing for the router to route on, and
        # the model was being handed an empty string.
        #
        # Measured, before this: an interaction turn escalated to a human. The
        # child got a ticket for using the widget they had just been given.
        #
        # These turns belong to whoever produced the widget, which the
        # checkpoint already records as `active_agent`. Deterministic, and no
        # model call: there is no decision here to make.
        continuation = _continues_an_agent(state, allowed)
        if continuation is not None:
            return {
                "active_agent": continuation,
                "safety_flags": {
                    **(state.get("safety_flags") or {}),
                    "route": {
                        "agent": continuation,
                        "confidence": 1.0,
                        "reason": "continues the agent that showed the widget",
                    },
                },
            }

        if len(allowed) == 1:
            # No decision to make, and therefore no model call to pay for.
            return {
                "active_agent": allowed[0],
                "safety_flags": {
                    **(state.get("safety_flags") or {}),
                    "route": {"agent": allowed[0], "confidence": 1.0, "reason": "only option"},
                },
            }

        message = _latest_user_text(state)
        decision: Classification
        if invoke is None:
            decision = _coerce("", 0.0, "no classifier configured", state)
        else:
            user = (
                f"Handlers:\n{agent_menu(allowed)}\n\n"
                f"Currently handling: {active or 'nothing'}\n\n"
                f"Message: {message}"
            )
            try:
                raw = await invoke(_SYSTEM, user)
            except Exception:
                # A router outage must not be a product outage. Falling back to
                # the active agent, then to the first allowed one, means the
                # turn is still answered by somebody this caller may reach.
                logger.warning(
                    "Classifier call failed for session %s; falling back.",
                    state.get("session_id"),
                    exc_info=True,
                )
                raw = ""
            parsed = _parse(raw)
            if parsed is None:
                decision = _coerce("", 0.0, "unparseable", state)
            else:
                decision = _coerce(*parsed, state)

        decision = apply_stickiness(decision, state)

        # Belt and braces, and worth the two lines: this is the invariant the
        # whole file exists to hold, and it is cheap enough to assert on every
        # turn rather than to trust.
        if decision.agent not in allowed:  # pragma: no cover - unreachable by _coerce
            logger.error(
                "Classifier escaped the allowed list for session %s; forcing %s.",
                state.get("session_id"),
                allowed[0],
            )
            decision = Classification(agent=allowed[0], confidence=0.0, coerced=True)

        _announce(state, decision.agent)
        return {
            "active_agent": decision.agent,
            "safety_flags": {
                **(state.get("safety_flags") or {}),
                "route": decision.model_dump(),
            },
        }

    return classify


def _announce(state: AspireState, agent: str) -> None:
    """Tell the stream interceptor which agent is about to run.

    The interceptor needs the agent, the band and the locale to gate widgets,
    and the only other way to give it them is to subscribe to langgraph's
    `updates` stream mode -- a third mode carrying every state delta of every
    node, for three strings. This is one custom event with no content, emitted
    once a turn.

    Silent when there is no stream writer: the graph is invoked directly by the
    tests and by the eval harness, and neither is streaming.
    """
    try:
        from langgraph.config import get_stream_writer

        get_stream_writer()(
            {
                "meta": {
                    "active_agent": agent,
                    "age_band": state.get("age_band", "5-8"),
                    "locale": state.get("locale", "en"),
                }
            }
        )
    except Exception:
        return


def _latest_user_text(state: AspireState) -> str:
    from app.graph.nodes.safety_in import latest_user_text

    return latest_user_text(state)


async def default_invoke(system: str, user: str) -> str:
    """The real model call, used when the graph is built for production."""
    from langchain_core.messages import HumanMessage, SystemMessage

    model = _cached_model()
    response = await model.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
    content = response.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


_model = None


def _cached_model():
    global _model
    if _model is None:
        _model = build_classifier_model()
    return _model
