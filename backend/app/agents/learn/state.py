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
    #: The primitive `plan_widget` chose for the teaching turn about to run,
    #: or None. Set on one node and consumed on the next, then cleared -- see
    #: `teach.make_teach` on why leaving it set composes the widget twice.
    pending_widget: str | None
    #: How each recent teaching turn began, so the next one can begin
    #: differently. See `teach._avoid` for why openings rather than whole
    #: messages. Per CONVERSATION -- this state is checkpointed per thread.
    recent_openings: list[str]
    #: Whether this learner has a mastery row for the concept being taught.
    #:
    #: The one repetition signal that crosses sessions, because mastery is the
    #: only thing about a learner that outlives the checkpoint. Set by
    #: `resume_or_place`, which has already loaded the rows.
    concept_seen_before: bool
    #: How many times each lesson id has been taught in this thread.
    #:
    #: Spaced repetition is meant to bring a concept back, so a returning
    #: learner meets the same lesson two and three times by design. The count
    #: is what lets the teaching turn know it is a repeat.
    teach_count: dict[str, int]
    #: Concepts due for review, folded into this lesson's checks.
    review_concepts: list[str]
    #: The learner row this session writes mastery against.
    learner_id: str | None
    #: Set once `wrap_session` has emitted its progress directive, so a resumed
    #: graph does not emit a second one.
    wrapped: bool

    # ── topic resolution (Track L) ──────────────────────────────────────────
    #
    # The lesson machine above places by SCHEDULE -- what this learner is due.
    # The fields below carry what they ASKED FOR, which the machine had no
    # representation of at all: `resume_or_place` chose the next unmastered
    # lesson whatever the message said, so "What is compound interest?" was
    # answered with a lesson about saving. See `resolve.py`.

    #: The concept this turn is about, from `resolve_concept`. Distinct from
    #: `lesson_id`: a lesson is an authored sequence, a concept is one idea, and
    #: a learner asking a question has named the second and not the first.
    active_concept_id: str | None
    #: How it was resolved: continuation | semantic | disambiguated | rag | none.
    #: Logged on every turn -- the RATE of "none" is the product's blind-spot
    #: metric, and it is invisible from any single turn.
    resolution_source: str
    #: The cosine similarity behind that decision, for threshold calibration.
    resolution_similarity: float
    #: Which move `plan_move` chose. Recorded rather than recomputed, so a
    #: checkpoint says what the turn actually did.
    move: str
    #: A check question is outstanding and the next message is its answer. The
    #: single most important bit in this state: without it a bare "20" is read
    #: as a new knowledge query.
    awaiting_check_answer: bool
    #: Which item from the concept's bank is outstanding.
    pending_check_id: str | None
    #: Check ids this learner has already seen, so the bank is not repeated
    #: before it is exhausted.
    seen_check_ids: list[str]
    #: Consecutive wrong answers on the current concept. Drives the hint rung
    #: and, at zero, means the ladder is not running.
    consecutive_wrong: int
    #: What they actually answered, so a later turn can avoid re-explaining what
    #: they already got right and can name what they got wrong.
    prior_wrong_answers: list[str]
    #: Turns spent on each concept this session. Drives the switch to a game.
    turns_on_concept: dict[str, int]
    #: Turns since a check question was last asked.
    turns_since_check: int


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
        pending_widget=None,
        recent_openings=[],
        concept_seen_before=False,
        teach_count={},
        review_concepts=[],
        learner_id=learner_id,
        wrapped=False,
        active_concept_id=None,
        resolution_source="none",
        resolution_similarity=0.0,
        move="",
        awaiting_check_answer=False,
        pending_check_id=None,
        seen_check_ids=[],
        consecutive_wrong=0,
        prior_wrong_answers=[],
        turns_on_concept={},
        turns_since_check=0,
    )


def on_concept(state: LearningState, concept_id: str | None) -> dict[str, int]:
    """The per-concept turn counter, incremented for this one.

    Per concept rather than per session, because the thing being counted is "how
    long have we been on THIS idea" -- the trigger for offering a game instead of
    a fifth paragraph. A session counter would fire on the fifth turn of a session
    that had covered four different concepts, which is exactly when a learner is
    doing well.
    """
    counts = dict(state.get("turns_on_concept") or {})
    if concept_id:
        counts[concept_id] = counts.get(concept_id, 0) + 1
    return counts


def seen_check(state: LearningState, check_id: str | None, *, keep: int = 40) -> list[str]:
    """Check ids this learner has met, most recent last.

    Bounded, because this rides in a checkpoint on every turn and an unbounded
    list of ids is a checkpoint that grows without limit over a long-running
    conversation. Forty is more than any concept's bank holds, so the cap can
    only ever discard an id from a concept the learner has long since left.
    """
    seen = [item for item in (state.get("seen_check_ids") or []) if item]
    if check_id and check_id not in seen:
        seen.append(check_id)
    return seen[-keep:]


#: The band used when neither the resolved context nor the turn state has one.
#:
#: One constant, in one place. Track C.2 removed eight copies of
#: `str(state.get("age_band") or "9-12")` from this agent -- in `graph.py`,
#: three times in `teach.py`, and in each of `explain_back`, `hint_ladder` and
#: `widget_result` (twice). Eight copies of a default is eight chances for one of
#: them to be edited alone, and `teach._cap` had already diverged: it fell back
#: to a 120-word cap, which is the 13-15 allowance, for a learner the other seven
#: sites were treating as 9-12.
FALLBACK_BAND = "9-12"


def band_of(state: Any) -> str:
    """This learner's age band: the resolved context first, then turn state.

    The context is preferred because `resolve_context` built it from the claims
    `hydrate` validated against the signed token, before routing, once. Turn
    state carries the same value and is the fallback for a node driven directly
    in a test, or a turn where `resolve_context` did not run.
    """
    context = state.get("context")
    band = getattr(context, "age_band", None) if context is not None else None
    return str(band or state.get("age_band") or FALLBACK_BAND)


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


#: How many words of a teaching turn count as its opening.
#:
#: Eight is about a sentence's worth at these bands, which is the unit
#: repetition is actually heard in. Storing the whole message instead would put
#: three full paragraphs in the next prompt and invite the model to differ from
#: all of them -- including in the parts that were right.
OPENING_WORDS = 8


def remember_opening(state: LearningState, text: str, *, keep: int = 3) -> list[str]:
    """The recent teaching openings, newest last, capped.

    Deduplicated on the way in. A repeat that got through is exactly the thing
    the next prompt most needs to see, and seeing it twice in a list of three
    crowds out the two other angles already tried.
    """
    recent = list(state.get("recent_openings") or [])
    opening = " ".join((text or "").split()[:OPENING_WORDS]).strip()
    if opening and opening not in recent:
        recent.append(opening)
    return recent[-keep:]


def taught_again(state: LearningState, lesson_id: str) -> dict[str, int]:
    """`teach_count` with this lesson's tally incremented."""
    counts = dict(state.get("teach_count") or {})
    if lesson_id:
        counts[lesson_id] = counts.get(lesson_id, 0) + 1
    return counts


def merge(state: Any, **changes: Any) -> LearningState:
    """A learning state with `changes` applied, tolerating None.

    `AspireState.learning` starts as None, and every node would otherwise open
    with the same three-line guard.
    """
    base: LearningState = dict(state) if state else new_session()  # type: ignore[assignment]
    base.update(changes)
    return base
