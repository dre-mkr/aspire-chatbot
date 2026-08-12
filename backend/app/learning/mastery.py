"""What counts as evidence that a child has learned something."""

from __future__ import annotations

import uuid

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

logger = logging.getLogger(__name__)

MIN_SCORE = 0
MAX_SCORE = 3

#: The ceiling a widget interaction may raise a concept to. Not a step size.
WIDGET_CEILING = 1

#: How many wrong attempts before a point is lost.
WRONG_ATTEMPTS_TO_DROP = 2


class Evidence(str, Enum):
    """What was observed. One value per transition rule, and no others."""

    WIDGET = "widget_interaction"
    CORRECT = "correct_no_hints"
    CORRECT_AFTER_HINTS = "correct_after_hints"
    WRONG = "wrong"
    EXPLAINED = "explain_back_accepted"
    #: A game result.
    GAME = "game_completed"


@dataclass(frozen=True, slots=True)
class MasteryRow:
    """One learner's standing on one concept."""

    concept_id: str
    score: int = 0
    attempts: int = 0
    hinted_attempts: int = 0
    widget_touches: int = 0
    wrong_streak: int = 0
    last_seen: datetime | None = None
    next_due: datetime | None = None


def apply(row: MasteryRow, evidence: Evidence, *, now: datetime | None = None) -> MasteryRow:
    """The new standing after one piece of evidence."""
    moment = now or datetime.now(timezone.utc)
    score = row.score
    attempts = row.attempts
    hinted = row.hinted_attempts
    touches = row.widget_touches
    wrong_streak = row.wrong_streak

    if evidence in (Evidence.WIDGET, Evidence.GAME):
        touches += 1
        # A CEILING, not an increment.
        score = max(score, WIDGET_CEILING) if score <= WIDGET_CEILING else score

    elif evidence is Evidence.CORRECT:
        attempts += 1
        wrong_streak = 0
        score = min(score + 1, MAX_SCORE)

    elif evidence is Evidence.CORRECT_AFTER_HINTS:
        attempts += 1
        hinted += 1
        wrong_streak = 0
        # No change.

    elif evidence is Evidence.WRONG:
        attempts += 1
        wrong_streak += 1
        if wrong_streak >= WRONG_ATTEMPTS_TO_DROP:
            score = max(score - 1, MIN_SCORE)
            wrong_streak = 0

    elif evidence is Evidence.EXPLAINED:
        attempts += 1
        wrong_streak = 0
        score = min(score + 1, MAX_SCORE)

    return MasteryRow(
        concept_id=row.concept_id,
        score=score,
        attempts=attempts,
        hinted_attempts=hinted,
        widget_touches=touches,
        wrong_streak=wrong_streak,
        last_seen=moment,
        next_due=due_after(score, moment),
    )


# ── spaced repetition ────────────────────────────────────────────────────────

#: Days until a concept is due again, by score.
INTERVAL_DAYS: dict[int, int] = {0: 1, 1: 3, 2: 7, 3: 21}


def due_after(score: int, moment: datetime) -> datetime:
    """When a concept at this score should resurface."""
    days = INTERVAL_DAYS.get(max(MIN_SCORE, min(score, MAX_SCORE)), 1)
    return moment + timedelta(days=days)


def is_due(row: MasteryRow, *, now: datetime | None = None) -> bool:
    """Whether this concept should come back round."""
    if row.next_due is None:
        return True
    return (now or datetime.now(timezone.utc)) >= row.next_due


def mastered(row: MasteryRow) -> bool:
    return row.score >= MAX_SCORE


# ── badges ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Badge:
    id: str
    name: str
    #: The real ASPIRE event that earns it, where there is one.
    milestone: str | None = None


BADGES: dict[str, Badge] = {
    "first_deposit": Badge(
        "first_deposit", "First Deposit", milestone="account.first_deposit"
    ),
    "first_hundred": Badge(
        "first_hundred", "First EC$100 Saved", milestone="account.balance_10000"
    ),
    "goal_reached": Badge(
        "goal_reached", "Goal Reached", milestone="account.goal_met"
    ),
    # App-activity badges exist, and are deliberately the minority.
    "first_lesson": Badge("first_lesson", "First Lesson"),
    "five_day_streak": Badge("five_day_streak", "Five Days in a Row"),
    "module_complete": Badge("module_complete", "Module Finished"),
}


def badge_for_streak(streak: int) -> Badge | None:
    return BADGES["five_day_streak"] if streak == 5 else None


# ── who owns a mastery row ───────────────────────────────────────────────────


def is_persistable(learner_id: str | None) -> bool:
    """Whether this id can be written to `mastery.learner_id`, a UUID column."""
    if not learner_id:
        return False
    try:
        uuid.UUID(str(learner_id))
    except (TypeError, ValueError):
        return False
    return True


# ── the store ────────────────────────────────────────────────────────────────


class MasteryStore:
    """Persistence for mastery rows, with an in-memory default."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], MasteryRow] = {}

    async def get(self, learner_id: str, concept_id: str) -> MasteryRow:
        return self._rows.get((learner_id, concept_id), MasteryRow(concept_id=concept_id))

    async def put(
        self, learner_id: str, row: MasteryRow, *, age_band: str = "9-12"
    ) -> None:
        # `age_band` is accepted and ignored.
        self._rows[(learner_id, row.concept_id)] = row

    async def all_for(self, learner_id: str) -> list[MasteryRow]:
        return [
            row
            for (owner, _concept), row in self._rows.items()
            if owner == learner_id
        ]

    async def record(
        self,
        learner_id: str | None,
        concept_id: str,
        evidence: Evidence,
        *,
        now: datetime | None = None,
        age_band: str = "9-12",
    ) -> MasteryRow:
        """Read, apply, write."""
        if not learner_id:
            row = apply(MasteryRow(concept_id=concept_id), evidence, now=now)
            logger.info(
                "mastery not recorded for an anonymous learner: concept=%s %s",
                concept_id,
                evidence.value,
            )
            return row

        row = await self.get(learner_id, concept_id)
        updated = apply(row, evidence, now=now)
        await self.put(learner_id, updated, age_band=age_band)
        logger.info(
            "mastery learner=%s concept=%s %s: %d -> %d (due %s)",
            learner_id,
            concept_id,
            evidence.value,
            row.score,
            updated.score,
            updated.next_due.date() if updated.next_due else "-",
        )
        return updated


class PostgresMasteryStore(MasteryStore):
    """The same interface, against the `mastery` table."""

    async def get(self, learner_id: str, concept_id: str) -> MasteryRow:
        from sqlalchemy import text as sql

        from app.db import session

        # A non-UUID learner id cannot be a `mastery.learner_id`, so it is served from memory.
        if not is_persistable(learner_id):
            return await super().get(learner_id, concept_id)

        async with session() as db:
            if db is None:
                return await super().get(learner_id, concept_id)
            row = (
                await db.execute(
                    sql(
                        """
                        SELECT score_0_3, attempts, hinted_attempts,
                               widget_touches, last_seen, next_due
                        FROM mastery
                        WHERE learner_id = :learner AND concept_id = :concept
                        """
                    ),
                    {"learner": learner_id, "concept": concept_id},
                )
            ).first()

        if row is None:
            return MasteryRow(concept_id=concept_id)
        return MasteryRow(
            concept_id=concept_id,
            score=row[0],
            attempts=row[1],
            hinted_attempts=row[2],
            widget_touches=row[3],
            last_seen=row[4],
            next_due=row[5],
        )

    async def put(
        self, learner_id: str, row: MasteryRow, *, age_band: str = "9-12"
    ) -> None:
        from sqlalchemy import text as sql

        from app.db import session

        if not is_persistable(learner_id):
            await super().put(learner_id, row)
            return

        async with session() as db:
            if db is None:
                await super().put(learner_id, row)
                return

            # The learner row first: `mastery.learner_id` references it, and nothing else makes it.
            await db.execute(
                sql(
                    """
                    INSERT INTO learners (id, user_id, age_band)
                    VALUES (CAST(:learner AS uuid), :learner, :band)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"learner": learner_id, "band": age_band},
            )

            await db.execute(
                sql(
                    """
                    INSERT INTO mastery (
                        learner_id, concept_id, score_0_3, attempts,
                        hinted_attempts, widget_touches, last_seen, next_due
                    ) VALUES (
                        :learner, :concept, :score, :attempts,
                        :hinted, :touches, :last_seen, :next_due
                    )
                    ON CONFLICT (learner_id, concept_id) DO UPDATE SET
                        score_0_3 = EXCLUDED.score_0_3,
                        attempts = EXCLUDED.attempts,
                        hinted_attempts = EXCLUDED.hinted_attempts,
                        widget_touches = EXCLUDED.widget_touches,
                        last_seen = EXCLUDED.last_seen,
                        next_due = EXCLUDED.next_due
                    """
                ),
                {
                    "learner": learner_id,
                    "concept": row.concept_id,
                    "score": row.score,
                    "attempts": row.attempts,
                    "hinted": row.hinted_attempts,
                    "touches": row.widget_touches,
                    "last_seen": row.last_seen,
                    "next_due": row.next_due,
                },
            )
            await db.commit()
