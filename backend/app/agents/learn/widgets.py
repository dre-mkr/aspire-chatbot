"""The widget, built on its own path and unable to touch the lesson."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.learning.concepts import TeachingConcept

logger = logging.getLogger(__name__)

#: Agents whose turns may carry a widget.
WIDGET_AGENTS: frozenset[str] = frozenset(
    {"learn_agent", "learning_preview", "learning_sample"}
)


@dataclass(slots=True)
class WidgetRequest:
    """Everything the widget path may know."""

    concept: TeachingConcept | None
    band: str
    locale: str = "en"
    agent: str = "learn_agent"
    #: Kinds this child has seen recently, so the planner does not repeat itself.
    recent_kinds: tuple[str, ...] = ()
    #: What the learner asked, for the planner only. Never reaches the composer.
    utterance: str = ""


@dataclass(slots=True)
class WidgetOutcome:
    """What the widget path produced, and how."""

    payload: dict[str, Any] | None = None
    kind: str | None = None
    cache_hit: bool = False
    gate: str | None = None
    reason: str = ""
    latency_ms: int = 0

    @property
    def emitted(self) -> bool:
        return self.payload is not None


# ── planning ─────────────────────────────────────────────────────────────────

_PLAN_SYSTEM = """You choose at most ONE interactive widget to accompany a lesson, or none.

Reply with JSON only: {"kind": "<one of the allowed kinds>", "rationale": "<six words>"}
or {"kind": "none", "rationale": "<six words>"}.

"none" is the right answer most of the time and you should reach for it freely. A widget
earns its place only when MOVING something teaches what words cannot: watching a stack
grow, comparing two choices side by side, splitting an amount into buckets. A widget that
merely restates the lesson is an interruption, and a widget that implies a relationship
the lesson did not teach is worse than no widget at all.

Choose from the allowed kinds and nothing else."""


async def plan_widget(request: WidgetRequest, invoke: Any) -> str | None:
    """Which primitive, or None."""
    if invoke is None or request.concept is None:
        return None

    from app.widgets.validate import BAND_KINDS

    permitted = BAND_KINDS.get(request.band, frozenset())
    hints = set(request.concept.widget_hints) or set(permitted)
    allowed = sorted((hints & permitted) - set(request.recent_kinds))
    if not allowed:
        # Everything this concept offers has just been shown, or the band permits none of it.
        return None

    try:
        answer = await invoke(
            system=_PLAN_SYSTEM,
            user=(
                f"CONCEPT: {request.concept.title}\n"
                f"Learner band: {request.band}. Language: {request.locale}.\n"
                f"What they asked: {request.utterance or request.concept.title}\n"
                f"Allowed kinds: {', '.join(allowed)}, none"
            ),
        )
    except Exception:
        logger.info("Widget planning failed; the lesson continues without one.", exc_info=True)
        return None

    if not isinstance(answer, dict):
        return None
    kind = str(answer.get("kind") or "none").strip()
    if kind in allowed:
        logger.debug("Widget plan: %s (%s)", kind, answer.get("rationale"))
        return kind
    return None


def plan_hash(request: WidgetRequest, kind: str) -> str:
    """The cache key's variable part."""
    anchors = json.dumps(
        (request.concept.numeric_anchors if request.concept else {}), sort_keys=True
    )
    material = f"{request.concept.id if request.concept else ''}|{kind}|{request.band}|{request.locale}|{anchors}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


# ── composition ──────────────────────────────────────────────────────────────


async def compose_widget(request: WidgetRequest, kind: str, invoke: Any) -> str | None:
    """The chosen primitive's JSON."""
    if invoke is None or request.concept is None:
        return None

    from app.widgets.planner import composition_prompt

    prompt = composition_prompt(kind, request.band, request.locale, request.concept.id)
    prompt = _strip_sentinel_instruction(prompt)

    anchors = request.concept.numeric_anchors or {}
    user = (
        f"Concept: {request.concept.title} (id {request.concept.id})\n"
        f"Language: {request.locale}. Every user-visible string must be in it.\n"
        + (
            f"Use exactly these numbers and compute nothing new: "
            f"{json.dumps(anchors, ensure_ascii=False)}\n"
            if anchors
            else ""
        )
        + (f"The lesson's example: {request.concept.local_example}\n" if request.concept.local_example else "")
        + "\nReturn ONLY the widget JSON object. No prose, no markers, no code fence."
    )

    try:
        return await invoke(system=prompt, user=user)
    except Exception:
        logger.info("Widget composition failed; the lesson continues.", exc_info=True)
        return None


#: The old inline instruction, removed from the composition prompt.
_SENTINEL_LINE = re.compile(
    r"Emit ONE (\w+) widget as JSON inside .*?, inline in\s*your reply, at the point it helps\.",
    re.DOTALL,
)


def _strip_sentinel_instruction(prompt: str) -> str:
    return _SENTINEL_LINE.sub(
        r"Emit ONE \1 widget as a JSON object. Return the object and nothing else.",
        prompt,
    )


# ── gates 8 and 9 ────────────────────────────────────────────────────────────

#: Characters that betray the wrong language when the alphabet is shared.
_ENGLISH_TELLS = re.compile(
    r"\b(?:the|your|you|and|of|with|save|saving|money|week|year|total|each|per)\b",
    re.IGNORECASE,
)
_ACCENTED = re.compile(r"[áéíóúñüàâçèêëîïôûùœ]", re.IGNORECASE)


def gate_locale(widget: Any, locale: str) -> tuple[bool, str]:
    """Every user-visible string is in this turn's language."""
    if locale == "en":
        return True, ""

    from app.widgets.validate import _strings

    texts = [text for _, text, _ in _strings(widget) if len(text.split()) >= 2]
    if not texts:
        return True, ""

    joined = " ".join(texts)
    if _ACCENTED.search(joined):
        return True, ""
    english_hits = len(_ENGLISH_TELLS.findall(joined))
    if english_hits >= 2:
        return False, f"labels read as English in a {locale} turn ({english_hits} tells)"
    return True, ""


def gate_provenance(
    widget: Any, *, concept: TeachingConcept | None, agent: str
) -> tuple[bool, str]:
    """This widget came from the learning agent, about this concept, in a permitted form."""
    if agent not in WIDGET_AGENTS:
        return False, f"{agent!r} may not emit widgets"
    if concept is None:
        return False, "no concept for this widget"
    if not getattr(widget, "concept_id", ""):
        return False, "widget carries no concept_id"

    hints = set(concept.widget_hints)
    if hints and widget.kind not in hints:
        return False, f"{widget.kind} is not among {concept.slug}'s permitted kinds"
    return True, ""


# ── the pipeline ─────────────────────────────────────────────────────────────


async def build_widget(
    request: WidgetRequest,
    *,
    plan: Any = None,
    compose: Any = None,
    cache: Any = None,
) -> WidgetOutcome:
    """Plan, compose, gate, cache."""
    import time

    started = time.monotonic()

    def elapsed() -> int:
        return int((time.monotonic() - started) * 1000)

    try:
        outcome = await _build(request, plan=plan, compose=compose, cache=cache)
        outcome.latency_ms = elapsed()
        return outcome
    except asyncio.CancelledError:
        # The prose path timed out waiting and cancelled this task.
        raise
    except Exception:
        logger.warning(
            "The widget pipeline raised for concept %s; serving prose alone.",
            request.concept.id if request.concept else None,
            exc_info=True,
        )
        return WidgetOutcome(gate="exception", reason="unhandled", latency_ms=elapsed())


async def _build(
    request: WidgetRequest, *, plan: Any, compose: Any, cache: Any
) -> WidgetOutcome:
    if request.concept is None:
        return WidgetOutcome(gate="provenance", reason="no concept resolved")
    if request.agent not in WIDGET_AGENTS:
        return WidgetOutcome(gate="provenance", reason=f"{request.agent} may not emit widgets")

    kind = await plan_widget(request, plan)
    if not kind:
        return WidgetOutcome(reason="planner chose none")

    key = plan_hash(request, kind)

    # Checked before composition, so a hit skips the compose call entirely.
    if cache is not None:
        try:
            hit = await cache.get(request.concept.id, request.band, request.locale, key)
        except Exception:
            hit = None
            logger.debug("Widget cache read failed.", exc_info=True)
        if hit:
            return WidgetOutcome(payload=hit, kind=kind, cache_hit=True)

    raw = await compose_widget(request, kind, compose)
    if not raw:
        return WidgetOutcome(kind=kind, gate="compose", reason="no composition returned")

    outcome = validate(raw, request=request, kind=kind)
    if outcome.emitted and cache is not None:
        try:
            await cache.put(request.concept.id, request.band, request.locale, key, outcome.payload)
        except Exception:
            logger.debug("Widget cache write failed.", exc_info=True)
    return outcome


def validate(raw: str, *, request: WidgetRequest, kind: str | None = None) -> WidgetOutcome:
    """Nine gates."""
    from app.widgets.validate import validate_widget
    from app.schemas.directives import WidgetDirective, directive_payload

    text = _unfence(raw)
    result = validate_widget(text, age_band=request.band, locale=request.locale)
    if not result.ok:
        logger.info("Widget dropped at gate %s: %s", result.gate, result.reason)
        return WidgetOutcome(kind=kind, gate=result.gate, reason=result.reason)

    widget = result.widget

    ok, reason = gate_locale(widget, request.locale)
    if not ok:
        logger.info("Widget dropped at gate locale: %s", reason)
        return WidgetOutcome(kind=kind, gate="locale", reason=reason)

    ok, reason = gate_provenance(widget, concept=request.concept, agent=request.agent)
    if not ok:
        logger.info("Widget dropped at gate provenance: %s", reason)
        return WidgetOutcome(kind=kind, gate="provenance", reason=reason)

    return WidgetOutcome(
        payload=directive_payload(WidgetDirective(payload=widget)),
        kind=getattr(widget, "kind", kind),
    )


_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def _unfence(raw: str) -> str:
    """Strip a code fence the composer wrapped its JSON in."""
    match = _FENCE.match(raw or "")
    return (match.group(1) if match else (raw or "")).strip()


# ── the cache ────────────────────────────────────────────────────────────────


class WidgetCache:
    """Valkey, keyed by concept, band, locale and the plan hash."""

    def __init__(self, ttl_days: int | None = None) -> None:
        self._ttl_days = ttl_days

    def _key(self, concept_id: str, band: str, locale: str, plan: str) -> str:
        return f"widget:{concept_id}:{band}:{locale}:{plan}"

    async def get(
        self, concept_id: str, band: str, locale: str, plan: str
    ) -> dict[str, Any] | None:
        client = await _valkey()
        if client is None:
            return None
        raw = await client.get(self._key(concept_id, band, locale, plan))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    async def put(
        self, concept_id: str, band: str, locale: str, plan: str, payload: Any
    ) -> None:
        client = await _valkey()
        if client is None:
            return
        from app.config import get_settings

        ttl = (self._ttl_days or get_settings().learn_widget_cache_ttl_days) * 86400
        await client.set(
            self._key(concept_id, band, locale, plan),
            json.dumps(payload, ensure_ascii=False),
            ex=ttl,
        )


async def _valkey() -> Any:
    """The shared Valkey client, or None when the cache is not configured."""
    try:
        from app.cache import get_client

        return get_client()
    except Exception:
        return None
