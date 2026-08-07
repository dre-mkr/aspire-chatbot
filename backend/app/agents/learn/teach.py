"""Saying the lesson: this child's words, the knowledge base's facts, and
something to touch.

The two nodes that produce teaching prose -- `teach` and `reteach` -- and the
one model call they share. Everything else in the lesson machine stays exactly
as deterministic as it was, and that division is the whole design of this file.

## What the model is allowed to decide, and what it is not

    authored, in the curriculum        the model's job
    ────────────────────────────       ──────────────────────────────
    which lesson (placement)           the words this child reads
    which concept it teaches           the order and the framing
    the teach points to convey         the example's local detail
    the check question and its answer  which of nine widgets, if any
    the hint ladder, rung by rung      whether a widget helps at all
    whether the answer was right

A lesson that can pick its own facts is a lesson that can teach the wrong ones,
and `grade_answer` staying in Python is what makes the hint ladder mean the
same thing on Tuesday as it did on Monday (`graph.grade_answer`). So the spine
is authored and reviewed, and what the model contributes is the thing a fixed
string cannot: the same idea, said differently, to a child who has heard it
before.

## Why the old node had to go

It emitted `teach_points[band][:2]` joined with a space, plus one example.
Correct, reviewed, band-appropriate -- and byte-identical every time the lesson
came round. Spaced repetition is *designed* to bring a concept back, so the
child who benefits most from the system is the one guaranteed to read the same
paragraph three times. `_avoid` exists because of that: the openings of the
last few teaching turns go into the prompt as things not to do again.

## Grounding, and why a lesson cites nothing

`retrieve` pulls from the same knowledge base `qa_agent` answers from -- one
corpus, one ingestion, one embedding model. What the chunks are FOR is
different, though, and the prompt says so: Q&A answers a question and must
attribute every figure to a row (`qa/nodes.ground_check`), while a lesson
explains an idea and a six-year-old has no use for "[ASP-042]". The chunks keep
the amounts, the deadlines and the branch names accurate. They are not quoted.

Retrieval failing costs grounding and never the turn. The teach points are
already correct on their own; the knowledge base makes them current.

## Two nodes, because one of them must not be heard

    plan_widget  →  teach  →  check
    (internal)      (streams)

`plan_widget` grounds and plans; `teach` writes. The split is not for tidiness,
it is the only way the planner can run at all.

`stream_mode="messages"` streams tokens from EVERY model call in the graph, and
the transport decides what to suppress by node name -- `INTERNAL_NODES` in
`graph/stream_interceptor.py`. A planner call made inside `teach` carries
`langgraph_node="teach"`, which is not on that list, so `{"kind": "compare",
"rationale": "asked what it is"}` would arrive at the child as prose, ahead of
the lesson. That is precisely what happened to the classifier the first time
the graph was run end to end, and it is why the deny-list exists.

`plan_widget` was already reserved in `INTERNAL_NODES` with nothing bearing the
name. Retrieval rides along in the same node so the two still run concurrently
(`asyncio.gather`): nothing in the planning input depends on retrieval, and
paying those latencies end to end would be paying twice for no reason.

`teach` is then the node that streams, and that is the second half of why the
widget works. The transport recognises `⟦widget⟧` in a TOKEN STREAM, and the
node this replaced streamed nothing at all. That is why the whole widget
pipeline -- nine schemas, seven gates, twelve few-shot files, nine React
renderers -- has been sitting complete and unreachable.

## No model configured is a supported deployment

`invoke=None` falls back to `authored_body`, which is the old node's output
exactly. Every existing test that builds this graph without a model keeps
passing, and a deployment with no provider key still teaches -- flatly, and
correctly.
"""

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
#:
#: Smaller than Q&A's twelve-into-four, and for a different reason than cost: a
#: lesson needs the concept to be *right*, not the specific row to be *found*.
#: Four chunks of background is enough to keep an amount current and few enough
#: that the model does not start reciting policy at a nine-year-old.
RETRIEVE_K = 4

#: Which corpus slice a learning turn may be grounded in.
#:
#: Keyed on the agent name like `qa/nodes._audience`, and deliberately NOT
#: defaulting to "all": the learner-facing name is the one a child is behind, so
#: the fall-through here is the narrow slice rather than the wide one. A
#: guardian previewing gets the full corpus because a guardian is an adult.
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

    The framing is doing real work. Handed bare context, a model trained on Q&A
    data starts answering with it -- the lesson turns into a policy summary with
    a mascot's punctuation. Naming what it is for, and naming the two things not
    to do with it, is what keeps it in the background where it belongs.
    """
    if not chunks:
        return (
            "You have no reference material this turn. Teach the idea above and "
            "state no amounts, dates or deadlines you were not given."
        )
    body = "\n".join(f"- {chunk.content.strip()}" for chunk in chunks if chunk.content.strip())
    if not body:
        return "You have no reference material this turn."
    return (
        "BACKGROUND, so that anything you say about the real programme is "
        "current. Draw on it only if it helps the idea land. Never quote it, "
        "never cite a reference number, and never turn the lesson into a "
        "summary of it:\n" + body
    )


def _avoid(learning: dict) -> str:
    """What this learner has already heard, as things not to do again.

    Two signals, and they cover different failures.

    `recent_openings` is exact and it is per CONVERSATION, because the learning
    state is checkpointed per thread. Openings rather than whole messages, for
    two reasons: a model handed three full previous turns writes a fourth that
    differs from them in every respect including the ones that were right, and
    repetition is *heard* at the start -- "Saving means keeping money for
    later" landing identically a third time is what tells a child this is a
    recording.

    `concept_seen_before` is vague and it CROSSES conversations. It is the case
    the first signal cannot see and the one that actually happens: a learner
    comes back the next day, opens a new chat, and spaced repetition brings the
    concept round again with an empty thread behind it. Without it the model
    gets the same prompt it got yesterday and, at this temperature, writes
    close to the same words -- which is precisely the report that prompted
    this: the same lesson, verbatim, on a fresh conversation.
    """
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
    """The lesson as the curriculum wrote it. The fallback, and the floor.

    Byte-for-byte what the node produced before there was a model call here, so
    a deployment with no provider key degrades to the previous behaviour rather
    than to an error -- and so the graph tests that build without a model are
    testing the same thing they were testing before.
    """
    points = lesson.teach_for(band)
    body = " ".join(points[:2])
    examples = lesson.examples_for(band)
    if examples:
        body = f"{body} {examples[0]}"
    return body.strip()


def _cap(band: str) -> int:
    """The band's word cap, as a number the prompt can state.

    Read from `safety_out.WORD_CAPS` rather than repeated, because a prompt that
    asks for a different number than the gate enforces produces a reply that is
    re-prompted on every single turn -- a second model call, forever, caused by
    a copied constant drifting.
    """
    # `FALLBACK_BAND`'s cap, not a separate number. This line used to return 120
    # -- the 13-15 allowance -- for a learner every other site in this agent was
    # treating as 9-12, whose cap is 70. One default, resolved through one band.
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
    """One model call, or None if it could not be made.

    None rather than a raised exception, and never a partial: the caller has an
    authored paragraph ready, and a child waiting through a retry to receive a
    worse version of a sentence that already existed is the wrong trade.
    """
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

    # Track C.4: one builder for every agent. The role above is the third layer;
    # GLOBAL and the persona card come from `app/prompting`, and the conversation
    # history arrives for the first time -- this call used to be
    # `[SystemMessage(role), HumanMessage(user)]` with no prior turns at all.
    #
    # `widget_prompt` goes in as `extra_instruction`, which lands BELOW the cache
    # breakpoint: it is present on some turns and absent on others, so putting it
    # in the prefix would break the prefix on every turn that has one.
    if context is not None:
        from app.prompting import build_messages

        messages = build_messages(
            context=context,
            agent_role=role,
            user_text=user,
            extra_instruction=widget_prompt,
        )
    else:
        # No resolved context: a unit test driving the node directly, or a turn
        # where `resolve_context` did not run. Falls back to the pre-C.4 shape
        # rather than failing, and loses only the history it never had.
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
    """Ground the lesson and choose a primitive, before a word is written.

    The node MUST stay named `plan_widget`: `INTERNAL_NODES` suppresses its
    model call by node name, and renaming it here without renaming it there
    would stream the planner's JSON to a child.

    Writes `retrieved` (the same state field Q&A uses, so one turn's retrieval
    is visible in one place) and `learning.pending_widget`, which is the kind
    `teach` will be asked to compose.
    """
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
    """Retrieval and widget planning, started together and failing separately.

    `return_exceptions=True` because these two have nothing to do with each
    other: a planner outage must not cost the grounding, and an empty knowledge
    base must not cost the widget. Each half degrades to its own neutral value.
    """

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
            # What the child last said, falling back to the lesson's own
            # objective when they said nothing -- a lesson can begin because
            # the previous one ended, with no message to plan against.
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
    """The kind carried across the node boundary, in the shape `_widget_prompt`
    reads.

    `Plan` itself is not checkpointed: it is a frozen dataclass and the state
    that crosses between nodes is JSON. Only the kind makes the trip.

    The field that does NOT make it is `Plan.concept_id`, the forced-kind
    redirect -- the rule that gives a nine-year-old asking about compounding a
    growth stack about `interest` instead. Checked rather than assumed: run
    `forced_kind` over every lesson concept at every band it is taught at and
    the redirect is the identity in all of them, because the curriculum is
    already band-filtered and a lesson is never about a concept off its own
    learner's ladder. A lesson whose concept redirects would need this widened.
    """

    __slots__ = ("kind",)

    def __init__(self, kind: str | None):
        self.kind = kind


def _widget_prompt(planned, *, band: str, locale: str, concept_id: str) -> tuple[str | None, str | None]:
    """Always `(None, None)`. The inline sentinel path is hard-disabled.

    ## What this used to do, and why it had to stop

    It returned `composition_prompt(...)`, which instructed the teaching model to
    emit a widget as JSON between `⟦widget⟧` markers, inline in the lesson. One
    model call produced both. Three consequences followed and each destroys a
    lesson on its own:

      * the widget's few hundred characters of JSON and the lesson's word budget
        came out of one generation, so the model traded prose away to fit it;
      * `graph/stream_interceptor.py` stops forwarding tokens at the opening
        marker, so a widget opened early meant almost no lesson reached the reader
        before the stream went quiet;
      * an unterminated marker caused the buffered block to be DISCARDED, taking
        every token after it with it. A malformed widget silently truncated the
        lesson mid-sentence.

    The third is the reported defect's mechanism. It is not fixable by prompting,
    because the failure is in what the transport must do with a half-widget: a
    client shown half a JSON object has no correct move, so buffering is right and
    inline composition is what has to go.

    ## Where widgets come from now

    `agents/learn/widgets.py`, on a separate task, from a separate model call,
    emitted as its own directive AFTER validated prose. `agents/learn/tutor.py`
    runs it. A widget failure there cannot subtract a word from a lesson, and
    `tests/learning/test_prose_survives_widgets.py` fails if that stops being
    true.

    ## Why this is a stub rather than a deletion

    Two reasons, and the second is the real one. `plan_widget` still runs and
    still records which primitive it would have chosen, so the planner's accuracy
    stays measurable by `evals/widgets.jsonl` while the curriculum path is
    migrated. And the signature is still called from `make_teach`, so a stub
    keeps the diff to one function rather than spreading through a node that is
    otherwise unchanged and still serving authored lessons correctly.

    KNOWN GAP, recorded rather than hidden: curriculum lessons served by this node
    now carry no widget at all. The tutor path has them; the authored-lesson path
    will when it moves onto `build_widget`. A lesson with no widget is a complete
    lesson, which is the whole premise of this workstream -- so this is a feature
    temporarily absent from one path, not a broken one.
    """
    return None, None


def make_teach(curriculum=None, *, invoke=None):
    """Say the lesson. Model-written when there is a model, authored when not.

    `invoke` is `async (messages) -> str`, injected and optional: with None the
    node serves `authored_body` and the machine behaves exactly as it did before
    there was a model in it.

    Reads the grounding and the planned primitive off state -- `plan_widget` put
    them there on the node before. This node makes exactly one model call, and
    that is what lets the transport treat every token it produces as prose meant
    for the reader.
    """
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

        # Remembered only if a widget was actually WRITTEN. Three ways the kind
        # can be set and no widget exist: the model call failed and the authored
        # paragraph was served, the model was asked for one and wrote prose
        # instead, or it emitted an unterminated marker. In all three the
        # planner would go on to avoid a primitive this child has never seen.
        #
        # Note this counts the sentinel, not a valid widget -- the seven gates
        # in `widgets/validate.py` run later, in the transport, and a composition
        # that fails one of them is a different problem with its own counter.
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
                # What was COMPOSED, never what the curriculum suggested. The
                # old node recorded `lesson.suggested_widget_kind` here, which
                # was harmless while nothing emitted widgets and is not any
                # more: `last_widget_kinds` is what the planner reads to avoid
                # repeating itself, so a suggestion recorded as a sighting
                # would suppress the primitive that lesson is best served by.
                last_widget_kinds=remember_widget(learning, kind),
                recent_openings=remember_opening(learning, body),
                teach_count=taught_again(learning, lesson.id),
                # Consumed. Left set, a resumed turn that re-enters `teach`
                # without passing `plan_widget` would compose the same widget
                # a second time.
                pending_widget=None,
            ),
        }

    return teach


def make_reteach(curriculum=None, *, retrieve=None, invoke=None):
    """After the reveal: why it is that answer, then move on. No further attempt.

    No widget and no planner call. The child has just been shown an answer they
    could not reach, and the next thing they need is one sentence of sense-making
    -- handing them a slider to explore instead is changing the subject at the
    moment they are most likely to disengage.
    """
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
    """Chips, capped at four and at four words each.

    Authored rather than generated, and that stays true now that the prose
    around them is not. Gate (e) in `safety_out` requires chips on a lesson
    turn, and a missing one costs a re-prompt -- a second model call to produce
    two words somebody has already written.
    """
    return [" ".join(option.split()[:4]) for option in options[:4]]
