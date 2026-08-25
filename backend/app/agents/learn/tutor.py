"""One learning turn, from "what did they ask?" to "here is the lesson".

The turn runs in one order and it is the order §2 of the tutoring brief names:

    resolve   -- what is this turn about?
    evaluate  -- what did they just demonstrate?
    plan      -- what does this learner need from me right now?
    render    -- say it, in the way this learner needs it said
    record    -- write what happened, so the next turn knows

`evaluate` and `record` are the two that used not to exist. Without the first,
every move was chosen from a snapshot that never changed; without the second,
mastery stayed at zero forever and no amount of correct answering could move
the tutor on.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from langchain_core.messages import AIMessage

from app.agents.learn.evaluate import (
    Evaluation,
    Verdict,
    evaluate_answer,
    evidence_for,
    triage,
)
from app.agents.learn.planner import (
    ASKING_MOVES,
    EXPLAINING_MOVES,
    LearnerSnapshot,
    Move,
    hint_level,
    plan_move,
)
from app.agents.learn.render import RenderResult, TeachContext, decline_text, render_teach
from app.agents.learn.resolve import (
    ConceptResolution,
    asks_to_practise,
    enqueue_candidate,
    place_concept,
    resolve_concept,
    wants_a_lesson,
)
from app.agents.learn.state import (
    band_of,
    merge,
    on_concept,
    remember_misconception,
    remember_opening,
    seen_check,
    touched,
    with_independent,
    wrong_again,
)
from app.agents.learn.strategy import (
    Prerequisite,
    Strategy,
    find_prerequisite,
    instruction_for,
    next_strategy,
)
from app.agents.learn.widgets import WidgetCache, WidgetOutcome, WidgetRequest, build_widget
from app.learning.concepts import CheckItem, TeachingConcept, get_store

logger = logging.getLogger(__name__)


# ── check selection: Python chooses, the model renders ───────────────────────


def select_check(
    concept: TeachingConcept | None,
    *,
    band: str,
    seen: list[str],
    difficulty: int = 0,
) -> CheckItem | None:
    """Which question to ask, at which difficulty.

    §16's adaptive difficulty, spent on authored content rather than on an
    invented difficulty scale: a learner who is succeeding is asked the
    question written for the band above, and one who is struggling the band
    below. Where no such band exists the request is simply not honoured, which
    is the right outcome -- a harder question nobody wrote is not a harder
    question.
    """
    if concept is None:
        return None

    items = concept.checks_for(_shifted_band(band, difficulty)) or concept.checks_for(band)
    if not items:
        return None
    unseen = [item for item in items if item.id not in set(seen)]
    return (unseen or list(items))[0]


def _shifted_band(band: str, steps: int) -> str:
    """The band `steps` along the ladder, clamped to its ends."""
    from app.learning.concepts import BANDS, band_index

    index = band_index(band)
    if index < 0 or not steps:
        return band
    return BANDS[max(0, min(index + steps, len(BANDS) - 1))]


def difficulty_for(mastery: int, *, wrong_on_concept: int, hinted: bool) -> int:
    """How far to move the difficulty this turn. §16, as one number.

    Succeeding unaided earns a harder question. Needing hints to get there
    earns another at the same level -- that is the "correct with support" rung
    of §15, and promoting off it would mistake scaffolding for mastery.
    """
    if wrong_on_concept >= 2:
        return -1
    if mastery >= 2 and not hinted and not wrong_on_concept:
        return 1
    return 0


def select_hint(item: CheckItem | None, level: int) -> str | None:
    """The rung. The last rung gives the method; none of them gives the answer."""
    if item is None or not item.hints:
        return None
    return item.hints[min(level, len(item.hints)) - 1]


#: What the learner says when the explanation did not land. §14's trigger.
_CONFUSED = re.compile(
    r"""(?:
        (?:i\s+)?(?:still\s+)?(?:do\s*n[o']?t|don'?t|do\s+not)\s+
            (?:understand|get\s+it|follow|see|know\s+what\s+you\s+mean)
      | (?:i\s+am|i'?m)\s+(?:still\s+)?(?:lost|confused|stuck)
      | (?:that|this|it)\s+does\s*n[o']?t\s+make\s+sense
      | makes\s+no\s+sense
      | (?:huh|what)\?{2,}
      | (?:can\s+you\s+)?(?:say|explain)\s+(?:that\s+)?(?:again|differently|another\s+way)
      | i'?m\s+not\s+following
    )""",
    re.VERBOSE | re.IGNORECASE,
)


def sounds_confused(text: str) -> bool:
    """Whether this message says, in any words, that the explanation did not land.

    "Make it simpler" belongs here rather than in the grader. It is the same
    message as "I don't understand" said politely, and the tutor already knows
    what to do with that -- re-teach, do not score. `_CONFUSED` knew the
    English confessions of confusion and none of the requests to simplify, so
    on the live site, 25 Aug, "make it simpler" was graded as an attempt at the
    last check question and answered with a new one about payday.

    `wants_it_simpler` also carries Spanish and French, which `_CONFUSED` never
    did: "no entiendo" and "je ne comprends pas" were as unheard as the
    English request.
    """
    from app.graph.nodes.intents import wants_it_simpler

    return bool(_CONFUSED.search(text or "")) or wants_it_simpler(text or "")


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
    grade: Any = None,
    curriculum: Any = None,
):
    """Build the tutor node."""

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
            # Fire and forget: the authoring backlog must never delay a child's lesson.
            asyncio.create_task(
                enqueue_candidate(utterance, band=band, locale=locale, resolution=resolution)
            )

        scores = await _mastery_map(mastery, state)

        if not resolution.teaches:
            # "Teach me something" names no topic, so nothing resolves -- but it
            # is a request to be taught, not a question we cannot answer, and
            # declining it sent the learner to a path with no tutor in it.
            placed = (
                place_concept(
                    store=store,
                    band=band,
                    locale=locale,
                    mastery=scores,
                    exclude=set(learning.get("concepts_touched") or ()),
                )
                if wants_a_lesson(utterance)
                else None
            )
            if placed is None:
                return _decline(state, learning, resolution, band, started)

            logger.info("placed concept=%s for a request that named none", placed.id)
            resolution = ConceptResolution(
                concept=placed, source="placed", similarity=1.0
            )

        concept = resolution.concept

        # ── 2. what did they just demonstrate? ──────────────────────────────
        score = scores.get(concept.id, 0) if concept else 0

        outstanding = _outstanding_check(concept, learning, band)
        evaluation = await _grade(
            utterance,
            item=outstanding,
            concept=concept,
            band=band,
            learning=learning,
            grade=grade,
        )
        # Confusion is about the EXPLANATION, and is deliberately not set by a
        # `DONT_KNOW` verdict, which is about the question. `reteach_pending` is
        # how something outside the conversation -- a poor game score -- says
        # the concept has not landed.
        confused = sounds_confused(utterance) or bool(learning.get("reteach_pending"))

        # A wrong answer is the only thing that makes a prerequisite gap worth
        # suspecting, so the lookup is not done on turns that went well.
        prerequisite = (
            _prerequisite(concept, band=band, locale=locale, scores=scores, curriculum=curriculum)
            if _struggling(evaluation, confused=confused)
            else None
        )

        # ── 3. which move? Pure Python, from everything above. ──────────────
        snapshot = LearnerSnapshot.from_state(
            learning,
            band=band,
            concept=concept,
            mastery=score,
            verdict=evaluation.verdict if outstanding is not None else None,
            diagnosis=evaluation.diagnosis,
            holds_misconception=bool(evaluation.misconception),
            confused=confused,
            hints_available=len(outstanding.hints) if outstanding else 0,
            prerequisite_available=prerequisite is not None,
            wants_practice=asks_to_practise(utterance),
        )
        move = plan_move(snapshot)

        # A step back changes what is being taught, so it changes everything below.
        deferred_id = learning.get("deferred_concept_id")
        if move is Move.STEP_BACK and prerequisite is not None:
            logger.info(
                "step_back from=%s to=%s source=%s (%s)",
                concept.id if concept else None,
                prerequisite.concept.id,
                prerequisite.source,
                prerequisite.reason,
            )
            deferred_id = concept.id if concept else None
            concept = prerequisite.concept
            score = scores.get(concept.id, 0)
        elif _steps_forward(move, learning, concept):
            # The prerequisite is secure, so go back to what they were on. A
            # tutor who steps back and never returns has changed the subject.
            resumed = store.get(deferred_id)
            if resumed is not None:
                logger.info("step_forward from=%s back to=%s", concept.id, resumed.id)
                concept = resumed
                score = scores.get(concept.id, 0)
                move = Move.ADVANCE
                deferred_id = None

        strategy = _strategy_for(move, learning, evaluation)
        check_item = _check_for_move(
            move,
            concept=concept,
            band=band,
            learning=learning,
            outstanding=outstanding,
            snapshot=snapshot,
            mastery=score,
        )

        # ── 4. prose and widget, started together ───────────────────────────
        context = TeachContext(
            concept=concept,
            band=band,
            locale=locale,
            move=move,
            persona=str(state.get("persona") or "stella"),
            supporting=tuple(resolution.kb_rows) or tuple(state.get("retrieved") or ()),
            check_item=check_item,
            hint=select_hint(outstanding, hint_level(snapshot)) if move is Move.HINT else None,
            mastered=tuple(learning.get("concepts_touched") or ())[-6:],
            prior_wrong=tuple(learning.get("prior_wrong_answers") or ()),
            utterance=utterance,
            voice=bool(state.get("voice")),
            recent_openings=tuple(learning.get("recent_openings") or ()),
            verdict=evaluation.feedback if move is Move.EVALUATE else "",
            approach=instruction_for(strategy) if move is Move.RETEACH else "",
            misconception=(
                evaluation.misconception if move is Move.CORRECT_MISCONCEPTION else ""
            ),
            correction=(
                _correction_for(concept, evaluation.misconception)
                if move is Move.CORRECT_MISCONCEPTION
                else ""
            ),
            answer=(outstanding.answer if move is Move.ANSWER and outstanding else ""),
            demonstrated=_demonstrated(learning, scores),
        )

        # A game IS the interactive thing this turn offers, so a widget beside
        # it would be two at once -- §4's "avoid overwhelming the learner".
        game = (
            _game_directive(move, concept, band, context.persona)
            if move is Move.GAME
            else None
        )

        # Created BEFORE the prose is awaited, which is the whole contract.
        widget_task = asyncio.create_task(
            build_widget(
                WidgetRequest(
                    concept=None if game else concept,
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
            # `render_teach` does not raise.
            widget_task.cancel()
            raise

        # ── 5. the lesson goes out. Nothing below can take it away. ─────────
        _emit_prose(lesson.spoken or lesson.text)

        # And this is what makes that sentence true rather than merely intended.
        try:
            widget = await _await_widget(widget_task)
            if widget.emitted:
                _emit_directive(widget.payload)
            if game is not None:
                _emit_directive(game)

            # ── 6. record what happened ─────────────────────────────────────
            after = await _record(
                mastery,
                state,
                concept=resolution.concept,
                evaluation=evaluation,
                hinted=snapshot.hint_rung > 0,
                band=band,
            )

            _log_turn(
                resolution=resolution,
                move=move,
                band=band,
                locale=locale,
                lesson=lesson,
                widget=widget,
                score=score,
                started=started,
                evaluation=evaluation,
                mastery_after=after,
                strategy=strategy,
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
                evaluation=evaluation,
                strategy=strategy,
                taught_concept=concept,
                deferred_id=deferred_id,
                utterance=utterance,
                game=game,
            )
        except Exception:
            logger.exception(
                "The lesson was delivered and the bookkeeping after it failed "
                "(concept=%s move=%s band=%s). Serving the lesson.",
                resolution.concept_id,
                move.value,
                band,
            )
            widget_task.cancel()
            # The minimum that keeps the turn coherent: what was said, and a way to reply.
            return {
                "messages": [AIMessage(content=lesson.text)],
                "quick_replies": _chips(band, _chip_options(move, band, str(state.get("locale") or "en"))),
            }

    return tutor


# ── the turn's decisions, each one small enough to test on its own ───────────


def _outstanding_check(
    concept: TeachingConcept | None, learning: dict[str, Any], band: str
) -> CheckItem | None:
    """The question the learner is answering, or None if none was asked.

    A check is outstanding only when one was actually put to them last turn.
    Grading a message against a question nobody asked is how a learner gets
    told they are wrong about something they were not answering.
    """
    if concept is None or not learning.get("awaiting_check_answer"):
        return None
    pending = learning.get("pending_check_id")
    if not pending:
        return None
    return next(
        (item for item in concept.checks_for(band) if item.id == pending), None
    )


async def _grade(
    utterance: str,
    *,
    item: CheckItem | None,
    concept: TeachingConcept | None,
    band: str,
    learning: dict[str, Any],
    grade: Any,
) -> Evaluation:
    """Grade the answer, or read the utterance for what it says about them.

    With no question outstanding there is nothing to mark, but "just tell me"
    and "I don't know" still mean what they mean, and the tutor should act on
    them either way.
    """
    if item is None:
        early = triage(utterance)
        if early in (Verdict.ASKS_FOR_ANSWER, Verdict.DONT_KNOW):
            return Evaluation(verdict=early, source="heuristic")
        return Evaluation()

    if sounds_confused(utterance) and triage(utterance) is None:
        # "I don't understand" is not an attempt at the question, and grading it
        # as one marks a learner wrong for admitting the explanation missed --
        # it is short, so it matches no accept term and reads as a bad answer.
        return Evaluation(verdict=Verdict.NOT_AN_ANSWER, source="heuristic")

    return await evaluate_answer(
        utterance, item=item, concept=concept, band=band, invoke=grade
    )


def _struggling(evaluation: Evaluation, *, confused: bool) -> bool:
    """Whether this turn is evidence of something not landing.

    Not being able to answer counts, even though it earns no mastery penalty:
    the question of whether a prerequisite is missing is a different question
    from whether this attempt was worth marking.
    """
    return confused or evaluation.verdict in (
        Verdict.WRONG,
        Verdict.PARTIAL,
        Verdict.DONT_KNOW,
    )


def _prerequisite(
    concept: TeachingConcept | None,
    *,
    band: str,
    locale: str,
    scores: dict[str, int],
    curriculum: Any,
) -> Prerequisite | None:
    """A weak prerequisite to step back to, or None. Never raises."""
    try:
        if curriculum is None:
            # Process-cached after the first call, so this is a dictionary lookup.
            from app.curriculum.schema import load_all

            curriculum = load_all()
        return find_prerequisite(
            concept,
            band=band,
            store=get_store(),
            mastery=scores,
            curriculum=curriculum,
            locale=locale,
        )
    except Exception:
        logger.debug("Prerequisite lookup failed.", exc_info=True)
        return None


def _steps_forward(
    move: Move, learning: dict[str, Any], concept: TeachingConcept | None
) -> bool:
    """Whether the prerequisite is done and the deferred concept can resume.

    The other half of §17. Stepping back to percentages is only useful if
    compound interest is still waiting when the learner gets there.
    """
    deferred = learning.get("deferred_concept_id")
    if not deferred or concept is None or deferred == concept.id:
        return False
    # ADVANCE means the scale says this concept is done; EVALUATE means they
    # just answered it correctly. Either is enough to go back up.
    return move in (Move.ADVANCE, Move.EVALUATE)


def _strategy_for(
    move: Move, learning: dict[str, Any], evaluation: Evaluation
) -> Strategy:
    """Which rung of the strategy ladder this turn stands on.

    A re-teach moves DOWN the ladder; anything else that explains starts it
    again, because a fresh concept is not a failed explanation.
    """
    current = str(learning.get("teaching_strategy") or "")
    if move is Move.RETEACH:
        return next_strategy(current, diagnosis=evaluation.diagnosis)
    if move in EXPLAINING_MOVES:
        return Strategy.DEFINITION
    try:
        return Strategy(current)
    except ValueError:
        return Strategy.DEFINITION


def _check_for_move(
    move: Move,
    *,
    concept: TeachingConcept | None,
    band: str,
    learning: dict[str, Any],
    outstanding: CheckItem | None,
    snapshot: LearnerSnapshot,
    mastery: int,
) -> CheckItem | None:
    """The question this turn ends with, or None when it ends with none.

    A hint keeps them on the question they are already answering; every other
    asking move picks the next one, at the difficulty §16 says they have earned.
    """
    if move not in ASKING_MOVES:
        return None
    if move is Move.HINT:
        return outstanding

    return select_check(
        concept,
        band=band,
        seen=list(learning.get("seen_check_ids") or []),
        difficulty=difficulty_for(
            mastery,
            wrong_on_concept=snapshot.wrong_on_concept,
            hinted=snapshot.hint_rung > 0,
        ),
    )


def _game_directive(
    move: Move, concept: TeachingConcept | None, band: str, persona: str | None = None
) -> dict[str, Any] | None:
    """The game this turn offers, through the existing launcher, or None.

    `plan_move` has been able to return GAME since Track L and nothing ever
    launched one, so the move rendered as another explanation. The launcher,
    the directive and the result channel all already exist; this is the call
    that was missing between them.
    """
    if move is not Move.GAME or concept is None:
        return None
    try:
        from app.agents.learn.tools.games import available_for, launch_game

        options = available_for(band, persona)
        if not options:
            return None
        return launch_game(options[-1], concept.id, age_band=band, persona=persona)
    except Exception:
        logger.warning("Could not launch a game; serving the prose alone.", exc_info=True)
        return None


def _correction_for(concept: TeachingConcept | None, wrong: str) -> str:
    """The `right` half of the authored misconception the learner is holding."""
    if concept is None or not wrong:
        return ""
    needle = wrong.strip().lower()
    for entry in concept.misconceptions:
        if entry.wrong.strip().lower() == needle:
            return entry.right
    # The grader paraphrased. Fall back to the closest authored pair by overlap.
    for entry in concept.misconceptions:
        if entry.wrong and needle and (entry.wrong.lower() in needle or needle in entry.wrong.lower()):
            return entry.right
    return ""


def _demonstrated(learning: dict[str, Any], scores: dict[str, int]) -> tuple[str, ...]:
    """Concepts this learner has answered correctly and unaided.

    §7's evidence, and the reason "beginner" is not a label the first message
    applies for the rest of the conversation.
    """
    from app.learning.concepts import get_store

    store = get_store()
    earned = [item for item in (learning.get("independent_correct") or []) if item]
    titles = []
    for concept_id in earned:
        if scores.get(concept_id, 0) < 1:
            continue
        concept = store.get(concept_id)
        titles.append(concept.title if concept else concept_id)
    return tuple(titles[-6:])


async def _record(
    mastery: Any,
    state: Any,
    *,
    concept: TeachingConcept | None,
    evaluation: Evaluation,
    hinted: bool,
    band: str,
) -> int:
    """Write what this turn demonstrated, and return the score after it.

    The half of the loop that did not exist. Without it the score stayed at
    zero however well the learner did, `Move.ADVANCE` was unreachable, and
    spaced repetition had nothing to schedule from.

    A bookkeeping failure is logged and swallowed: the lesson is already on
    screen and the learner does not lose it over a database.
    """
    if mastery is None or concept is None:
        return 0

    evidence = evidence_for(evaluation, hinted=hinted)
    if evidence is None:
        return 0

    try:
        from app.agents.learn.graph import _learner

        row = await mastery.record(
            _learner(state), concept.id, evidence, age_band=band
        )
        return int(getattr(row, "score", 0))
    except Exception:
        logger.warning(
            "Could not record mastery for concept %s.", concept.id, exc_info=True
        )
        return 0


# ── emission ─────────────────────────────────────────────────────────────────


def _writer() -> Any:
    """The custom-channel writer, or None outside a streaming run."""
    try:
        from langgraph.config import get_stream_writer

        return get_stream_writer()
    except Exception:
        return None


def _emit_prose(text: str) -> None:
    """The validated lesson, as prose the transport will tokenise."""
    writer = _writer()
    if writer is not None and text.strip():
        writer({"prose": text})


def _emit_directive(payload: dict[str, Any] | None) -> None:
    writer = _writer()
    if writer is not None and payload:
        writer({"directive": payload})


async def _await_widget(task: "asyncio.Task[WidgetOutcome]") -> WidgetOutcome:
    """Wait for the widget, briefly, and never let it matter."""
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
    """Nothing resolved."""
    text = decline_text(band, resolution.alternatives, str(state.get("locale") or "en"))
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
            # The offer above ends in a question, and its answer is a TOPIC.
            # Without this the reply fell through `_entry`'s claims -- a bare
            # concept title asks nothing and names no lesson -- into the phase
            # table, which sends `checking` to the curriculum `branch`. A
            # tutor-taught conversation has no lesson there to answer against,
            # so the turn ended having said nothing at all.
            awaiting_topic_choice=True,
        ),
    }


# ── state and logging ────────────────────────────────────────────────────────


def _lesson_citations(
    resolution: ConceptResolution, taught_concept: TeachingConcept | None
) -> dict[str, Any]:
    """Sources for a lesson, but only for the lessons that HAVE any.

    Most lessons are authored. The curriculum wrote them, retrieval only runs
    beside them to keep an amount current, and the prompt says in as many words
    never to quote or cite the rows -- so attaching a citation panel to one
    would claim a provenance the lesson does not have. §7's rule is that the
    sources must match the answer, and for an authored lesson the answer's
    source is the curriculum.

    The RAG-teach path is the exception and the reason this exists: no authored
    concept covered the question, `RAG_TEACH_ROLE` told the tutor to teach from
    the retrieved rows and nothing else, and that lesson genuinely came from the
    knowledge base. Those rows are cited, the same way and through the same
    machinery a Q&A answer's are.
    """
    if taught_concept is not None or resolution.concept is not None:
        return {}

    from app.agents.qa.nodes import citation_for
    from app.config import get_settings

    # Floor-checked per row, not per set. `resolve_concept` takes the RAG-teach
    # path when the BEST row clears `qa_relevance_floor`, and says nothing about
    # the rest -- so rows two and three can be far below it. Citing them would
    # put a source under a lesson they had no part in, which is the one thing a
    # citation may not do.
    floor = get_settings().qa_relevance_floor
    rows = [
        row
        for row in (resolution.kb_rows or ())
        if getattr(row, "kb_id", "")
        and max(getattr(row, "relevance", 0.0), getattr(row, "score", 0.0)) >= floor
    ]
    if not rows:
        return {}
    return {"citations": [citation_for(row) for row in rows[:CITATION_LIMIT]]}


#: How many rows a RAG-taught lesson may cite. Lower than Q&A's: a lesson draws
#: on background broadly, and a wall of references under a child's lesson is
#: noise rather than provenance.
CITATION_LIMIT = 3


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
    evaluation: Evaluation = Evaluation(),
    strategy: Strategy = Strategy.DEFINITION,
    taught_concept: TeachingConcept | None = None,
    deferred_id: str | None = None,
    utterance: str = "",
    game: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # What was TAUGHT, which a step back makes different from what was resolved.
    concept_id = (taught_concept.id if taught_concept else None) or resolution.concept_id
    asked = move in ASKING_MOVES and check_item is not None

    missed = evaluation.verdict in (Verdict.WRONG, Verdict.PARTIAL)
    # A hint climbs the ladder; anything else puts them on a new footing.
    rung = snapshot.hint_rung + 1 if move is Move.HINT else 0

    return {
        # The message is returned as well as emitted.
        "messages": [AIMessage(content=lesson.text)],
        "quick_replies": _chips(band, _chip_options(move, band, str(state.get("locale") or "en"))),
        **_lesson_citations(resolution, taught_concept),
        # The widget travels in STATE, not on the custom channel.
        #
        # `_emit_directive` writes it to the stream writer, and a subgraph's
        # custom writes never reach the transport -- `astream` only surfaces
        # them with `subgraphs=True`, which doubled every answer. `ui_directives`
        # merges into the main graph's state and `persist` publishes it with the
        # closing directives, which is the same path the cards use and the only
        # one measured to work. Emitting to the writer as well is harmless and
        # keeps a streaming deployment that does open the boundary correct.
        **(
            {"ui_directives": [payload for payload in (widget.payload, game) if payload]}
            if (widget.emitted or game)
            else {}
        ),
        "learning": merge(
            learning,
            phase="checking",
            active_concept_id=concept_id,
            resolution_source=resolution.source,
            resolution_similarity=resolution.similarity,
            move=move.value,
            concepts_touched=touched(learning, concept_id) if concept_id else learning.get("concepts_touched"),
            # A check was asked, so the next message is its answer.
            awaiting_check_answer=asked,
            # Something was taught, so any outstanding offer has been answered.
            awaiting_topic_choice=False,
            pending_check_id=check_item.id if asked else None,
            # A hint re-asks a question they have already met, so it is not
            # newly seen -- marking it seen would burn an item off the bank
            # every time the ladder ran.
            seen_check_ids=seen_check(
                learning, check_item.id if (asked and move is not Move.HINT) else None
            ),
            turns_on_concept=on_concept(learning, concept_id),
            turns_since_check=0 if asked else int(learning.get("turns_since_check") or 0) + 1,
            # ── what this turn demonstrated, so the next one can act on it ───
            #
            # `consecutive_wrong` is written here for the first time. It used to
            # be carried forward on a hint and zeroed everywhere else, which
            # meant it could never leave zero and `Move.HINT` was unreachable.
            consecutive_wrong=(
                snapshot.consecutive_wrong + 1
                if missed
                else 0
                if evaluation.verdict is Verdict.CORRECT
                else snapshot.consecutive_wrong
            ),
            wrong_by_concept=(
                wrong_again(learning, concept_id) if missed else learning.get("wrong_by_concept") or {}
            ),
            prior_wrong_answers=(
                [*(learning.get("prior_wrong_answers") or []), utterance.strip()][-4:]
                if missed and utterance.strip()
                else learning.get("prior_wrong_answers") or []
            ),
            misconceptions=(
                remember_misconception(learning, evaluation.misconception)
                if evaluation.misconception
                else learning.get("misconceptions") or []
            ),
            # §15: unaided and correct is a different rung from correct with help.
            independent_correct=(
                with_independent(learning, concept_id)
                if evaluation.verdict is Verdict.CORRECT and snapshot.hint_rung == 0
                else learning.get("independent_correct") or []
            ),
            last_verdict=evaluation.verdict.value,
            last_diagnosis=evaluation.diagnosis.value,
            teaching_strategy=strategy.value,
            hint_rung_now=rung,
            deferred_concept_id=deferred_id,
            # Read once, then spent. Leaving it set would reteach forever.
            reteach_pending=False,
            recent_openings=remember_opening(learning, lesson.text),
            last_widget_kinds=_remember_kind(learning, widget.kind if widget.emitted else None),
        ),
    }


def _remember_kind(learning: dict[str, Any], kind: str | None, *, keep: int = 3) -> list[str]:
    """Widget kinds recently SHOWN."""
    kinds = [item for item in (learning.get("last_widget_kinds") or []) if item]
    if kind:
        kinds.append(kind)
    return kinds[-keep:]


def _chip_options(move: Move, band: str, locale: str = "en") -> list[str]:
    """What to offer after this move, in the reader's language."""
    from app.prompting.ui_lines import chips

    if move is Move.HINT:
        return chips(["try_again", "tell_answer"], locale)
    if move is Move.EVALUATE:
        return chips(["next", "say_more"], locale)
    if move is Move.ANSWER:
        # They have the answer. What they need now is a chance to use it.
        return chips(["let_me_try", "got_it"], locale)
    if move in (Move.RETEACH, Move.CORRECT_MISCONCEPTION):
        # Never "Got it" first here -- they have just said it did not land.
        return chips(["that_helps", "still_stuck", "show_number"], locale)
    if move is Move.STEP_BACK:
        return chips(["okay", "go_back"], locale)
    if band == "5-8":
        return chips(["got_it", "say_it_again"], locale)
    return chips(["got_it", "say_more", "something_else"], locale)


def _chips(band: str, options: list[str]) -> list[str]:
    """Chips, capped at four and at four words each."""
    return [" ".join(option.split()[:4]) for option in options[:4]][:4]


async def _mastery_map(mastery: Any, state: Any) -> dict[str, int]:
    """Every concept this learner has a score on, read once.

    The whole map rather than one concept's score, because the prerequisite
    lookup needs to know how the concepts UNDERNEATH this one are going, and
    one round trip is cheaper than one per candidate.
    """
    if mastery is None:
        return {}
    try:
        from app.agents.learn.graph import _learner

        rows = await mastery.all_for(_learner(state))
        return {str(row.concept_id): int(row.score) for row in rows}
    except Exception:
        logger.debug("Could not read mastery.", exc_info=True)
        return {}


async def _mastery_of(mastery: Any, state: Any, concept: TeachingConcept | None) -> int:
    """This learner's score for this concept, or 0."""
    if concept is None:
        return 0
    return (await _mastery_map(mastery, state)).get(concept.id, 0)


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
    evaluation: Evaluation = Evaluation(),
    mastery_after: int = 0,
    strategy: Strategy = Strategy.DEFINITION,
) -> None:
    """One structured line per learning turn.

    §25. The teaching decisions are on the line beside the plumbing, because a
    tutor that adapts invisibly cannot be told from one that does not.
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
        mastery_after=max(mastery_after, score),
        total_ms=int((time.monotonic() - started) * 1000),
        verdict=evaluation.verdict.value,
        diagnosis=evaluation.diagnosis.value,
        evaluated_by=evaluation.source,
        misconception_detected=bool(evaluation.misconception),
        strategy=strategy.value,
    )

    logger.info(
        "learn_turn concept_id=%s resolution_source=%s similarity=%.3f move=%s band=%s "
        "locale=%s prose_words=%d teach_tier=%d teach_retry=%s teach_fallback=%s "
        "widget_kind=%s widget_gate_failed=%s widget_cache_hit=%s widget_latency_ms=%d "
        "verdict=%s diagnosis=%s evaluated_by=%s misconception_detected=%s strategy=%s "
        "mastery_before=%d mastery_after=%d escalated=False total_ms=%d",
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
        metrics.verdict,
        metrics.diagnosis,
        metrics.evaluated_by,
        metrics.misconception_detected,
        metrics.strategy,
        metrics.mastery_before,
        metrics.mastery_after,
        metrics.total_ms,
    )

    # Fire and forget.
    from app.learning.health import record

    asyncio.create_task(record(metrics))
