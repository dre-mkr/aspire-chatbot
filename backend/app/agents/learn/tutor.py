"""One learning turn, from "what did they ask?" to "here is the lesson".

    resolve  ─►  plan_move  ─►  tutor  ─►  turn_end
                                 │
                                 ├─ prose   validated, then emitted
                                 └─ widget  concurrent, timed out, dropped freely

This is the node the reported defect lives in, and the shape above is the fix.
The two properties it exists to guarantee are both testable and both tested:

  1. A learning turn ALWAYS emits a substantive, grounded, persona-appropriate
     explanation. `render.render_teach` has three tiers and the third is
     deterministic Python, so there is no configuration -- including no provider
     key at all -- in which this node produces an empty or trivial turn.

  2. The widget is an enhancement layered on prose that already exists and has
     already been emitted. The widget task is created at the same instant as the
     prose task, is awaited only after the prose is on the wire, and cannot
     return anything but a validated config or None.

The reverse of (2) -- a widget with no lesson -- is a P0 bug, and
`tests/learning/test_prose_survives_widgets.py` fails if it ever becomes
reachable.

## Why the prose is written to the custom channel

`stream_mode="messages"` forwards a model's tokens as it produces them, which
means anything the model writes reaches the reader before anything can check it.
That is not compatible with the tier-2 guarantee, and it is how an unterminated
widget marker used to truncate a lesson mid-sentence.

So this node is on `INTERNAL_NODES` -- its raw model tokens are suppressed -- and
it emits the VALIDATED lesson explicitly, as a `prose` payload on the graph's own
custom channel. The invariant that buys is worth stating: no token a model
produced reaches a child without having passed the band contract first.

## Ordering on the wire

    token…token   the lesson, as one or more token events
    directive     the widget, at the NEXT ordinal, or absent

Ordinals come from the interceptor and are monotonic over events, so the client's
settled-block parser sees the widget as its own block arriving after the prose
block. A turn with no widget closes with no directive and the parser handles it,
because "no directive" is the common case rather than an error path.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from langchain_core.messages import AIMessage

from app.agents.learn.contract import contract_for
from app.agents.learn.planner import LearnerSnapshot, Move, hint_level, plan_move
from app.agents.learn.render import RenderResult, TeachContext, decline_text, render_teach
from app.agents.learn.resolve import ConceptResolution, enqueue_candidate, resolve_concept
from app.agents.learn.state import band_of, merge, on_concept, remember_opening, seen_check, touched
from app.agents.learn.widgets import WidgetCache, WidgetOutcome, WidgetRequest, build_widget
from app.learning.concepts import CheckItem, TeachingConcept, get_store

logger = logging.getLogger(__name__)


# ── check selection: Python chooses, the model renders ───────────────────────


def select_check(
    concept: TeachingConcept | None, *, band: str, seen: list[str]
) -> CheckItem | None:
    """Which question to ask. Unseen first, then round-robin.

    Chosen in Python and handed to the renderer, never picked by the model. Two
    reasons and the second is the load-bearing one: a model picking from a bank
    picks the first item every time, and -- more importantly -- the ANSWER has to
    be known to the grader before the question is asked. A question the model
    invented has no accept list, so the grader has nothing to compare against and
    the hint ladder has no rungs.
    """
    if concept is None:
        return None
    items = concept.checks_for(band)
    if not items:
        return None
    unseen = [item for item in items if item.id not in set(seen)]
    return (unseen or list(items))[0]


def select_hint(item: CheckItem | None, level: int) -> str | None:
    """The rung. Level 3 gives the method; there is no rung that gives the answer."""
    if item is None or not item.hints:
        return None
    return item.hints[min(level, len(item.hints)) - 1]


# ── the node ─────────────────────────────────────────────────────────────────


def make_tutor(
    *,
    embed: Any = None,
    retrieve: Any = None,
    disambiguate: Any = None,
    invoke: Any = None,
    plan: Any = None,
    compose: Any = None,
    mastery: Any = None,
    cache: Any = None,
):
    """Build the tutor node.

    Every collaborator is injected and every one is optional. With all of them
    None the node still teaches -- from the concept store, through the template
    floor -- which is what makes the guarantee in the module docstring
    unconditional rather than dependent on a healthy deployment.
    """

    async def tutor(state: Any) -> dict[str, Any]:
        started = time.monotonic()
        learning = dict(state.get("learning") or {})
        band = band_of(state)
        locale = str(state.get("locale") or "en")
        agent = str(state.get("active_agent") or "learn_agent")
        store = get_store()

        from app.graph.nodes.safety_in import latest_user_text

        utterance = latest_user_text(state) or ""

        # ── 1. what is this turn about? ─────────────────────────────────────
        resolution = await resolve_concept(
            utterance,
            band=band,
            locale=locale,
            active_concept_id=learning.get("active_concept_id"),
            awaiting_answer=bool(learning.get("awaiting_check_answer")),
            store=store,
            embed=embed,
            retrieve=retrieve,
            disambiguate=disambiguate,
        )

        if resolution.source in ("rag", "none"):
            # Fire and forget: the authoring backlog must never be the thing that
            # delays a child's lesson.
            asyncio.create_task(
                enqueue_candidate(utterance, band=band, locale=locale, resolution=resolution)
            )

        if not resolution.teaches:
            return _decline(state, learning, resolution, band, started)

        concept = resolution.concept

        # ── 2. which move? Pure Python. ─────────────────────────────────────
        score = await _mastery_of(mastery, state, concept)
        snapshot = LearnerSnapshot.from_state(
            learning, band=band, concept=concept, mastery=score
        )
        move = plan_move(snapshot)

        check_item = select_check(concept, band=band, seen=list(learning.get("seen_check_ids") or []))
        if move is Move.HINT:
            pending = learning.get("pending_check_id")
            check_item = next(
                (
                    item
                    for item in (concept.checks_for(band) if concept else ())
                    if item.id == pending
                ),
                check_item,
            )

        # ── 3. prose and widget, started together ───────────────────────────
        context = TeachContext(
            concept=concept,
            band=band,
            locale=locale,
            move=move,
            persona=str(state.get("persona") or "stella"),
            supporting=tuple(resolution.kb_rows) or tuple(state.get("retrieved") or ()),
            check_item=check_item,
            hint=select_hint(check_item, hint_level(snapshot)) if move is Move.HINT else None,
            mastered=tuple(learning.get("concepts_touched") or ())[-6:],
            prior_wrong=tuple(learning.get("prior_wrong_answers") or ()),
            utterance=utterance,
            voice=bool(state.get("voice")),
            recent_openings=tuple(learning.get("recent_openings") or ()),
        )

        # Created BEFORE the prose is awaited, which is the whole contract. The
        # widget's two model calls overlap the teaching call entirely, so the
        # widget costs the turn nothing but the tail it is given after the prose
        # has already been emitted.
        widget_task = asyncio.create_task(
            build_widget(
                WidgetRequest(
                    concept=concept,
                    band=band,
                    locale=locale,
                    agent=agent,
                    recent_kinds=tuple(learning.get("last_widget_kinds") or ()),
                    utterance=utterance,
                ),
                plan=plan,
                compose=compose,
                cache=cache if cache is not None else WidgetCache(),
            )
        )

        try:
            lesson = await render_teach(
                context, invoke=invoke, session_context=state.get("context")
            )
        except Exception:
            # `render_teach` does not raise. This exists so that if it ever does,
            # the widget task is not left orphaned holding a connection.
            widget_task.cancel()
            raise

        # ── 4. the lesson goes out. Nothing below can take it away. ─────────
        _emit_prose(lesson.spoken or lesson.text)

        widget = await _await_widget(widget_task)
        if widget.emitted:
            _emit_directive(widget.payload)

        _log_turn(
            resolution=resolution,
            move=move,
            band=band,
            locale=locale,
            lesson=lesson,
            widget=widget,
            score=score,
            started=started,
        )

        return _state_after(
            state=state,
            learning=learning,
            resolution=resolution,
            move=move,
            band=band,
            lesson=lesson,
            widget=widget,
            check_item=check_item,
            snapshot=snapshot,
        )

    return tutor


# ── emission ─────────────────────────────────────────────────────────────────


def _writer() -> Any:
    """The custom-channel writer, or None outside a streaming run.

    None when a unit test invokes the node directly, and that must not be an
    error: the node's return value carries the same message, so a non-streaming
    caller loses the wire event and keeps the lesson.
    """
    try:
        from langgraph.config import get_stream_writer

        return get_stream_writer()
    except Exception:
        return None


def _emit_prose(text: str) -> None:
    """The validated lesson, as prose the transport will tokenise.

    Explicit rather than left to `stream_mode="messages"`, because this node is
    on `INTERNAL_NODES` -- its raw model output is suppressed precisely so that
    nothing unvalidated can reach a reader. This is the only prose this node
    emits and it has passed the band contract.
    """
    writer = _writer()
    if writer is not None and text.strip():
        writer({"prose": text})


def _emit_directive(payload: dict[str, Any] | None) -> None:
    writer = _writer()
    if writer is not None and payload:
        writer({"directive": payload})


async def _await_widget(task: "asyncio.Task[WidgetOutcome]") -> WidgetOutcome:
    """Wait for the widget, briefly, and never let it matter.

    Timeout, cancellation and every exception collapse to the same outcome: no
    widget, one log line, and a lesson the reader already has. The timeout is
    measured from HERE rather than from the task's creation, so the widget gets
    its full allowance after prose generation rather than competing with it --
    in practice it has usually finished already.
    """
    from app.config import get_settings

    try:
        return await asyncio.wait_for(task, timeout=get_settings().learn_widget_timeout_s)
    except asyncio.TimeoutError:
        task.cancel()
        logger.info("widget_dropped reason=timeout")
        return WidgetOutcome(gate="timeout", reason="exceeded the widget budget")
    except Exception:
        logger.warning("widget_dropped reason=exception", exc_info=True)
        return WidgetOutcome(gate="exception", reason="unhandled")


# ── the decline path ─────────────────────────────────────────────────────────


def _decline(
    state: Any,
    learning: dict[str, Any],
    resolution: ConceptResolution,
    band: str,
    started: float,
) -> dict[str, Any]:
    """Nothing resolved. Say so in persona, offer two things, do not escalate.

    Explicitly NOT an escalation and explicitly not an improvisation. A child
    asking about cryptocurrency has done nothing that warrants fetching a human,
    and a lesson invented on the spot about a topic nobody authored is the exact
    failure the concept table exists to prevent.
    """
    text = decline_text(band, resolution.alternatives)
    _emit_prose(text)
    logger.info(
        "learn_turn concept_id=None resolution_source=%s similarity=%.3f move=DECLINE "
        "band=%s prose_words=%d teach_fallback=decline widget_kind=None escalated=False "
        "total_ms=%d",
        resolution.source,
        resolution.similarity,
        band,
        len(text.split()),
        int((time.monotonic() - started) * 1000),
    )
    return {
        "messages": [AIMessage(content=text)],
        "quick_replies": _chips(
            band, [concept.title for concept in resolution.alternatives[:2]] or ["Something else"]
        ),
        "learning": merge(
            learning,
            phase="checking",
            active_concept_id=None,
            resolution_source=resolution.source,
            resolution_similarity=resolution.similarity,
            move="DECLINE",
            awaiting_check_answer=False,
            pending_check_id=None,
        ),
    }


# ── state and logging ────────────────────────────────────────────────────────


def _state_after(
    *,
    state: Any,
    learning: dict[str, Any],
    resolution: ConceptResolution,
    move: Move,
    band: str,
    lesson: RenderResult,
    widget: WidgetOutcome,
    check_item: CheckItem | None,
    snapshot: LearnerSnapshot,
) -> dict[str, Any]:
    concept_id = resolution.concept_id
    asked = move in (Move.TEACH, Move.CHECK, Move.RECAP, Move.ADVANCE, Move.HINT)

    return {
        # The message is returned as well as emitted. The wire event is what the
        # reader sees; this is what the checkpoint keeps, what the next turn's
        # history contains, and what `safety_out` gates. Both must be the same
        # string, which is why `lesson.text` is used here rather than `spoken` --
        # the transcript is written, not read aloud.
        "messages": [AIMessage(content=lesson.text)],
        "quick_replies": _chips(band, _chip_options(move, band)),
        "learning": merge(
            learning,
            phase="checking",
            active_concept_id=concept_id,
            resolution_source=resolution.source,
            resolution_similarity=resolution.similarity,
            move=move.value,
            concepts_touched=touched(learning, concept_id) if concept_id else learning.get("concepts_touched"),
            # A check was asked, so the next message is its answer. This single
            # bit is what makes a bare "20" reach EVALUATE instead of being read
            # as a new knowledge query.
            awaiting_check_answer=bool(check_item) and asked,
            pending_check_id=check_item.id if (check_item and asked) else None,
            seen_check_ids=seen_check(learning, check_item.id if asked else None),
            turns_on_concept=on_concept(learning, concept_id),
            turns_since_check=0 if (check_item and asked) else int(learning.get("turns_since_check") or 0) + 1,
            # Cleared on any move that is not a hint. The ladder counts
            # CONSECUTIVE misses, and a turn that taught rather than graded has
            # not added one.
            consecutive_wrong=snapshot.consecutive_wrong if move is Move.HINT else 0,
            recent_openings=remember_opening(learning, lesson.text),
            last_widget_kinds=_remember_kind(learning, widget.kind if widget.emitted else None),
        ),
    }


def _remember_kind(learning: dict[str, Any], kind: str | None, *, keep: int = 3) -> list[str]:
    """Widget kinds recently SHOWN. Only a kind that reached the reader counts.

    The distinction matters because this list is what the planner reads to avoid
    repeating itself. Recording a kind that was planned but dropped at a gate
    would suppress the primitive a concept is best served by, on the grounds that
    the child had seen it -- when they had not.
    """
    kinds = [item for item in (learning.get("last_widget_kinds") or []) if item]
    if kind:
        kinds.append(kind)
    return kinds[-keep:]


def _chip_options(move: Move, band: str) -> list[str]:
    if move is Move.HINT:
        return ["Try again", "Tell me"]
    if move is Move.EVALUATE:
        return ["Next", "Say more"]
    if band == "5-8":
        return ["Got it", "Say it again"]
    return ["Got it", "Say more", "Something else"]


def _chips(band: str, options: list[str]) -> list[str]:
    """Chips, capped at four and at four words each.

    Trimmed here rather than left to `safety_out`, because a chip that arrives too
    long triggers a re-prompt -- a model call to fix something the author could
    have written shorter.
    """
    return [" ".join(option.split()[:4]) for option in options[:4]][:4]


async def _mastery_of(mastery: Any, state: Any, concept: TeachingConcept | None) -> int:
    """This learner's score for this concept, or 0.

    Zero on every failure, and that is the safe direction: an unreadable mastery
    row means the concept is taught rather than skipped, and being taught
    something you already know is a smaller harm than never being taught it.
    """
    if mastery is None or concept is None:
        return 0
    try:
        from app.agents.learn.graph import _learner

        rows = await mastery.all_for(_learner(state))
        for row in rows:
            if row.concept_id == concept.id:
                return int(row.score)
    except Exception:
        logger.debug("Could not read mastery.", exc_info=True)
    return 0


def _log_turn(
    *,
    resolution: ConceptResolution,
    move: Move,
    band: str,
    locale: str,
    lesson: RenderResult,
    widget: WidgetOutcome,
    score: int,
    started: float,
) -> None:
    """One structured line per learning turn. Every field the health surface reads.

    A single line rather than several, because the questions being asked of it are
    joint -- "what is the fallback rate for 5-8 turns that resolved semantically?"
    cannot be answered from two lines that have to be correlated by timestamp.
    """
    from app.learning.health import TurnMetrics

    metrics = TurnMetrics(
        concept_id=resolution.concept_id,
        resolution_source=resolution.source,
        similarity=resolution.similarity,
        move=move.value,
        band=band,
        locale=locale,
        prose_words=lesson.words,
        teach_retry=lesson.retry,
        teach_fallback="template" if lesson.tier == 3 else "none",
        widget_kind=widget.kind if widget.emitted else None,
        widget_gate_failed=widget.gate,
        widget_cache_hit=widget.cache_hit,
        widget_latency_ms=widget.latency_ms,
        mastery_before=score,
        total_ms=int((time.monotonic() - started) * 1000),
    )

    logger.info(
        "learn_turn concept_id=%s resolution_source=%s similarity=%.3f move=%s band=%s "
        "locale=%s prose_words=%d teach_tier=%d teach_retry=%s teach_fallback=%s "
        "widget_kind=%s widget_gate_failed=%s widget_cache_hit=%s widget_latency_ms=%d "
        "mastery_before=%d escalated=False total_ms=%d",
        metrics.concept_id,
        metrics.resolution_source,
        metrics.similarity,
        metrics.move,
        metrics.band,
        metrics.locale,
        metrics.prose_words,
        lesson.tier,
        metrics.teach_retry,
        metrics.teach_fallback,
        metrics.widget_kind,
        metrics.widget_gate_failed or "none",
        metrics.widget_cache_hit,
        metrics.widget_latency_ms,
        metrics.mastery_before,
        metrics.total_ms,
    )

    # Fire and forget. The aggregate is an alerting surface and the log line
    # above is the record -- a counter write that could delay or break a lesson
    # would be a worse trade than losing a data point.
    from app.learning.health import record

    asyncio.create_task(record(metrics))
