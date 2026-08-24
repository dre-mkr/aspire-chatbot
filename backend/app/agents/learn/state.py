"""What a lesson in progress is made of."""

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

#: Hard caps.
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
    #: Wrong answers on the CURRENT question.
    attempts: int
    #: Which rung of the hint ladder was last given, 0 meaning none.
    hint_rung: int
    #: CONSECUTIVE off-curriculum turns.
    digression_count: int
    session_started_at: str
    #: Concepts this session has touched, for the wrap-up summary.
    concepts_touched: list[str]
    #: Which widget kinds have been shown recently, so the planner varies the primitive.
    last_widget_kinds: list[str]
    #: The primitive `plan_widget` chose for the teaching turn about to run, or None.
    pending_widget: str | None
    #: How each recent teaching turn began, so the next one can begin differently.
    recent_openings: list[str]
    #: Whether this learner has a mastery row for the concept being taught.
    concept_seen_before: bool
    #: How many times each lesson id has been taught in this thread.
    teach_count: dict[str, int]
    #: Concepts due for review, folded into this lesson's checks.
    review_concepts: list[str]
    #: The learner row this session writes mastery against.
    learner_id: str | None
    #: Set once `wrap_session` emitted its progress directive, so a resume emits no second one.
    wrapped: bool

    # ── topic resolution ──────────────────────────────────────────────────

    #: The concept this turn is about, from `resolve_concept`.
    active_concept_id: str | None
    #: How it was resolved: continuation | semantic | disambiguated | rag | none.
    resolution_source: str
    #: The cosine similarity behind that decision, for threshold calibration.
    resolution_similarity: float
    #: Which move `plan_move` chose.
    move: str
    #: A check question is outstanding and the next message is its answer.
    awaiting_check_answer: bool
    #: The tutor resolved nothing and offered concepts instead, so the next
    #: message is the learner picking one. It is a TOPIC, not a check answer,
    #: and only the tutor can resolve it -- see `graph._entry`.
    awaiting_topic_choice: bool
    #: Which item from the concept's bank is outstanding.
    pending_check_id: str | None
    #: Check ids this learner has already seen, so the bank is not repeated before it is exhausted.
    seen_check_ids: list[str]
    #: Consecutive wrong answers on the current concept.
    consecutive_wrong: int
    #: The wrong answers themselves, so a later turn can address the mistake, not just repeat.
    prior_wrong_answers: list[str]
    #: Turns spent on each concept this session. Drives the switch to a game.
    turns_on_concept: dict[str, int]
    #: Turns since a check question was last asked.
    turns_since_check: int

    # ── the teaching loop's own memory ──────────────────────────────────────── Everything below is written by `evalu…

    #: How the last explanation was PUT ACROSS, from `strategy.Strategy`. A
    #: second failure moves down the ladder rather than round it.
    teaching_strategy: str
    #: The last verdict, from `evaluate.Verdict`.
    last_verdict: str
    #: The last diagnosis, from `evaluate.Diagnosis`.
    last_diagnosis: str
    #: Misconceptions this learner has demonstrated, as the concept authored
    #: them, most recent last. The evidence behind `RETEACH` and the reason a
    #: repeated conceptual error is treated differently from a repeated slip.
    misconceptions: list[str]
    #: How many times each concept has been answered wrongly, across the session.
    wrong_by_concept: dict[str, int]
    #: The concept a step back interrupted. Cleared when the tutor returns to
    #: it, which is what stops a step back from silently changing the subject.
    deferred_concept_id: str | None
    #: Something outside the conversation showed this has not landed -- a poor
    #: game score, say. Read once by the next teaching turn and then cleared.
    reteach_pending: bool
    #: Which rung of assistance has been given on the outstanding question, 0
    #: being none. Climbs on each hint and resets on any other move, because a
    #: new question -- or a new explanation -- is a fresh piece of scaffolding.
    hint_rung_now: int
    #: Whether the learner has ever answered a check on the active concept
    #: without needing a hint first. The difference between §15's "correct with
    #: support" and "correct independently".
    independent_correct: list[str]


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
        awaiting_topic_choice=False,
        pending_check_id=None,
        seen_check_ids=[],
        consecutive_wrong=0,
        prior_wrong_answers=[],
        turns_on_concept={},
        turns_since_check=0,
        teaching_strategy="",
        last_verdict="",
        last_diagnosis="",
        misconceptions=[],
        wrong_by_concept={},
        deferred_concept_id=None,
        reteach_pending=False,
        hint_rung_now=0,
        independent_correct=[],
    )


def remember_misconception(state: LearningState, wrong: str, *, keep: int = 8) -> list[str]:
    """The demonstrated misconceptions, most recent last, without duplicates.

    A repeat moves to the end rather than being dropped: the same wrong model
    surfacing twice is the signal §13 exists to catch, and it should read as
    the most recent thing this learner did.
    """
    held = [item for item in (state.get("misconceptions") or []) if item]
    text = (wrong or "").strip()
    if not text:
        return held[-keep:]
    held = [item for item in held if item != text]
    held.append(text)
    return held[-keep:]


def wrong_again(state: LearningState, concept_id: str | None) -> dict[str, int]:
    """`wrong_by_concept` with this concept's tally incremented."""
    counts = dict(state.get("wrong_by_concept") or {})
    if concept_id:
        counts[concept_id] = counts.get(concept_id, 0) + 1
    return counts


def with_independent(state: LearningState, concept_id: str | None) -> list[str]:
    """`independent_correct` with this concept added once."""
    earned = [item for item in (state.get("independent_correct") or []) if item]
    if concept_id and concept_id not in earned:
        earned.append(concept_id)
    return earned


def on_concept(state: LearningState, concept_id: str | None) -> dict[str, int]:
    """The per-concept turn counter, incremented for this one."""
    counts = dict(state.get("turns_on_concept") or {})
    if concept_id:
        counts[concept_id] = counts.get(concept_id, 0) + 1
    return counts


def seen_check(state: LearningState, check_id: str | None, *, keep: int = 40) -> list[str]:
    """Check ids this learner has met, most recent last."""
    seen = [item for item in (state.get("seen_check_ids") or []) if item]
    if check_id and check_id not in seen:
        seen.append(check_id)
    return seen[-keep:]


#: The band used when neither the resolved context nor the turn state has one.
FALLBACK_BAND = "9-12"


#: Learning agents whose turns are watched rather than taken, and score nobody.
#:
#: Defined here rather than in `graph`, because `band_of` below has to consult it
#: and `graph` already imports this module -- the other direction would be a
#: cycle. `graph` re-exports it under the same name.
NON_SCORING_AGENTS: frozenset[str] = frozenset({"learning_preview", "learning_sample"})


def band_of(state: Any) -> str:
    """The band this turn should be WRITTEN at.

    Usually the reader's own. Not always: a parent asking to see the lesson her
    nine-year-old would get is asking for a band that is not hers, and before
    `preview_band` existed there was no way to say so. `_band` read the reader
    every time, so she asked for a nine-year-old's lesson and got a
    fourteen-year-old's question -- adult falls back through 16-18 to 13-15, and
    that is the content she was shown.

    Honoured ONLY for a non-scoring agent. That is the safety property, and it
    is structural rather than a rule written beside the code: `learn_agent`
    never consults it, so nothing a real learner can type moves their own band,
    their own caps or their own vocabulary ladder. A preview is a window; it is
    not a way in.
    """
    preview = state.get("preview_band")
    if preview and str(state.get("active_agent") or "") in NON_SCORING_AGENTS:
        return str(preview)

    context = state.get("context")
    band = getattr(context, "age_band", None) if context is not None else None
    return str(band or state.get("age_band") or FALLBACK_BAND)


def started_at(state: LearningState) -> datetime:
    """When this session began, as an aware datetime."""
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
    """The recent widget kinds, newest last, capped."""
    recent = list(state.get("last_widget_kinds") or [])
    if kind:
        recent.append(kind)
    return recent[-keep:]


#: How many words of a teaching turn count as its opening.
OPENING_WORDS = 8


def remember_opening(state: LearningState, text: str, *, keep: int = 3) -> list[str]:
    """The recent teaching openings, newest last, capped."""
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
    """A learning state with `changes` applied, tolerating None."""
    base: LearningState = dict(state) if state else new_session()  # type: ignore[assignment]
    base.update(changes)
    return base
