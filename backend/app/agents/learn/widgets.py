"""The widget, built on its own path and unable to touch the lesson.

    prose_task  ─────────────────────────► validated prose ─► emitted
    widget_task ─► plan ─► compose ─► 9 gates ─► cache ─────► emitted AFTER

Both tasks start at the same instant. The prose is emitted the moment it is
validated; the widget is awaited afterwards, with a timeout, inside a catch-all
that can only ever produce `None`.

## What this replaces, and why the replacement is the fix

The widget used to be composed by the SAME model call that wrote the lesson, as
JSON between `⟦widget⟧` markers inline in the prose. Three things followed, and
each of them destroys a lesson on its own:

  * the widget's few hundred characters of JSON and the lesson's word budget came
    out of one generation, so the model traded prose away to fit the widget;
  * the transport stopped forwarding tokens at the opening marker
    (`graph/stream_interceptor.py`), so a widget opened early meant almost no
    lesson reached the reader before the stream went quiet;
  * an unterminated marker caused the buffer to be DISCARDED, taking every token
    after it with it -- a malformed widget silently truncated the lesson.

None of that is reachable from here. `build_widget` returns a validated config or
None, the prose was already emitted before it is awaited, and there is no path by
which a widget failure can subtract a word from a lesson. `tests/learning/
test_prose_survives_widgets.py` is the regression test and it fails if that ever
stops being true.

## `none` is a good plan

The planner is pushed hard towards returning no widget. Most lessons do not need
one, an unnecessary widget is an interruption, and a *bad* widget is worse than
none -- a child who moves a slider and learns the wrong relationship has been
taught something false by a thing that looked authoritative.

## Two gates beyond the seven

`widgets/validate.py` runs seven gates that check the widget against the band and
the formula registry. Two more belong here rather than there, because they are
about the TURN rather than about the widget:

  LOCALE      every user-visible string is in this turn's language. A Spanish
              lesson with English slider labels is two products in one message.
  PROVENANCE  the emitting agent is a learning agent, the concept id is present,
              and the kind is one the concept actually permits. A widget arriving
              from anywhere else is dropped unconditionally -- the widget system
              is a teaching device with a curriculum behind it.
"""

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

#: Agents whose turns may carry a widget. Mirrors
#: `stream_interceptor.WIDGET_AGENTS` -- one list, two enforcement points, and
#: the transport keeps its copy because it is the last line before the wire.
WIDGET_AGENTS: frozenset[str] = frozenset(
    {"learn_agent", "learning_preview", "learning_sample"}
)


@dataclass(slots=True)
class WidgetRequest:
    """Everything the widget path may know. Deliberately no message history.

    A widget is composed from a concept, a band and a set of numbers. Handing the
    composer the conversation would let it compose about something the lesson did
    not teach, and the reader would have no way to tell.
    """

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
    """What the widget path produced, and how. Every field is logged.

    `gate` naming the failing gate is the whole feedback loop: "gate copy fired
    40 times this week" is something to fix, and "the widget was dropped" is not.
    """

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
    """Which primitive, or None. One cheap structured call over a short menu.

    The menu is the intersection of what the concept's author permitted
    (`widget_hints`) and what the band is allowed to receive (`BAND_KINDS`).
    Intersecting BEFORE the call rather than validating after it is what stops
    the planner proposing a simulator for a six-year-old and the band gate
    rejecting it a second later -- two calls' worth of latency for a decision
    that was knowable up front.
    """
    if invoke is None or request.concept is None:
        return None

    from app.widgets.validate import BAND_KINDS

    permitted = BAND_KINDS.get(request.band, frozenset())
    hints = set(request.concept.widget_hints) or set(permitted)
    allowed = sorted((hints & permitted) - set(request.recent_kinds))
    if not allowed:
        # Everything this concept offers has just been shown, or the band permits
        # none of it. Not a failure: the lesson is complete without one.
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
    """The cache key's variable part.

    Over the inputs a composition actually depends on -- concept, kind, band,
    locale and the numbers -- and NOT over the utterance. Two children asking
    "how does saving grow?" and "why does my money get bigger?" about the same
    concept want the same growth stack, and keying on their words would compose
    it twice and cache neither usefully.
    """
    anchors = json.dumps(
        (request.concept.numeric_anchors if request.concept else {}), sort_keys=True
    )
    material = f"{request.concept.id if request.concept else ''}|{kind}|{request.band}|{request.locale}|{anchors}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


# ── composition ──────────────────────────────────────────────────────────────


async def compose_widget(request: WidgetRequest, kind: str, invoke: Any) -> str | None:
    """The chosen primitive's JSON. One schema in the prompt, never nine.

    Reuses `widgets/planner.composition_prompt`, minus the sentinel instruction --
    the composer now returns JSON as its whole reply rather than embedding it in
    prose, which is the change that decouples it from the lesson.
    """
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
#:
#: `composition_prompt` still carries it because the prompt is shared with the
#: legacy path during the transition. Stripped here rather than edited there so
#: that turning the legacy path off is a deletion rather than a rewrite.
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
#:
#: Locale detection on a slider label is not the stopword problem `safety_out`
#: solves -- there are three words and no function words among them. So the test
#: is the one signal that IS available at that length: a Spanish or French
#: config with no accented character and an English function word in it was
#: composed in English.
_ENGLISH_TELLS = re.compile(
    r"\b(?:the|your|you|and|of|with|save|saving|money|week|year|total|each|per)\b",
    re.IGNORECASE,
)
_ACCENTED = re.compile(r"[áéíóúñüàâçèêëîïôûùœ]", re.IGNORECASE)


def gate_locale(widget: Any, locale: str) -> tuple[bool, str]:
    """Every user-visible string is in this turn's language.

    English is not checked -- an English label in an English turn is the base
    case, and there is no negative signal to test for. Spanish and French are
    checked by their own accented characters and by the absence of English
    function words, which is crude and is correct at the length of a widget
    label.
    """
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
    """This widget came from the learning agent, about this concept, in a permitted form.

    Three checks and the third is the one that catches a real mistake rather than
    an attack: a composer given `growth_stack` that returns a `simulator` has
    produced something the concept's author never approved for it, and the band
    gate would pass it because the band permits both.
    """
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
    """Plan, compose, gate, cache. Returns an outcome; never raises.

    The catch-all is not defensive habit. This coroutine is awaited by the turn
    that has already emitted a complete lesson, and an exception escaping it
    would propagate into the streaming generator and end the turn with an error
    event -- turning a missing bonus into a broken answer, which is precisely the
    inversion this module exists to prevent.
    """
    import time

    started = time.monotonic()

    def elapsed() -> int:
        return int((time.monotonic() - started) * 1000)

    try:
        outcome = await _build(request, plan=plan, compose=compose, cache=cache)
        outcome.latency_ms = elapsed()
        return outcome
    except asyncio.CancelledError:
        # The prose path timed out waiting and cancelled this task. Not an error
        # and not logged as one -- the lesson is already on screen.
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

    # ── cache ───────────────────────────────────────────────────────────────
    #
    # Before composition, so a hit skips BOTH model calls. Most learning turns
    # are about the same few dozen concepts, so this is the common path rather
    # than an optimisation for a rare one.
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
    """Nine gates. First failure wins and names itself.

    Separated from `_build` so the tests can run the gates over a fixture without
    a planner, a composer or a cache -- which is the only way to prove a gate
    rejects what it claims to reject.
    """
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
    """Strip a code fence the composer wrapped its JSON in.

    Not a repair of the widget -- gate 1 still parses the JSON and rejects it if
    it is malformed. This removes a wrapper the model added around a correct
    object, which is a formatting habit rather than a composition failure, and
    rejecting it would drop good widgets for a reason no reviewer would guess
    from "invalid JSON".
    """
    match = _FENCE.match(raw or "")
    return (match.group(1) if match else (raw or "")).strip()


# ── the cache ────────────────────────────────────────────────────────────────


class WidgetCache:
    """Valkey, keyed by concept, band, locale and the plan hash.

    Every failure is swallowed and reported as a miss. A cache that can break a
    turn is worse than no cache, and the only thing a miss costs is two model
    calls on a path that is already allowed to produce nothing.
    """

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
    """The shared Valkey client, or None when the cache is not configured.

    `async` despite `get_client` being synchronous, so that the call sites stay
    awaits and a future backend that needs a round trip to connect does not
    require touching every one of them.
    """
    try:
        from app.cache import get_client

        return get_client()
    except Exception:
        return None
