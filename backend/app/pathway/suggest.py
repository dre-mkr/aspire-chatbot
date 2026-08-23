"""What to offer the reader next -- one rung, or silence.

WHY THIS EXISTS
    The adaptive pathway is already in the product. `Concept.prerequisites` is
    the graph, `place_concept` and `due_concepts` walk it, `MasteryStore` knows
    where each learner stands on it, and every lesson is already written five
    times, once per band. All of it is invisible: nothing reads it to decide
    what to put in front of the reader at the end of a turn.

    So this is not an engine, a coach or an assessment. It is the read.

WHAT IT DOES NOT DO
    It never asks the reader how they learn. Every signal below is already
    recorded, on every turn, and none of it is read for this purpose today:

        row.widget_touches      hands-on -- lead with the allocator
        row.hinted_attempts     needs smaller steps
        row.wrong_streak        step back to the prerequisite
        row.score               ready to move on
        videos_offered          took a video, or did not
        concepts_touched        do not re-offer what was just covered

    A child who says "visual" and then plays four games has told us twice, and
    the second answer is the true one. Observed beats declared, and it is not
    close. It also costs nothing to collect, cannot be gamed, and needs no form
    in front of a reader who came here to ask a question.

RUNG SIX IS THE FEATURE
    `next_step` returns None on most turns. A suggester that always suggests is
    a nag, and a nag is what a thirteen-year-old closes. Every rung below has to
    earn its turn against silence.

WHERE IT RUNS
    `safety_out`, beside `offer_for`, which is where every turn converges no
    matter which agent answered it. The same five rules apply and are enforced
    here rather than assumed:

      - never on a turn that is already a card. A form is not also a suggestion.
      - never on a widget result or a graded game answer. That is a
        continuation, not a question.
      - never twice running for the same thing.
      - it takes a chip SLOT. Four is the wire cap and a fifth chip is a chip
        silently dropped.
      - it never changes what was said. The answer is capped, cited and
        stripped by the time this is asked.

PURE ON PURPOSE
    Everything is passed in. No database call, no `await`, no clock of its own.
    `safety_out` is on the path of every reply and is the wrong place to learn
    that the mastery store is slow today; a caller that has no rows passes none
    and gets the rungs that do not need them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any, Iterable, Mapping, Sequence

from app.learning.mastery import MasteryRow, is_due, mastered

logger = logging.getLogger(__name__)

#: Chips are also what gets SENT when tapped, so they are commands, not
#: sentences. `wants_video` and the widget router both refuse anything longer.
MAX_CHIP_WORDS = 4

#: A reader this far into a wrong streak is not helped by being moved forward.
STUCK_WRONG_STREAK = 2

#: Touches before the widget is read as a preference rather than an accident.
HANDS_ON_TOUCHES = 2


class Rung(IntEnum):
    """Which rung fired. Exactly one per turn, and six means none did.

    Ordered by how much the reader has already told us. The earlier rungs answer
    something observed about THIS learner; the later ones fall back to where
    they are in the course; the last one declines.
    """

    STUCK = 1
    DUE_FOR_REVIEW = 2
    HANDS_ON = 3
    CONTINUE = 4
    START = 5
    SILENCE = 6


@dataclass(frozen=True, slots=True)
class Suggestion:
    """One offer, and why it was made.

    `why` is not decoration. It is what makes this auditable in a log and in a
    demo: a suggester nobody can explain is a suggester nobody trusts, and the
    client will ask why a particular chip appeared.
    """

    rung: Rung
    chip: str
    concept_id: str | None = None
    lesson_id: str | None = None
    why: str = ""


def _is_a_turn_that_takes_no_suggestion(state: Mapping[str, Any]) -> str | None:
    """The reason this turn is not eligible, or None if it is."""
    flags = state.get("safety_flags") or {}
    if flags.get("card"):
        return "the turn is already a card"
    if any(flags.get(name) for name in ("widget_interaction", "game_result")):
        return "a continuation, not a question"
    if state.get("offered_video"):
        return "a video is already on offer"
    if state.get("suggested_step"):
        return "a step is already on offer"
    return None


def _rows_by_concept(mastery: Iterable[MasteryRow]) -> dict[str, MasteryRow]:
    return {row.concept_id: row for row in mastery}


def _chip(text: str) -> str | None:
    """A chip, or None if it is too long to survive the wire."""
    words = text.split()
    if not words or len(words) > MAX_CHIP_WORDS:
        logger.debug("pathway chip rejected as too long: %r", text)
        return None
    return " ".join(words)


def next_step(
    state: Mapping[str, Any],
    *,
    mastery: Sequence[MasteryRow] | None = None,
    lessons: Sequence[Any] | None = None,
    concept_names: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> Suggestion | None:
    """The one thing to offer at the end of this turn, or None.

    `lessons` is `curriculum.lessons_for_band(band)` -- passed in rather than
    loaded here, so this function has no opinion about where the curriculum
    lives and a test can hand it three lessons.

    `concept_names` maps a concept id to the short name a chip may use. Missing
    names are not fatal: a rung that cannot phrase itself declines, which is
    always a safe answer here.
    """
    blocked = _is_a_turn_that_takes_no_suggestion(state)
    if blocked:
        logger.debug("pathway: no suggestion -- %s", blocked)
        return None

    moment = now or datetime.now(timezone.utc)
    rows = _rows_by_concept(mastery or [])
    names = dict(concept_names or {})
    touched = set(state.get("concepts_touched") or [])

    def name_of(concept_id: str) -> str | None:
        return names.get(concept_id)

    # ── rung 1 · stuck ───────────────────────────────────────────────────────
    # Before anything else, because moving a stuck reader forward is the one
    # suggestion that makes things worse. Most overdue first is wrong here; most
    # recently wrong is the one they are still holding.
    stuck = sorted(
        (row for row in rows.values() if row.wrong_streak >= STUCK_WRONG_STREAK),
        key=lambda row: (row.last_seen or moment),
        reverse=True,
    )
    for row in stuck:
        short = name_of(row.concept_id)
        chip = _chip(f"Go back to {short}") if short else None
        if chip:
            return Suggestion(
                rung=Rung.STUCK,
                chip=chip,
                concept_id=row.concept_id,
                why=f"wrong {row.wrong_streak} times running on {row.concept_id}",
            )

    # ── rung 2 · due for review ──────────────────────────────────────────────
    # Spaced repetition, and the reason `next_due` is written at all. Skips
    # anything already covered this session: re-offering it reads as the
    # assistant not having noticed.
    due = sorted(
        (
            row
            for row in rows.values()
            if row.concept_id not in touched
            and row.next_due is not None
            and is_due(row, now=moment)
        ),
        key=lambda row: (row.next_due or moment, row.score),
    )
    for row in due:
        short = name_of(row.concept_id)
        chip = _chip(f"Practise {short}") if short else None
        if chip:
            return Suggestion(
                rung=Rung.DUE_FOR_REVIEW,
                chip=chip,
                concept_id=row.concept_id,
                why=f"{row.concept_id} came due at {row.next_due:%Y-%m-%d}",
            )

    # ── rung 3 · hands-on ────────────────────────────────────────────────────
    # The honest version of a learning-style question. This reader has reached
    # for the widget more than once, so offer the widget -- on a concept they
    # have not finished, and never as a way to redo something already mastered.
    hands_on = any(row.widget_touches >= HANDS_ON_TOUCHES for row in rows.values())
    if hands_on and lessons:
        for lesson in lessons:
            kind = getattr(lesson, "suggested_widget_kind", None)
            concept_id = getattr(lesson, "concept_id", None)
            if not kind or not concept_id or concept_id in touched:
                continue
            row = rows.get(concept_id)
            if row is not None and mastered(row):
                continue
            chip = _chip("Try it hands-on")
            if chip:
                return Suggestion(
                    rung=Rung.HANDS_ON,
                    chip=chip,
                    concept_id=concept_id,
                    lesson_id=getattr(lesson, "id", None),
                    why="this reader uses the widgets",
                )

    # ── rung 4 · continue ────────────────────────────────────────────────────
    # Course order, which IS the pathway: it fell out of the prerequisite graph
    # the moment somebody authored it, and a second scheme on top would be a
    # rival one disagreeing with the first.
    if lessons:
        for lesson in lessons:
            concept_id = getattr(lesson, "concept_id", None)
            if not concept_id or concept_id in touched:
                continue
            row = rows.get(concept_id)
            if row is not None and mastered(row):
                continue
            if not rows:
                # Nothing learned yet: that is rung 5's turn, not this one.
                break
            short = name_of(concept_id)
            chip = _chip(f"Next: {short}") if short else _chip("Carry on")
            if chip:
                return Suggestion(
                    rung=Rung.CONTINUE,
                    chip=chip,
                    concept_id=concept_id,
                    lesson_id=getattr(lesson, "id", None),
                    why="the next unmastered lesson in course order",
                )

    # ── rung 5 · start ───────────────────────────────────────────────────────
    # A reader with no rows at all. One offer, phrased as an invitation, and
    # only when there is something real to open.
    if not rows and lessons:
        chip = _chip("Start learning")
        first = lessons[0]
        if chip:
            return Suggestion(
                rung=Rung.START,
                chip=chip,
                concept_id=getattr(first, "concept_id", None),
                lesson_id=getattr(first, "id", None),
                why="nothing recorded for this learner yet",
            )

    # ── rung 6 · silence ─────────────────────────────────────────────────────
    # Not a fallback. The usual answer.
    logger.debug("pathway: rung 6, nothing to offer")
    return None
