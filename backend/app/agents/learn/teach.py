"""Saying the lesson: this child's words, the knowledge base's facts, and something to touch."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agents.learn.state import (
    FALLBACK_BAND,
    band_of,
    merge,
    remember_opening,
    remember_widget,
    taught_again,
    touched,
)
from app.curriculum.schema import Lesson
from app.graph.nodes.safety_out import WORD_CAPS
from app.graph.state import AspireState, KBChunk
from app.safety import vocab
from app.widgets import sentinel

logger = logging.getLogger(__name__)

#: How many chunks to ground a lesson in.
RETRIEVE_K = 4

#: Which corpus slice a learning turn may be grounded in.
_AUDIENCE: dict[str, str] = {
    "learn_agent": "youth",
    "learning_sample": "public",
    "learning_preview": "all",
}


def audience_for(state: AspireState) -> str:
    return _AUDIENCE.get(str(state.get("active_agent")), "youth")


_SYSTEM = """You are teaching one idea to one child, as their mascot.

THE IDEA, and you must get all of it across:
{spine}

An example this band understands. Use it, or one just as concrete and just as
local -- patties, snow cones, a bicycle, a Carnival costume:
{example}

{grounding}

HOW TO SAY IT
- At most {cap} words. This is a hard limit and shorter is better.
- Words you may use freely: {ladder}
- Words you may NOT use, at all: {banned}
- Plain sentences. No markup, no links, no lists, no headings.
- Warm, and never babyish. You are explaining, not performing.
- Stop when the idea is explained. A question is asked in the very next
  message, so do not ask one, do not invite them to reply, and do not tell them
  what is coming.
{avoid}
Write only what the child reads. Never describe what you are doing."""

_RETEACH_SYSTEM = """You are a mascot who has just shown a child the answer they
could not reach.

They have already been told what it is. Your job now is WHY it is that, in one
or two sentences, and then move on warmly. Do not restate the answer as though
it were news, do not say anything about their attempt, and do not ask another
question.

THE IDEA:
{spine}

{grounding}

HOW TO SAY IT
- At most {cap} words. Fewer is better here than anywhere.
- Words you may use freely: {ladder}
- Words you may NOT use, at all: {banned}
- Plain sentences. No markup, no links, no lists.
{avoid}
Write only what the child reads."""


def _spine(lesson: Lesson, band: str) -> str:
    """The teach points, as a list the model must cover rather than recite."""
    points = lesson.teach_for(band) or [lesson.objective]
    return "\n".join(f"- {point}" for point in points)


def _example(lesson: Lesson, band: str) -> str:
    examples = lesson.examples_for(band)
    return examples[0] if examples else "(none written -- invent one, and keep it local)"


def _grounding(chunks: list[KBChunk]) -> str:
    """Retrieved rows, framed as background rather than as something to quote.

    `without_provenance` takes the CSV's bookkeeping columns off first. A lesson
    is told never to cite a reference number, and it was being handed rows that
    ended `source_url: https://aspire.gov.kn/` -- the one kind of reference a
    child's lesson has no business reproducing.
    """
    from app.sources import without_provenance

    if not chunks:
        return (
            "You have no reference material this turn. Teach the idea above and "
            "state no amounts, dates or deadlines you were not given."
        )
    body = "\n".join(
        f"- {text}" for chunk in chunks if (text := without_provenance(chunk.content))
    )
    if not body:
        return "You have no reference material this turn."
    return (
        "BACKGROUND, so that anything you say about the real programme is "
        "current. Draw on it only if it helps the idea land. Never quote it, "
        "never cite a reference number, and never turn the lesson into a "
        "summary of it:\n" + body
    )


def _avoid(learning: dict) -> str:
    """What this learner has already heard, as things not to do again."""
    seen = [line for line in (learning.get("recent_openings") or []) if line]
    if seen:
        listed = "\n".join(f'- "{line}"' for line in seen[-3:])
        return (
            "\nThey have heard this idea from you already in this conversation. "
            "These are how you began -- begin differently, and take a different "
            "angle in:\n"
            f"{listed}\n"
        )

    if learning.get("concept_seen_before"):
        return (
            "\nThey have been taught this idea before, on another day. Do not "
            "open the way an explanation of it usually opens, and do not lead "
            "with the definition -- start from the example, or from a question "
            "they would actually ask, and let the idea arrive second.\n"
        )

    return ""


def authored_body(lesson: Lesson, band: str) -> str:
    """The lesson as the curriculum wrote it."""
    points = lesson.teach_for(band)
    body = " ".join(points[:2])
    examples = lesson.examples_for(band)
    if examples:
        body = f"{body} {examples[0]}"
    return body.strip()


def _cap(band: str) -> int:
    """The band's word cap, as a number the prompt can state."""
    # `FALLBACK_BAND`'s cap, not a separate number.
    return WORD_CAPS.get(band) or WORD_CAPS[FALLBACK_BAND] or 70


async def _compose(
    *,
    system: str,
    lesson: Lesson,
    band: str,
    learning: dict,
    chunks: list[KBChunk],
    widget_prompt: str | None,
    invoke,
    user: str,
    context=None,
) -> str | None:
    """One model call, or None if it could not be made."""
    if invoke is None:
        return None

    role = system.format(
        spine=_spine(lesson, band),
        example=_example(lesson, band),
        grounding=_grounding(chunks),
        cap=_cap(band),
        ladder=", ".join(sorted(vocab.concepts_for(band))) or "plain language only",
        banned=", ".join(sorted(vocab.banned_terms(band))) or "(none)",
        avoid=_avoid(learning),
    )

    # One prompt builder for every agent.
    if context is not None:
        from app.prompting import build_messages

        messages = build_messages(
            context=context,
            agent_role=role,
            user_text=user,
            extra_instruction=widget_prompt,
        )
    else:
        # No resolved context: a unit test, or a turn where `resolve_context` did not run.
        prompt = f"{role}\n\n{widget_prompt}" if widget_prompt else role
        messages = [SystemMessage(content=prompt), HumanMessage(content=user)]

    try:
        text = await invoke(messages)
    except Exception:
        logger.warning(
            "The teaching call failed for lesson %s; serving the authored text.",
            lesson.id,
            exc_info=True,
        )
        return None

    return (text or "").strip() or None


def make_plan_widget(curriculum=None, *, retrieve=None, plan=None):
    """Ground the lesson and choose a primitive, before a word is written."""
    from app.curriculum.schema import load_all

    async def plan_widget(state: AspireState) -> dict[str, Any]:
        book = curriculum or load_all()
        learning = state.get("learning") or {}
        lesson = book.lessons.get(learning.get("lesson_id") or "")
        if lesson is None:  # pragma: no cover - routing guards this
            return {}

        band = band_of(state)
        chunks, planned = await _ground_and_plan(
            state=state,
            lesson=lesson,
            band=band,
            learning=learning,
            retrieve=retrieve,
            plan=plan,
        )
        return {
            "retrieved": chunks,
            "learning": merge(learning, pending_widget=getattr(planned, "kind", None)),
        }

    return plan_widget


async def _ground_and_plan(
    *, state: AspireState, lesson: Lesson, band: str, learning: dict, retrieve, plan
) -> tuple[list[KBChunk], Any]:
    """Retrieval and widget planning, started together and failing separately."""

    async def _retrieval() -> list[KBChunk]:
        if retrieve is None:
            return []
        query = f"{lesson.objective} {lesson.concept_id.replace('_', ' ')}"
        return list(await retrieve(query, RETRIEVE_K, audience_for(state)))

    async def _planning():
        if plan is None:
            return None
        from app.graph.nodes.safety_in import latest_user_text

        return await plan(
            # What the child last said, or the lesson's objective when they said nothing.
            user_message=latest_user_text(state) or lesson.objective,
            concept_id=lesson.concept_id,
            age_band=band,
            locale=str(state.get("locale") or "en"),
            recent_widget_kinds=list(learning.get("last_widget_kinds") or []),
        )

    grounded, planned = await asyncio.gather(
        _retrieval(), _planning(), return_exceptions=True
    )

    if isinstance(grounded, BaseException):
        logger.warning("Could not ground lesson %s.", lesson.id, exc_info=grounded)
        grounded = []
    if isinstance(planned, BaseException):
        logger.warning("Widget planning failed for %s.", lesson.id, exc_info=planned)
        planned = None

    return grounded, planned


class _Planned:
    """The kind carried across the node boundary, in the shape `_widget_prompt` reads."""

    __slots__ = ("kind",)

    def __init__(self, kind: str | None):
        self.kind = kind


def _widget_prompt(planned, *, band: str, locale: str, concept_id: str) -> tuple[str | None, str | None]:
    """Always `(None, None)`."""
    return None, None


def make_teach(curriculum=None, *, invoke=None):
    """Say the lesson."""
    from app.curriculum.schema import load_all

    async def teach(state: AspireState) -> dict[str, Any]:
        book = curriculum or load_all()
        learning = state.get("learning") or {}
        lesson = book.lessons.get(learning.get("lesson_id") or "")
        if lesson is None:  # pragma: no cover - routing guards this
            return {}

        band = band_of(state)
        chunks = list(state.get("retrieved") or [])
        widget_prompt, kind = _widget_prompt(
            _Planned(learning.get("pending_widget")),
            band=band,
            locale=str(state.get("locale") or "en"),
            concept_id=lesson.concept_id,
        )

        body = await _compose(
            system=_SYSTEM,
            lesson=lesson,
            band=band,
            learning=learning,
            chunks=chunks,
            widget_prompt=widget_prompt,
            invoke=invoke,
            user=f"Teach them: {lesson.objective}",
            context=state.get("context"),
        )
        if body is None:
            body = authored_body(lesson, band)

        # Remembered only if a widget was actually WRITTEN.
        if kind and sentinel.count(body) == 0:
            logger.info(
                "Planned a %s for lesson %s and none was composed; serving prose.",
                kind,
                lesson.id,
            )
            kind = None

        return {
            "messages": [AIMessage(content=body)],
            "quick_replies": _chips(band, ["Got it", "Say that again"]),
            "learning": merge(
                learning,
                phase="checking",
                concepts_touched=touched(learning, lesson.concept_id),
                # What was COMPOSED, never what the curriculum suggested.
                last_widget_kinds=remember_widget(learning, kind),
                recent_openings=remember_opening(learning, body),
                teach_count=taught_again(learning, lesson.id),
                # Consumed.
                pending_widget=None,
            ),
        }

    return teach


def make_reteach(curriculum=None, *, retrieve=None, invoke=None):
    """After the reveal: why it is that answer, then move on."""
    from app.curriculum.schema import load_all

    async def reteach(state: AspireState) -> dict[str, Any]:
        book = curriculum or load_all()
        learning = state.get("learning") or {}
        lesson = book.lessons.get(learning.get("lesson_id") or "")
        if lesson is None:  # pragma: no cover
            return {}

        band = band_of(state)
        chunks: list[KBChunk] = []
        if retrieve is not None:
            try:
                chunks = list(
                    await retrieve(
                        f"{lesson.objective} {lesson.concept_id.replace('_', ' ')}",
                        RETRIEVE_K,
                        audience_for(state),
                    )
                )
            except Exception:
                logger.warning("Could not ground the reteach for %s.", lesson.id, exc_info=True)

        body = await _compose(
            system=_RETEACH_SYSTEM,
            lesson=lesson,
            band=band,
            learning=learning,
            chunks=chunks,
            widget_prompt=None,
            invoke=invoke,
            user=f"Explain why: {lesson.objective}",
            context=state.get("context"),
        )
        if body is None:
            points = lesson.teach_for(band)
            body = points[-1] if points else lesson.objective

        return {
            "messages": [AIMessage(content=body)],
            "quick_replies": _chips(band, ["Got it", "Next"]),
            "learning": merge(
                learning,
                phase="updating_mastery",
                outcome="wrong",
                recent_openings=remember_opening(learning, body),
            ),
        }

    return reteach


def _chips(band: str, options: list[str]) -> list[str]:
    """Chips, capped at four and at four words each."""
    return [" ".join(option.split()[:4]) for option in options[:4]]
