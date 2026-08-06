"""The lesson machine.

    resume_or_place → teach → check → branch
                       ↑                │
                       │   got_it / partial / lost
                       │      │        │       │
                       │    game   hint_ladder reteach
                       │      │        │       │
                       └──────┴────────┴───────┘
                                  │
                        mastery_update → next_lesson | wrap_session

Every path in that diagram ends at `mastery_update`, and that is the property
worth stating: there is no way to answer a check question -- rightly, wrongly,
with hints, by playing a game -- that does not record what happened.

## Open-ended chat is not the mode

A lesson is a sequence of nodes with quick replies at every step. A child CAN
type -- the input is never removed -- but the primary interaction is tapping,
and every node that speaks emits chips. `safety_out` enforces that as a
backstop; these nodes generate them properly rather than relying on the
re-prompt, because a re-prompt costs a model call and produces chips that were
not authored.

## Digressions

An off-curriculum question gets a real answer in at most two sentences, then a
warm steer back: "Good question! Now -- back to our snow cone money." Two
consecutive digressions is the cap; after that the line is held, still warmly.

The cap counts CONSECUTIVE digressions and any on-topic turn resets it. A child
who asks two questions, does a lesson step, then asks another has not used up
anything.

## Sessions end at a natural break

`should_wrap` is only ever consulted between nodes, so a session cannot end
mid-explanation. Eight to twelve minutes is the target and fifteen is the
ceiling; a lesson that finishes in six minutes ends in six.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from app.agents.learn.nodes.explain_back import make_explain_back
from app.agents.learn.nodes.hint_ladder import make_hint_ladder
from app.agents.learn.state import (
    MAX_ATTEMPTS,
    MAX_DIGRESSIONS,
    merge,
    new_session,
    remember_widget,
    started_at,
    touched,
)
from app.curriculum.schema import CheckQuestion, Lesson, for_band, load_all
from app.graph.state import AspireState
from app.learning import scheduler
from app.learning.mastery import Evidence, MasteryStore
from app.schemas.directives import ProgressDirective

logger = logging.getLogger(__name__)


def _band(state: AspireState) -> str:
    return str(state.get("age_band") or "9-12")


def _lesson(curriculum, learning: dict) -> Lesson | None:
    return curriculum.lessons.get(learning.get("lesson_id") or "")


def _question(lesson: Lesson, learning: dict) -> CheckQuestion | None:
    wanted = learning.get("question_id")
    graded = [q for q in lesson.check_questions if q.graded]
    if wanted:
        found = next((q for q in lesson.check_questions if q.id == wanted), None)
        if found is not None:
            return found
    return graded[0] if graded else None


# ── resume_or_place ──────────────────────────────────────────────────────────


def make_resume_or_place(curriculum=None, store: MasteryStore | None = None):
    """Resume inside 48 hours, else fill the earliest gap, else say we are done."""

    async def resume_or_place(state: AspireState) -> dict[str, Any]:
        book = curriculum or load_all()
        rows = await (store or MasteryStore()).all_for(_learner(state))
        learning = state.get("learning") or new_session(learner_id=_learner(state))

        if learning.get("lesson_id") and learning.get("phase") not in (None, "placing", "done"):
            # Already mid-lesson within this session. Nothing to place.
            return {"learning": learning}

        placement = scheduler.place(
            book,
            _band(state),
            rows,
            last_lesson_id=learning.get("lesson_id"),
            last_seen_at=max((row.last_seen for row in rows if row.last_seen), default=None),
            # A wrong answer does not raise mastery, so without this the
            # lesson just revealed is still "the first unmastered one" and the
            # session teaches it again immediately, forever. The reveal already
            # retaught it; spaced repetition brings it back tomorrow.
            covered_this_session=set(learning.get("concepts_touched") or []),
        )
        logger.info(
            "placement session=%s -> %s (%s)",
            state.get("session_id"),
            placement.lesson.id if placement.lesson else None,
            placement.reason,
        )

        if placement.lesson is None:
            return {
                "messages": [AIMessage(content=_all_done(_band(state)))],
                "quick_replies": _chips(_band(state), ["Play a game", "Ask a question"]),
                "learning": merge(learning, phase="done"),
            }

        return {
            "learning": merge(
                learning,
                module_id=placement.lesson.module_id,
                lesson_id=placement.lesson.id,
                question_id=None,
                phase="teaching",
                attempts=0,
                hint_rung=0,
                review_concepts=scheduler.due_concepts(
                    rows, exclude={placement.lesson.concept_id}
                ),
            )
        }

    return resume_or_place


def _learner(state: AspireState) -> str | None:
    """The learner this session writes mastery against, or None for nobody.

    None for an anonymous visitor, and that is the honest answer rather than a
    refusal. `mastery.learner_id` is a UUID referencing an account; a
    `learning_sample` visitor has none, so there is no row for their progress to
    live in and nothing for it to mean when they come back.

    This used to fall back to the session id, reasoning that a sample session
    should "score normally for its own length". It does -- the hint ladder and
    the reply arithmetic run on the turn's own state and never touch the
    database. What the fallback actually did was hand a non-UUID string to
    asyncpg, which raised, killed the node, and told a child who had moved a
    slider that the assistant was unavailable.

    `MasteryStore.record` accepts None and returns the applied row without
    writing, so every caller's arithmetic is unchanged.
    """
    user_id = state.get("user_id")
    return str(user_id) if user_id else None


# ── teach ────────────────────────────────────────────────────────────────────


def make_teach(curriculum=None):
    """Say the teach points for this band, then hand over to the check."""

    def teach(state: AspireState) -> dict[str, Any]:
        book = curriculum or load_all()
        learning = state.get("learning") or {}
        lesson = _lesson(book, learning)
        if lesson is None:  # pragma: no cover - routing guards this
            return {}

        band = _band(state)
        points = lesson.teach_for(band)
        examples = lesson.examples_for(band)

        # One example, not all of them. A lesson that lists four examples of the
        # same idea is a lesson that has stopped teaching and started padding --
        # and the length cap would truncate it anyway, at whichever sentence it
        # happened to reach.
        body = " ".join(points[:2])
        if examples:
            body = f"{body} {examples[0]}"

        return {
            "messages": [AIMessage(content=body.strip())],
            "quick_replies": _chips(band, ["Got it", "Say that again"]),
            "learning": merge(
                learning,
                phase="checking",
                concepts_touched=touched(learning, lesson.concept_id),
                last_widget_kinds=remember_widget(
                    learning, lesson.suggested_widget_kind
                ),
            ),
        }

    return teach


# ── check ────────────────────────────────────────────────────────────────────


def make_check(curriculum=None):
    """Ask the check question, with its options as quick replies."""

    def check(state: AspireState) -> dict[str, Any]:
        book = curriculum or load_all()
        learning = state.get("learning") or {}
        lesson = _lesson(book, learning)
        if lesson is None:  # pragma: no cover
            return {}

        question = _question(lesson, learning)
        if question is None:
            return {"learning": merge(learning, phase="updating_mastery")}

        band = _band(state)
        prompt = for_band(question.prompt, band) or next(iter(question.prompt.values()))

        return {
            "messages": [AIMessage(content=prompt)],
            # The options ARE the interaction. Generated here rather than left
            # to `safety_out`'s re-prompt, which would cost a model call and
            # produce chips nobody authored.
            "quick_replies": list(question.options) or _chips(band, ["Tell me"]),
            "learning": merge(learning, question_id=question.id, phase="checking"),
        }

    return check


# ── the branch after an answer ───────────────────────────────────────────────


def grade_answer(question: CheckQuestion, answer: str) -> bool:
    """Whether the child got it. Deterministic, in Python.

    Not a model call, and the reason is the hint ladder: a rung count only
    means something if "wrong" is decided the same way every time. A model that
    grades leniently on Tuesday gives a child two nudges for the same answer
    that got them a reveal on Monday.
    """
    text = (answer or "").strip().lower()
    if not text:
        return False
    if question.answer is not None and question.options:
        correct = question.options[question.answer].strip().lower()
        if text == correct or correct in text:
            return True
        # A tapped chip sends the option text; a typed answer might be the
        # option's first word, or its index.
        if text in {str(question.answer), str(question.answer + 1)}:
            return True
        return False
    return any(word.lower() in text for word in question.accept)


def make_branch(curriculum=None):
    """Decide what happens after the child answers.

    Three outcomes and a fourth that is not an outcome at all:

      got_it   -> a game if one fits, otherwise straight to mastery
      partial  -> the hint ladder
      lost     -> the hint ladder, which reveals on the second miss
      digressed-> answer briefly, steer back, do not count it as an attempt
    """

    def branch(state: AspireState) -> dict[str, Any]:
        book = curriculum or load_all()
        learning = state.get("learning") or {}
        lesson = _lesson(book, learning)
        if lesson is None:  # pragma: no cover
            return {}

        flags = state.get("safety_flags") or {}
        if flags.get("off_topic"):
            return _digress(state, learning, lesson)

        question = _question(lesson, learning)
        if question is None:  # pragma: no cover
            return {"learning": merge(learning, phase="updating_mastery")}

        from app.graph.nodes.safety_in import latest_user_text

        correct = grade_answer(question, latest_user_text(state))
        attempts = int(learning.get("attempts") or 0)

        if correct:
            return {
                "learning": merge(
                    learning,
                    phase="updating_mastery",
                    # An on-topic turn clears the digression run.
                    digression_count=0,
                    outcome="correct_after_hints" if attempts else "correct",
                )
            }

        attempts += 1
        return {
            "learning": merge(
                learning,
                attempts=min(attempts, MAX_ATTEMPTS),
                digression_count=0,
                phase="hinting",
                outcome="wrong",
            )
        }

    return branch


def _digress(state: AspireState, learning: dict, lesson: Lesson) -> dict[str, Any]:
    """Answer the off-topic question briefly, then steer back.

    Two sentences at most, then the steer. The steer names what they were doing
    -- "back to our snow cone money" -- because "let's get back on track" is a
    reprimand and naming the thing is an invitation.

    Past the cap the line is held, still warmly. Note what "held" means here: it
    is one more friendly sentence and the same question again, not a refusal.
    """
    band = _band(state)
    count = int(learning.get("digression_count") or 0) + 1
    example = (lesson.examples_for(band) or ["what we were doing"])[0]
    subject = example.split(".")[0][:60]

    if count > MAX_DIGRESSIONS:
        text = {
            "5-8": f"Ooh, let us hold that one for the end! Back to {subject}.",
            "9-12": f"Good one -- keep it for the end. For now, back to {subject}.",
            "13-15": f"Worth coming back to. Let us finish this first: {subject}.",
        }.get(band, "Let us finish this first.")
    else:
        text = {
            "5-8": f"Good question! Now -- back to {subject}.",
            "9-12": f"Good question! Right, back to {subject}.",
            "13-15": f"Fair question. Now, back to {subject}.",
        }.get(band, "Good question! Now, back to what we were doing.")

    return {
        "messages": [AIMessage(content=text)],
        "quick_replies": _chips(band, ["Okay", "Ask again later"]),
        "learning": merge(
            learning,
            digression_count=count,
            # NOT an attempt. A child asking a question has not answered wrongly,
            # and counting it would run the hint ladder on curiosity.
            phase="checking",
        ),
    }


# ── reteach ──────────────────────────────────────────────────────────────────


def make_reteach(curriculum=None):
    """After the reveal: explain why, then move on. No further attempt."""

    def reteach(state: AspireState) -> dict[str, Any]:
        book = curriculum or load_all()
        learning = state.get("learning") or {}
        lesson = _lesson(book, learning)
        if lesson is None:  # pragma: no cover
            return {}

        band = _band(state)
        points = lesson.teach_for(band)
        body = points[-1] if points else lesson.objective

        return {
            "messages": [AIMessage(content=body)],
            "quick_replies": _chips(band, ["Got it", "Next"]),
            "learning": merge(learning, phase="updating_mastery", outcome="wrong"),
        }

    return reteach


# ── mastery_update ───────────────────────────────────────────────────────────

#: What the branch recorded, mapped to the evidence the scale understands.
_EVIDENCE = {
    "correct": Evidence.CORRECT,
    "correct_after_hints": Evidence.CORRECT_AFTER_HINTS,
    "wrong": Evidence.WRONG,
    "widget": Evidence.WIDGET,
    "game": Evidence.GAME,
}


def make_mastery_update(curriculum=None, store: MasteryStore | None = None):
    """Record the evidence, then decide whether to continue or wrap.

    The only writer of mastery in the product. `main_graph.persist` deliberately
    does not recompute it -- two writers for one row is how two subsystems come
    to disagree about what a child has learned.
    """

    async def mastery_update(state: AspireState) -> dict[str, Any]:
        book = curriculum or load_all()
        rows = store or MasteryStore()
        learning = state.get("learning") or {}
        lesson = _lesson(book, learning)
        if lesson is None:  # pragma: no cover
            return {}

        outcome = learning.get("outcome")
        if learning.get("explain_accepted"):
            evidence = Evidence.EXPLAINED
        else:
            evidence = _EVIDENCE.get(str(outcome or ""), Evidence.WIDGET)

        await rows.record(_learner(state), lesson.concept_id, evidence)

        wrap, why = scheduler.should_wrap(
            started_at(learning),
            at_natural_break=True,
            lesson_complete=evidence
            in (Evidence.CORRECT, Evidence.EXPLAINED, Evidence.CORRECT_AFTER_HINTS),
        )
        return {
            "learning": merge(
                learning,
                phase="wrapping" if wrap else "placing",
                attempts=0,
                hint_rung=0,
                question_id=None,
                outcome=None,
                explain_accepted=None,
                wrap_reason=why,
            )
        }

    return mastery_update


# ── wrap_session ─────────────────────────────────────────────────────────────


def make_wrap_session(store: MasteryStore | None = None):
    """End at a natural stopping point, with a progress directive.

    Never mid-explanation: this node is only reachable from `mastery_update`,
    which is between steps by construction.
    """

    async def wrap_session(state: AspireState) -> dict[str, Any]:
        learning = state.get("learning") or {}
        band = _band(state)
        rows = await (store or MasteryStore()).all_for(_learner(state))
        touched_ids = list(learning.get("concepts_touched") or [])

        moved = sum(1 for row in rows if row.concept_id in touched_ids and row.score > 0)
        streak = scheduler.streak_after(
            int(state.get("streak") or 0),
            max((row.last_seen for row in rows if row.last_seen), default=None),
        )

        from app.learning.mastery import badge_for_streak

        badge = badge_for_streak(streak)
        directive = ProgressDirective(
            badge=badge.id if badge else None,
            streak=streak,
            mastery_delta=moved,
        )

        return {
            "messages": [AIMessage(content=_wrap_text(band, moved))],
            "quick_replies": _chips(band, ["Play a game", "See you tomorrow"]),
            "ui_directives": [directive],
            "learning": merge(learning, phase="done", wrapped=True),
        }

    return wrap_session


def _wrap_text(band: str, moved: int) -> str:
    if band == "5-8":
        return "That was great work today. Come back tomorrow and we will do more!"
    if band == "9-12":
        return f"Good session -- you worked on {moved} idea{'s' if moved != 1 else ''}. Same time tomorrow?"
    return f"Nice work. You covered {moved} concept{'s' if moved != 1 else ''} today."


def _all_done(band: str) -> str:
    if band == "5-8":
        return "You have finished all our lessons! You are a saving expert."
    return "You have worked through everything available for your level. Well done."


def _chips(band: str, options: list[str]) -> list[str]:
    """Chips, capped at four and at four words each.

    Trimmed here rather than left to `safety_out`, because a chip that arrives
    too long triggers a re-prompt -- a model call to fix something the author
    could simply have written shorter.
    """
    return [" ".join(option.split()[:4]) for option in options[:4]]


# ── routing ──────────────────────────────────────────────────────────────────


def _after_place(state: AspireState) -> str:
    learning = state.get("learning") or {}
    return {"teaching": "teach", "done": END}.get(str(learning.get("phase")), END)


def _after_check(state: AspireState) -> str:
    """The graph pauses here on a real turn, waiting for the child's answer.

    On a resumed turn -- the child has replied -- `phase` is still `checking`
    and there IS a new human message, so `branch` runs. The distinction is the
    message count, not the phase, because the phase is what the previous turn
    left behind.
    """
    return END


def _after_branch(state: AspireState) -> str:
    learning = state.get("learning") or {}
    phase = str(learning.get("phase"))
    if phase == "hinting":
        return "hint_ladder"
    if phase == "updating_mastery":
        return "explain_back"
    return END


def _after_hint(state: AspireState) -> str:
    learning = state.get("learning") or {}
    return "reteach" if learning.get("phase") == "reteaching" else END


def _after_explain(state: AspireState) -> str:
    learning = state.get("learning") or {}
    return "mastery_update" if learning.get("phase") == "updating_mastery" else END


def _after_mastery(state: AspireState) -> str:
    learning = state.get("learning") or {}
    return "wrap_session" if learning.get("phase") == "wrapping" else "resume_or_place"


def _entry(state: AspireState) -> str:
    """Where this turn starts, from the phase the last one left behind.

    A lesson spans many turns and langgraph runs the graph once per turn, so
    the entry point IS the resumption logic. Reading it from `phase` rather
    than from an interrupt keeps the machine legible: the phase in a checkpoint
    tells you exactly which node runs next.
    """
    # A widget interaction or a game result is a TURN and it jumps the queue.
    # The agent must answer it referencing the child's own numbers, in this
    # turn -- so it runs before the lesson machine resumes wherever it was.
    flags = state.get("safety_flags") or {}
    if flags.get("widget_interaction"):
        return "widget_result"
    if flags.get("game_result"):
        return "game_result"

    learning = state.get("learning") or {}
    phase = str(learning.get("phase") or "placing")
    return {
        "placing": "resume_or_place",
        "teaching": "teach",
        "checking": "branch",
        "hinting": "hint_ladder",
        "reteaching": "reteach",
        "explaining_back": "explain_back",
        "updating_mastery": "mastery_update",
        "wrapping": "wrap_session",
        "done": "resume_or_place",
    }.get(phase, "resume_or_place")


def build_learn_graph(*, curriculum=None, store: MasteryStore | None = None):
    graph = StateGraph(AspireState)

    graph.add_node("resume_or_place", make_resume_or_place(curriculum, store))
    graph.add_node("teach", make_teach(curriculum))
    graph.add_node("check", make_check(curriculum))
    graph.add_node("branch", make_branch(curriculum))
    graph.add_node("hint_ladder", make_hint_ladder(curriculum))
    graph.add_node("reteach", make_reteach(curriculum))
    graph.add_node("explain_back", make_explain_back(curriculum))
    graph.add_node("mastery_update", make_mastery_update(curriculum, store))
    graph.add_node("wrap_session", make_wrap_session(store))

    from app.agents.learn.nodes.widget_result import make_widget_result
    from app.agents.learn.tools.games import make_game_result_node

    graph.add_node("widget_result", make_widget_result(store))
    graph.add_node("game_result", make_game_result_node(store))

    graph.add_conditional_edges(
        START,
        _entry,
        [
            "resume_or_place",
            "teach",
            "branch",
            "hint_ladder",
            "reteach",
            "explain_back",
            "mastery_update",
            "wrap_session",
            "widget_result",
            "game_result",
        ],
    )
    # Both end the turn. The child interacted with something and got an answer
    # about it; continuing into the next teach point in the same turn would
    # bury the response they were owed.
    graph.add_edge("widget_result", END)
    graph.add_edge("game_result", END)
    graph.add_conditional_edges("resume_or_place", _after_place, ["teach", END])
    graph.add_edge("teach", "check")
    graph.add_conditional_edges("check", _after_check, [END])
    graph.add_conditional_edges(
        "branch", _after_branch, ["hint_ladder", "explain_back", END]
    )
    graph.add_conditional_edges("hint_ladder", _after_hint, ["reteach", END])
    graph.add_edge("reteach", "mastery_update")
    graph.add_conditional_edges("explain_back", _after_explain, ["mastery_update", END])
    graph.add_conditional_edges(
        "mastery_update", _after_mastery, ["wrap_session", "resume_or_place"]
    )
    graph.add_edge("wrap_session", END)

    return graph.compile()


def build_production_learn():
    from app.learning.mastery import PostgresMasteryStore

    return build_learn_graph(store=PostgresMasteryStore())


def register() -> None:
    """Register the lesson machine for all three learning agent names.

    `learning_preview` (a guardian looking at what their child is taught) and
    `learning_sample` (a signed-out visitor trying one) run the same machine.
    The difference is the learner id -- see `_learner` -- so a preview scores
    against the adult's own row and a sample scores against a session id that
    is thrown away.
    """
    from app.graph.main_graph import register_agent

    for name in ("learn_agent", "learning_preview", "learning_sample"):
        register_agent(name, build_production_learn)
