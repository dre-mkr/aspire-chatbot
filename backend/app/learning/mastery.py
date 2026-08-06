"""What counts as evidence that a child has learned something.

The scale is four values and the transitions are five rules. Both are short on
purpose: this is the number that decides what a child is taught next, and a
scoring system nobody can hold in their head is a scoring system nobody
notices going wrong.

    0 unseen | 1 exposed | 2 practised | 3 mastered

    widget interaction        →  0 to 1 only. NEVER above 1.
    correct check, no hints   →  +1
    correct after hints       →  no change
    wrong twice               →  -1, floor 0
    explain_back accepted     →  +1, cap 3

## The rule that matters: a widget is exposure, not mastery

A child can move a slider forty times. It is engagement, it is often the moment
the idea lands, and it is not evidence that they hold it -- because moving a
slider requires no recall, no articulation and no decision. If widget
interaction could raise mastery, the fastest route to every badge in the product
would be to drag things, and children optimise for badges faster than adults
expect.

So `WIDGET` saturates at 1. `apply` enforces it as a hard ceiling on that
transition rather than as a "+1 with a cap", which is a distinction that
matters when a concept is already at 2: a widget touch must not move it to 3,
and must not move it *down* either.

## Down is possible, and gentle

Two wrong attempts costs a point, floored at 0. It has to be possible -- a
scale that only rises stops meaning anything after a fortnight -- and it has to
be small, because the child never sees it and the only effect they experience
is the concept coming back round sooner.
"""

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

#: How many wrong attempts before a point is lost. Matches the hint ladder's
#: hard cap: the third attempt does not happen, so "wrong twice" is the most
#: that can be observed.
WRONG_ATTEMPTS_TO_DROP = 2


class Evidence(str, Enum):
    """What was observed. One value per transition rule, and no others."""

    WIDGET = "widget_interaction"
    CORRECT = "correct_no_hints"
    CORRECT_AFTER_HINTS = "correct_after_hints"
    WRONG = "wrong"
    EXPLAINED = "explain_back_accepted"
    #: A game result. Deliberately mapped to exposure, never to mastery: a game
    #: score is a mix of understanding, reading speed and luck, and letting one
    #: push a concept to 3 would make the scale mean "played a game".
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
    """The new standing after one piece of evidence.

    Pure, and takes `now` rather than reading the clock, so a scheduling
    decision made last Tuesday can be re-derived exactly. A function that reads
    `datetime.now()` cannot be tested at a boundary and cannot be explained to a
    parent asking why a concept came back.
    """
    moment = now or datetime.now(timezone.utc)
    score = row.score
    attempts = row.attempts
    hinted = row.hinted_attempts
    touches = row.widget_touches
    wrong_streak = row.wrong_streak

    if evidence in (Evidence.WIDGET, Evidence.GAME):
        touches += 1
        # A CEILING, not an increment. At 0 this lifts to 1; at 2 it leaves the
        # score alone. Writing it as `min(score + 1, 1)` would silently DROP a
        # concept already at 2 or 3 back to 1, which is the same bug in the
        # opposite direction.
        score = max(score, WIDGET_CEILING) if score <= WIDGET_CEILING else score

    elif evidence is Evidence.CORRECT:
        attempts += 1
        wrong_streak = 0
        score = min(score + 1, MAX_SCORE)

    elif evidence is Evidence.CORRECT_AFTER_HINTS:
        attempts += 1
        hinted += 1
        wrong_streak = 0
        # No change. They arrived, and they arrived with help -- which is
        # exposure to the idea rather than evidence they hold it.

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
#:
#: 1, 3, 7, 21 -- roughly doubling-and-a-bit, which is the shape every spaced
#: repetition schedule converges on. Something unseen (0) comes back tomorrow;
#: something mastered (3) comes back in three weeks to check it stayed.
INTERVAL_DAYS: dict[int, int] = {0: 1, 1: 3, 2: 7, 3: 21}


def due_after(score: int, moment: datetime) -> datetime:
    """When a concept at this score should resurface."""
    days = INTERVAL_DAYS.get(max(MIN_SCORE, min(score, MAX_SCORE)), 1)
    return moment + timedelta(days=days)


def is_due(row: MasteryRow, *, now: datetime | None = None) -> bool:
    """Whether this concept should come back round.

    A row that has never been seen is due. That is what makes placement work
    without a separate "unseen" query: a new learner's concepts are all due,
    and the scheduler simply orders them.
    """
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
    #: The real ASPIRE event that earns it, where there is one. Badges tied to
    #: something that happened at a branch mean more than badges tied to app
    #: activity -- a child showing a parent "I got this for my first deposit" is
    #: a different conversation from "I got this for opening the app".
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
    """Whether this id can be written to `mastery.learner_id`, a UUID column.

    Asked by `PostgresMasteryStore` only. The in-memory store keys on whatever
    string it is given and is right to -- its ids are test ids and session ids,
    and inventing a UUID requirement for a dict would break every test that
    writes `"learner-1"`.

    What this guards is the boundary. The graph used to derive a learner as
    `user_id or session_id or "anonymous"` and hand the result straight to
    asyncpg; a session id is not a UUID, asyncpg raised, the exception escaped
    the node, and a child who had moved a slider was told the assistant was
    unavailable. Falling back to memory keeps the turn's arithmetic correct and
    writes nothing, which is the honest outcome for a learner with no account.
    """
    if not learner_id:
        return False
    try:
        uuid.UUID(str(learner_id))
    except (TypeError, ValueError):
        return False
    return True


# ── the store ────────────────────────────────────────────────────────────────


class MasteryStore:
    """Persistence for mastery rows, with an in-memory default.

    The in-memory implementation is not a test double -- it is what a
    deployment without a database uses, and it is what `learning_sample` uses
    for an anonymous visitor who has no learner row to write to. A lesson that
    refuses to run without Postgres would be a lesson nobody without an account
    can try.
    """

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], MasteryRow] = {}

    async def get(self, learner_id: str, concept_id: str) -> MasteryRow:
        return self._rows.get((learner_id, concept_id), MasteryRow(concept_id=concept_id))

    async def put(
        self, learner_id: str, row: MasteryRow, *, age_band: str = "9-12"
    ) -> None:
        # `age_band` is accepted and ignored. The Postgres store needs it to
        # create the learner row; in memory there is no learner row to create,
        # and the two stores must take the same arguments or `record` cannot
        # call either.
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
        """Read, apply, write. The only method callers should need.

        `learner_id` may be None, and that is a supported turn rather than a
        caller mistake: an anonymous visitor playing with a widget in
        `learning_sample` has no account for a mastery row to belong to.
        Nothing is written, the in-memory result is returned so the caller's
        arithmetic still works, and the turn proceeds.

        This used to take a fallback string -- the session id, or the literal
        "anonymous" -- and hand it to a UUID column. asyncpg rejected it
        (`invalid UUID 'wi-anonymous'`), the exception escaped `widget_result`,
        and the whole turn died with "the assistant is temporarily unavailable"
        for a child who had done nothing but move a slider.
        """
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
    """The same interface, against the `mastery` table.

    Falls back to the in-memory rows whenever there is no session, rather than
    raising. A lesson interrupted by a database blip should carry on and lose
    the scoring, not stop mid-sentence in front of a child.
    """

    async def get(self, learner_id: str, concept_id: str) -> MasteryRow:
        from sqlalchemy import text as sql

        from app.db import session

        # A learner id that is not a UUID cannot be a `mastery.learner_id`, so
        # it is served from memory rather than handed to asyncpg to raise on.
        # See `is_persistable`.
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

            # The learner row first, because `mastery.learner_id` references it
            # and NOTHING ELSE CREATES ONE. Without this every mastery write for
            # a signed-in child raised `mastery_learner_id_fkey`, which killed
            # the node and made the whole C4 track -- mastery, scheduling,
            # spaced repetition -- unreachable in production. Found by running a
            # widget interaction, not by a test: the tests use the in-memory
            # store, which has no foreign keys to violate.
            #
            # `id` IS the account's uuid rather than a fresh one. `learners.id`
            # defaults to `gen_random_uuid()` and carries a nullable `user_id`,
            # so the schema allows either -- but every caller in the graph
            # passes `state["user_id"]` as the learner, and giving the two
            # different values would mean a lookup table nobody consults and a
            # class of bug where mastery is written under an id no reader knows.
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
