"""What a lesson in progress is made of.

Lives in `AspireState.learning` and is None whenever the learning agent is not
running. That is not tidiness -- it is what stops a registration turn from
being able to read or write a child's lesson position.

## `phase` is the state machine

    resume_or_place → teach → check → (game | hint | reteach | explain_back)
                        ↑                          │
                        └──────────────────────────┘
                                    │
                          mastery_update → next_lesson | wrap

The node that runs next is decided from `phase` and nothing else, so a trace
that shows the phase shows the whole machine. `attempts` and `digression_count`
are counters with hard caps, and both caps are behavioural promises rather than
guards: two wrong answers before the reveal, two consecutive digressions before
the line is held.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, TypedDict

#: Every phase the lesson machine can be in.
Phase = Literal[
    "placing",
    "teaching",
    "checking",
    "hinting",
    "reteaching",
    "explaining_back",
    "playing",
    "updating_mastery",
    "wrapping",
    "done",
]

#: Hard caps. Both are promises to a child rather than defensive limits.
#:
#: `MAX_ATTEMPTS = 3` is the ladder counted in misses: the first gets a nudge,
#: the second a narrowing to two options, the third the reveal. There is no
#: fourth, which is the promise -- two failures *after* being helped is where a
#: child starts concluding something about themselves.
MAX_ATTEMPTS = 3
MAX_DIGRESSIONS = 2
MAX_HINT_RUNG = 3


class LearningState(TypedDict, total=False):
    """One lesson in progress."""

    module_id: str | None
    lesson_id: str | None
    #: Which check question within the lesson.
    question_id: str | None
    phase: Phase
    #: Wrong answers on the CURRENT question. Reset on every new question.
    #: Capped at `MAX_ATTEMPTS` -- there is no third attempt.
    attempts: int
    #: Which rung of the hint ladder was last given, 0 meaning none.
    hint_rung: int
    #: CONSECUTIVE off-curriculum turns. Reset by any on-topic turn, which is
    #: what makes "two in a row" mean two in a row rather than two ever.
    digression_count: int
    session_started_at: str
    #: Concepts this session has touched, for the wrap-up summary.
    concepts_touched: list[str]
    #: Which widget kinds have been shown recently, so the planner does not
    #: emit the same primitive three turns running.
    last_widget_kinds: list[str]
    #: Concepts due for review, folded into this lesson's checks.
    review_concepts: list[str]
    #: The learner row this session writes mastery against.
    learner_id: str | None
    #: Set once `wrap_session` has emitted its progress directive, so a resumed
    #: graph does not emit a second one.
    wrapped: bool


def new_session(*, learner_id: str | None = None, now: datetime | None = None) -> LearningState:
    """A fresh lesson state. Every field populated, none left to a `.get` default."""
    moment = now or datetime.now(timezone.utc)
    return LearningState(
        module_id=None,
        lesson_id=None,
        question_id=None,
        phase="placing",
        attempts=0,
        hint_rung=0,
        digression_count=0,
        session_started_at=moment.isoformat(),
        concepts_touched=[],
        last_widget_kinds=[],
        review_concepts=[],
        learner_id=learner_id,
        wrapped=False,
    )


def started_at(state: LearningState) -> datetime:
    """When this session began, as an aware datetime.

    Stored as an ISO string because the whole `AspireState` is checkpointed as
    JSON, and a datetime that round-trips through JSON as a string and back as
    a string is a subtraction that raises three turns later.
    """
    raw = state.get("session_started_at")
    if not raw:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.now(timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def touched(state: LearningState, concept_id: str) -> list[str]:
    """`concepts_touched` with `concept_id` added once."""
    seen = list(state.get("concepts_touched") or [])
    if concept_id and concept_id not in seen:
        seen.append(concept_id)
    return seen


def remember_widget(state: LearningState, kind: str | None, *, keep: int = 3) -> list[str]:
    """The recent widget kinds, newest last, capped.

    Three is enough for the planner's "do not repeat the same primitive three
    turns running" rule and short enough that a kind becomes available again
    within a lesson.
    """
    recent = list(state.get("last_widget_kinds") or [])
    if kind:
        recent.append(kind)
    return recent[-keep:]


def merge(state: Any, **changes: Any) -> LearningState:
    """A learning state with `changes` applied, tolerating None.

    `AspireState.learning` starts as None, and every node would otherwise open
    with the same three-line guard.
    """
    base: LearningState = dict(state) if state else new_session()  # type: ignore[assignment]
    base.update(changes)
    return base
