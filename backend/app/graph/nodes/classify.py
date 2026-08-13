"""Which agent answers this turn."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from app.config import get_settings
from app.graph.state import AspireState

logger = logging.getLogger(__name__)

#: One line each.
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
}

# `escalate_agent` has no description because `routable()` drops it before the menu is built.

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
    """What the classifier returns, after validation."""

    agent: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    #: True when the model's choice was discarded.
    coerced: bool = False
    #: True when stickiness kept the turn in `active_agent` against a differing proposal.
    sticky: bool = False


#: Agents the router may never select, whatever the access matrix granted.
UNROUTABLE: frozenset[str] = frozenset({"escalate_agent"})

#: Agents the access matrix grants that have no implementation behind them.
UNBUILT: frozenset[str] = frozenset({"servicing_agent"})


def routable(allowed: list[str]) -> list[str]:
    """The granted agents the router may actually choose between."""
    excluded = UNROUTABLE | UNBUILT
    return [agent for agent in allowed if agent not in excluded]


def agent_menu(allowed: list[str]) -> str:
    """The list the classifier is shown."""
    lines = []
    for agent in allowed:
        description = AGENT_DESCRIPTIONS.get(agent, "")
        lines.append(f"- {agent}: {description}" if description else f"- {agent}")
    return "\n".join(lines)


def _parse(raw: str) -> tuple[str, float, str] | None:
    """Read the model's JSON, tolerating the wrappers small models add."""
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
    """Turn the model's answer into a decision that is certainly permitted."""
    allowed = list(state.get("allowed_agents") or [])
    active = state.get("active_agent")

    if proposed in allowed:
        return Classification(agent=proposed, confidence=confidence, reason=reason)

    if proposed:
        # WARNING: a name outside the list is a hallucination or an attempt, and worth watching.
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
    """Keep an ongoing flow unless the proposal clears the threshold."""
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
    """Which model actually runs the router here."""
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
    """The small model this node uses."""
    from langchain.chat_models import init_chat_model

    settings = get_settings()
    chosen = resolve_classifier_model()
    kwargs: dict[str, Any] = {}
    # Zero temperature where the provider accepts it.
    if not chosen.startswith("openai:gpt-5"):
        kwargs["temperature"] = settings.classifier_temperature
    return init_chat_model(chosen, **kwargs)


#: State flags that mean "this turn is a reply to something an agent showed".
CONTINUATION_FLAGS: tuple[str, ...] = ("widget_interaction", "game_result")

#: Where a continuation goes when the checkpoint has no active agent to resume.
CONTINUATION_FALLBACKS: tuple[str, ...] = (
    "learn_agent",
    "learning_sample",
    "learning_preview",
)


def _continues_an_agent(state: AspireState, allowed: list[str]) -> str | None:
    """The agent this continuation belongs to, or None if it is not one."""
    flags = state.get("safety_flags") or {}
    if not any(flags.get(name) for name in CONTINUATION_FLAGS):
        return None

    active = state.get("active_agent")
    if active in allowed and active in CONTINUATION_FALLBACKS:
        return str(active)
    for fallback in CONTINUATION_FALLBACKS:
        if fallback in allowed:
            return fallback
    if active in allowed:
        return str(active)
    logger.warning(
        "A continuation arrived for session %s but neither %r nor any of %s is "
        "allowed; routing it normally.",
        state.get("session_id"),
        active,
        ", ".join(CONTINUATION_FALLBACKS),
    )
    return None


def make_classify(invoke=None):
    """Build the node."""

    async def classify(state: AspireState) -> dict[str, Any]:
        # `routable` drops `escalate_agent`.
        allowed = routable(list(state.get("allowed_agents") or []))
        if not allowed:
            # `guard` has already halted the turn; reaching here means the graph was wired wrong.
            return {"active_agent": None, "halt_reason": "access_denied"}

        active = state.get("active_agent")

        # ── a reply to something an agent showed, not a new question ──
        # A widget interaction or a game result resumes its agent instead of being routed.
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
                # A router outage must not be a product outage.
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

        # Belt and braces: this is the invariant the whole file exists to hold.
        if decision.agent not in allowed:  # pragma: no cover - unreachable by _coerce
            logger.error(
                "Classifier escaped the allowed list for session %s; forcing %s.",
                state.get("session_id"),
                allowed[0],
            )
            decision = Classification(agent=allowed[0], confidence=0.0, coerced=True)

        # The only record of a routing decision. Its ABSENCE is a signal too: the
        # continuation bypass and the single-option shortcut both return above this,
        # so no line means the router was never consulted.
        logger.info(
            "route session=%s agent=%s confidence=%.2f sticky=%s coerced=%s active=%s reason=%r",
            state.get("session_id"),
            decision.agent,
            decision.confidence,
            decision.sticky,
            decision.coerced,
            active,
            decision.reason,
        )

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
    """Tell the stream interceptor which agent is about to run."""
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
