"""What to teach next, and which old concepts to fold back in."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.curriculum.schema import Curriculum, Lesson
from app.learning.mastery import MasteryRow, is_due, mastered

logger = logging.getLogger(__name__)

#: How long an interrupted lesson stays resumable.
RESUME_WINDOW = timedelta(hours=48)

#: How many due concepts one lesson may fold in.
MAX_REVIEWS_PER_LESSON = 2

#: Session length.
SOFT_LIMIT = timedelta(minutes=8)
TARGET_LIMIT = timedelta(minutes=12)
HARD_LIMIT = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class Placement:
    """Where this session starts, and why."""

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
    """Which lesson this learner starts with."""
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
    """Concepts to fold into this lesson's checks, most overdue first."""
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
    """Whether to end the session, and what to say it was."""
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
    """The streak once today's session is counted."""
    moment = now or datetime.now(timezone.utc)
    if last_session_at is None:
        return 1

    gap = moment.date() - last_session_at.date()
    if gap.days == 0:
        return max(previous_streak, 1)
    if gap.days == 1:
        return previous_streak + 1
    return 1
