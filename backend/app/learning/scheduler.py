"""What to teach next, and which old concepts to fold back in.

Two jobs, and they are deliberately not the same function:

  * **Placement** picks the lesson. It resumes an interrupted one, otherwise
    fills the earliest gap, otherwise moves on.
  * **Review selection** picks concepts that are due and threads them into the
    lesson that is already happening.

## There is no drill mode, and there will not be one

Due concepts resurface INSIDE later checks and games -- a lesson about budgets
asks a question that happens to need "goal" again. They never appear as a
separate "revision" screen.

That is the difference between a product a child opens and one they avoid. A
drill is visibly a test; a check question inside a lesson is the lesson. The
retention mechanic is identical either way, and only one of them gets used.

## Resumption is time-boxed at 48 hours

Inside the window, a half-finished lesson picks up where it stopped. Outside it,
the child has forgotten the setup and being dropped into the middle of an
explanation is worse than starting the lesson again -- so the lesson restarts
from its first teach point, keeping the mastery that was earned.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.curriculum.schema import Curriculum, Lesson
from app.learning.mastery import MasteryRow, is_due, mastered

logger = logging.getLogger(__name__)

#: How long an interrupted lesson stays resumable.
RESUME_WINDOW = timedelta(hours=48)

#: How many due concepts one lesson may fold in. Two, because a check that
#: revisits three earlier ideas is a quiz, and this is meant to be invisible.
MAX_REVIEWS_PER_LESSON = 2

#: Session length. `wrap_session` triggers at the SOFT limit if a natural
#: stopping point has been reached, and at the HARD limit regardless -- but only
#: ever between nodes, never mid-explanation.
SOFT_LIMIT = timedelta(minutes=8)
TARGET_LIMIT = timedelta(minutes=12)
HARD_LIMIT = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class Placement:
    """Where this session starts, and why.

    `reason` is carried so a trace answers "why is she being taught this?"
    without re-deriving the decision -- which is the first question anybody asks
    when placement looks wrong.
    """

    lesson: Lesson | None
    reason: str
    resumed: bool = False


def place(
    curriculum: Curriculum,
    band: str,
    mastery: list[MasteryRow],
    *,
    last_lesson_id: str | None = None,
    last_seen_at: datetime | None = None,
    covered_this_session: set[str] | None = None,
    now: datetime | None = None,
) -> Placement:
    """Which lesson this learner starts with.

    Three rungs, in order:

      1. Resume, if a lesson was interrupted within `RESUME_WINDOW`.
      2. Fill the earliest gap -- the first band-appropriate lesson whose
         concept is not yet mastered AND has not already been covered in this
         session.
      3. Nothing left, which is a real outcome and not an error.

    Note rung 2 walks the course in order rather than picking the lowest score.
    Curriculum order encodes prerequisites; jumping to whichever concept scored
    worst would teach "budget" to a child who has not met "goal".

    `covered_this_session` is what stops a child who got a lesson wrong from
    being taught the same lesson immediately again, forever. A wrong answer
    does not raise mastery, so without it "first unmastered lesson" is the one
    that was just revealed and the session loops. The reveal already retaught
    it; the concept comes back through spaced repetition, tomorrow, when it will
    land better.
    """
    moment = now or datetime.now(timezone.utc)
    covered = covered_this_session or set()

    if last_lesson_id and last_seen_at:
        if moment - last_seen_at <= RESUME_WINDOW:
            lesson = curriculum.lessons.get(last_lesson_id)
            if lesson is not None and lesson.concept_id not in covered:
                return Placement(lesson, "resumed within 48 hours", resumed=True)
        else:
            logger.info(
                "Not resuming %s: last seen %s ago, past the %s window.",
                last_lesson_id,
                moment - last_seen_at,
                RESUME_WINDOW,
            )

    by_concept = {row.concept_id: row for row in mastery}
    for lesson in curriculum.lessons_for_band(band):
        if lesson.concept_id in covered:
            continue
        row = by_concept.get(lesson.concept_id)
        if row is None or not mastered(row):
            return Placement(lesson, "first unmastered lesson in course order")

    if covered:
        return Placement(None, "everything left was already covered this session")
    return Placement(None, "every band-appropriate lesson is mastered")


def due_concepts(
    mastery: list[MasteryRow],
    *,
    exclude: set[str] | None = None,
    now: datetime | None = None,
    limit: int = MAX_REVIEWS_PER_LESSON,
) -> list[str]:
    """Concepts to fold into this lesson's checks, most overdue first.

    `exclude` is normally the lesson's own concept -- reviewing what is being
    taught right now is not review, it is the lesson.

    A concept with no `next_due` (never seen) is NOT returned. It is due in the
    placement sense and is handled by `place`; returning it here would fold an
    unmet concept into a check as though it were revision.
    """
    moment = now or datetime.now(timezone.utc)
    skip = exclude or set()

    candidates = [
        row
        for row in mastery
        if row.concept_id not in skip and row.next_due is not None and is_due(row, now=moment)
    ]
    candidates.sort(key=lambda row: (row.next_due or moment, row.score))
    return [row.concept_id for row in candidates[:limit]]


def should_wrap(
    started_at: datetime,
    *,
    at_natural_break: bool,
    lesson_complete: bool,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Whether to end the session, and what to say it was.

    The ordering is the whole of it. A lesson that finishes at six minutes ends
    at six minutes -- the point is not to fill twelve. Past the soft limit, the
    session ends at the next natural break rather than immediately. Past the
    hard limit it ends at the next break regardless of whether the break feels
    natural, because fifteen minutes is the ceiling.

    What it never does is end mid-explanation: every caller only consults this
    BETWEEN nodes, and `at_natural_break` is the caller saying so.
    """
    elapsed = (now or datetime.now(timezone.utc)) - started_at

    if lesson_complete:
        return True, "lesson complete"
    if not at_natural_break:
        return False, "mid-explanation"
    if elapsed >= HARD_LIMIT:
        return True, "hard limit"
    if elapsed >= TARGET_LIMIT:
        return True, "target session length"
    if elapsed >= SOFT_LIMIT:
        return True, "natural break past the soft limit"
    return False, "still going"


def streak_after(
    previous_streak: int,
    last_session_at: datetime | None,
    *,
    now: datetime | None = None,
) -> int:
    """The streak once today's session is counted.

    Same day: unchanged -- two sessions on Tuesday are one day. Next day: +1.
    A gap: back to 1, not to 0, because today's session did happen and a child
    who came back deserves to see that rather than a zero.
    """
    moment = now or datetime.now(timezone.utc)
    if last_session_at is None:
        return 1

    gap = moment.date() - last_session_at.date()
    if gap.days == 0:
        return max(previous_streak, 1)
    if gap.days == 1:
        return previous_streak + 1
    return 1
