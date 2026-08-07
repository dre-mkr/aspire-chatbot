"""The lesson machine.

    resume_or_place → plan_widget → teach → check → branch
                       ↑                              │
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

## Two nodes think; the rest of the machine does not

`teach` and `reteach` live in `teach.py` and are the only nodes here that call
a model. They write the words, ground them in the knowledge base, and decide
whether an interactive widget would help. Everything defined in THIS file is
deterministic, and the split is meant to be checkable by looking: placement,
grading, the hint ladder's rung count and the mastery write are arithmetic and
table lookups, and they stay that way.

The reason is not caution about models generally. It is that `grade_answer`
deciding "wrong" the same way every time is what makes a hint ladder a ladder,
and a lesson chosen by a scheduler rather than by a conversation is what makes
spaced repetition happen at all. What a model is genuinely better at is the one
thing a fixed string cannot do: say the same idea a different way to a child
who has already heard it once.

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
import re
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from app.agents.learn.nodes.explain_back import make_explain_back
from app.agents.learn.nodes.hint_ladder import make_hint_ladder
from app.agents.learn.state import (
    band_of,
    MAX_ATTEMPTS,
    MAX_DIGRESSIONS,
    merge,
    new_session,
    started_at,
)
from app.curriculum.schema import CheckQuestion, Lesson, for_band, load_all
from app.graph.state import AspireState
from app.learning import scheduler
from app.learning.mastery import Evidence, MasteryStore
from app.schemas.directives import ProgressDirective

logger = logging.getLogger(__name__)


def _band(state: AspireState) -> str:
    return band_of(state)


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
                # The only signal the teaching turn gets that CROSSES sessions.
                #
                # `recent_openings` lives in the checkpoint, so it is per
                # conversation, and the case it therefore misses is the common
                # one: a learner comes back tomorrow, starts a new chat, and
                # spaced repetition brings the same concept round again with an
                # empty history behind it. The mastery row is the thing that
                # persists per learner, and `resume_or_place` has already paid
                # for it -- so whether they have met this idea before is free
                # here and unavailable anywhere else in the machine.
                concept_seen_before=any(
                    row.concept_id == placement.lesson.concept_id and row.last_seen
                    for row in rows
                ),
                review_concepts=scheduler.due_concepts(
                    rows, exclude={placement.lesson.concept_id}
                ),
            )
        }

    return resume_or_place


#: Learning agents whose turns are watched rather than taken, and therefore
#: score nobody.
#:
#: `learning_sample` because a signed-out visitor has no account for a row to
#: reference. `learning_preview` because the person at the keyboard is not the
#: learner: a guardian looking in at their child's curriculum was writing
#: `save`, `spend` and `goal` into their OWN mastery row, which then drove
#: spaced repetition for them -- the scheduler would bring a nine-year-old's
#: lesson back to an adult on a fortnightly interval, and their progress
#: figures counted concepts they had watched rather than learned.
NON_SCORING_AGENTS: frozenset[str] = frozenset({"learning_preview", "learning_sample"})


def _learner(state: AspireState) -> str | None:
    """The learner this session writes mastery against, or None for nobody.

    None for an anonymous visitor, and that is the honest answer rather than a
    refusal. `mastery.learner_id` is a UUID referencing an account; a
    `learning_sample` visitor has none, so there is no row for their progress to
    live in and nothing for it to mean when they come back.

    None for a guardian preview too, and for a different reason: there IS an
    account, and it is not the learner's. `access.py` describes the preview as
    letting a parent see what their child is being taught, and until this was
    fixed it did so by teaching the parent and grading them. The lesson itself
    is unchanged -- real teaching, real widgets, real check questions -- and
    nothing it produces is recorded against anybody.

    This used to fall back to the session id, reasoning that a sample session
    should "score normally for its own length". It does -- the hint ladder and
    the reply arithmetic run on the turn's own state and never touch the
    database. What the fallback actually did was hand a non-UUID string to
    asyncpg, which raised, killed the node, and told a child who had moved a
    slider that the assistant was unavailable.

    `MasteryStore.record` accepts None and returns the applied row without
    writing, so every caller's arithmetic is unchanged.
    """
    if state.get("active_agent") in NON_SCORING_AGENTS:
        return None
    user_id = state.get("user_id")
    return str(user_id) if user_id else None


# ── teach ────────────────────────────────────────────────────────────────────


# `plan_widget`, `teach` and `reteach` live in `teach.py`. They are the only
# nodes in this machine that call a model, and keeping them together is what
# makes that easy to check -- every node defined in THIS file is deterministic.
from app.agents.learn.teach import (  # noqa: E402
    make_plan_widget,
    make_reteach,
    make_teach,
)


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


#: A learner asking for a different lesson, rather than answering this one.
#:
#: Deliberately narrow, and the narrowness is the point: a false positive
#: abandons a lesson somebody was halfway through, which is worse than the
#: digression it replaces. Every alternative here names the change explicitly --
#: "something else", "another topic", "different lesson". Anything vaguer is
#: left to the graders and the digression handler.
#:
#: Bare "next" is deliberately ABSENT even though it reads like a match. It is
#: an authored chip on the wrap-up and the reteach turns, where it means
#: "continue", and `_LESSON_REPLY` in `safety_in` already treats it as an
#: on-topic reply. Capturing it here would turn a tap meaning "carry on" into an
#: abandoned lesson.
#: "something else" must be ATTACHED to a teaching verb, never bare.
#:
#: Bare, it matches "i want to buy something else with my money" -- a lesson
#: answer about spending, and one of the better ones a child could give. That
#: turn would have discarded the lesson they were halfway through, which is the
#: exact false positive this pattern is written to avoid rather than an
#: acceptable cost of catching it.
_WANTS_ANOTHER = re.compile(
    r"""
    \b(?:
        (?:teach|show|tell|give)\s+me\s+(?:something|anything)\s+(?:else|new|different)
      | (?:can\s+we|could\s+we|let'?s|i\s+want\s+to|i'?d\s+like\s+to)
        \s+(?:do|try|learn|study)\s+(?:something|anything)\s+(?:else|new|different)
      | (?:a|an|another|different|new|other)\s+(?:topic|lesson|subject)
      | (?:next|another)\s+(?:topic|lesson|subject)
      | change\s+(?:the\s+)?(?:topic|subject)
      | move\s+on\s+(?:to|from)
      | skip\s+(?:this|it|ahead)
    )\b
    """,
    re.VERBOSE | re.IGNORECASE,
)


def wants_a_different_lesson(text: str) -> bool:
    """Whether this message asks to be taught something other than this.

    Consulted in `branch` before the digression check -- see there for why the
    order is the whole fix.
    """
    return bool(_WANTS_ANOTHER.search(text or ""))


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

    Three outcomes and two that are not outcomes at all:

      got_it   -> a game if one fits, otherwise straight to mastery
      partial  -> the hint ladder
      lost     -> the hint ladder, which reveals on the second miss
      move on  -> place a different lesson, in this turn
      digressed-> answer briefly, steer back, do not count it as an attempt
    """

    def branch(state: AspireState) -> dict[str, Any]:
        book = curriculum or load_all()
        learning = state.get("learning") or {}
        lesson = _lesson(book, learning)
        if lesson is None:  # pragma: no cover
            return {}

        from app.graph.nodes.safety_in import latest_user_text

        # BEFORE the digression check, and that order is the fix.
        #
        # `is_off_topic` asks whether the message contains a money word, and
        # "teach me something else" does not -- so the single most on-topic
        # thing a learner can say inside a lesson was being answered with "Good
        # question! Now, back to what we were doing." They asked to move on and
        # were told they could not, which is also the one steer the digression
        # cap is not meant to cover.
        #
        # Placement handles the rest: `concepts_touched` already carries the
        # concept just taught, so `resume_or_place` skips it and picks the next
        # unmastered lesson rather than re-teaching the one being abandoned.
        if wants_a_different_lesson(latest_user_text(state)):
            logger.info(
                "Learner asked to move on from %s; placing another lesson.", lesson.id
            )
            return {
                "learning": merge(
                    learning,
                    phase="placing",
                    question_id=None,
                    attempts=0,
                    hint_rung=0,
                    digression_count=0,
                    outcome=None,
                )
            }

        flags = state.get("safety_flags") or {}
        if flags.get("off_topic"):
            return _digress(state, learning, lesson)

        question = _question(lesson, learning)
        if question is None:  # pragma: no cover
            return {"learning": merge(learning, phase="updating_mastery")}

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

    # Every band names the subject, INCLUDING the fallback. The two fallbacks
    # used not to -- "Good question! Now, back to what we were doing." -- which
    # is precisely the reprimand this function's docstring says to avoid, served
    # to the two bands that were missing from the table. `16-18` and `adult`
    # both landed there, and `adult` is the band a guardian previews in.
    if count > MAX_DIGRESSIONS:
        text = {
            "5-8": f"Ooh, let us hold that one for the end! Back to {subject}.",
            "9-12": f"Good one -- keep it for the end. For now, back to {subject}.",
            "13-15": f"Worth coming back to. Let us finish this first: {subject}.",
        }.get(band, f"Worth coming back to. Let us finish this first: {subject}.")
    else:
        text = {
            "5-8": f"Good question! Now -- back to {subject}.",
            "9-12": f"Good question! Right, back to {subject}.",
            "13-15": f"Fair question. Now, back to {subject}.",
        }.get(band, f"Fair question. Now, back to {subject}.")

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
    return {"teaching": "plan_widget", "done": END}.get(str(learning.get("phase")), END)


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
    if phase == "placing":
        # A move-on request, answered in THIS turn rather than the next one.
        # Ending here and waiting for `_entry` to route `placing` would leave
        # the learner who just asked for a different lesson looking at nothing
        # until they typed again.
        return "resume_or_place"
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


#: Whether a message is a question about a topic rather than a lesson reply.
#:
#: The gate between the two machines in this subgraph. `resume_or_place` teaches
#: what the learner is DUE; `tutor` teaches what they ASKED FOR. Before the tutor
#: existed there was only the first, so "What is compound interest?" was answered
#: with the next unmastered lesson -- which is the defect Track L was opened for.
#:
#: Every clause requires a SUBJECT, and that requirement is the whole design.
#:
#: "Teach me" is a request to start a lesson and belongs to placement -- the
#: learner has named no topic, so there is nothing for a topic resolver to
#: resolve, and routing it here would replace a curriculum with a shrug. "Teach
#: me about compound interest" names one. The difference is `\w{3,}` after the
#: verb, and it is why every alternative below carries one.
#:
#: Narrow in one more place: a message arriving while a check question is
#: outstanding is an ANSWER, whatever it looks like. "What is a dollar worth?"
#: typed in reply to "how much after four weeks?" is still a reply, and routing
#: it as a new topic abandons a question the child was in the middle of. That
#: check lives in `_entry` rather than in the pattern, because it is about the
#: conversation's state and not about the words.
_ASKS_ABOUT = re.compile(
    r"""\b(?:
        what(?:'?s|\s+is|\s+are|\s+does|\s+do)\s+(?:\w+\s+){0,3}\w{3,}
      | (?:why|how)\s+(?:do|does|did|is|are|can|come)\b\s*(?:\w+\s+){0,3}\w{3,}
      | tell\s+me\s+(?:about|what|how|why)\s+(?:\w+\s+){0,3}\w{3,}
      | (?:teach|explain)\s+(?:me\s+)?(?:about\s+)?(?:\w+\s+){0,3}\w{4,}
      | i\s+(?:want|need|would\s+like)\s+to\s+(?:know|learn|understand)\s+(?:\w+\s+){0,3}\w{3,}
      | can\s+you\s+(?:tell|teach|explain|show)\s+me\s+(?:about\s+)?(?:\w+\s+){0,3}\w{3,}
      | what\s+(?:is\s+)?a\s+\w{3,}
      | what\s+about\s+\w{3,}
      | what\s+does\s+\w+\s+mean
    )""",
    re.VERBOSE | re.IGNORECASE,
)

#: Verbs that ask for a lesson without naming one. These belong to PLACEMENT.
#:
#: Listed explicitly and checked first, because the pattern above is generous
#: enough to match "teach me something" on the `\w{4,}` tail, and "something" is
#: the learner declining to choose -- which is exactly the case the scheduler
#: exists for.
_NAMES_NOTHING = re.compile(
    r"""^\s*(?:
        (?:teach|show|tell)\s+me\s*(?:something|anything|a\s+lesson|more)?
      | (?:i\s+want\s+to\s+)?learn\s*(?:something|anything|more)?
      | (?:let'?s|lets)\s+(?:learn|start|go|begin)\b.*
      | (?:start|begin)\s+(?:a\s+)?(?:lesson|learning)?
      | next\s+lesson
      | (?:another|a\s+new)\s+(?:one|lesson|topic)
    )\s*[.!?]*\s*$""",
    re.VERBOSE | re.IGNORECASE,
)


def asks_about_a_topic(text: str) -> bool:
    """Whether this message names something specific the learner wants explained.

    False for "teach me" and true for "teach me about compound interest". The
    distinction routes between the two machines in this subgraph, so it is
    written to be read rather than inferred from behaviour.
    """
    body = (text or "").strip()
    if not body or _NAMES_NOTHING.match(body):
        return False
    return bool(_ASKS_ABOUT.search(body))


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

    # ── the tutor's claim on the turn ───────────────────────────────────────
    #
    # Three ways in, and the first two are what fix the reported defect:
    #
    #   * they asked about a topic, and there is no check outstanding;
    #   * the tutor was already running -- a conversation about a concept
    #     continues as a conversation about that concept, so a bare "20" or "why?"
    #     reaches EVALUATE rather than being re-routed into placement;
    #   * a check the TUTOR asked is outstanding.
    #
    # The authored curriculum keeps everything else. A learner working through a
    # module is working through a module, and placement, the hint ladder, games
    # and the wrap-up are all better at that than a topic resolver is.
    from app.graph.nodes.safety_in import latest_user_text

    # An empty concept store means nothing has been seeded, and the tutor would
    # decline every turn. Falling back to the authored curriculum is the correct
    # behaviour then, not a degraded one -- and it is what keeps a deployment
    # that has not run `seed_concepts.py` working exactly as it did before.
    from app.learning.concepts import get_store

    if len(get_store()):
        text = latest_user_text(state)
        if learning.get("active_concept_id") and learning.get("resolution_source") != "none":
            return "tutor"
        if asks_about_a_topic(text) and not learning.get("question_id"):
            return "tutor"

    phase = str(learning.get("phase") or "placing")
    return {
        "placing": "resume_or_place",
        # `plan_widget`, never `teach` directly. A turn that resumes straight
        # into the teaching node has no grounding and no planned primitive in
        # state, so the lesson would be written from the curriculum alone and
        # the widget silently skipped -- on exactly the turns a resumed lesson
        # makes most likely.
        "teaching": "plan_widget",
        "checking": "branch",
        "hinting": "hint_ladder",
        "reteaching": "reteach",
        "explaining_back": "explain_back",
        "updating_mastery": "mastery_update",
        "wrapping": "wrap_session",
        "done": "resume_or_place",
    }.get(phase, "resume_or_place")


def build_learn_graph(
    *,
    curriculum=None,
    store: MasteryStore | None = None,
    retrieve=None,
    plan=None,
    invoke=None,
    embed=None,
    teach_retrieve=None,
    disambiguate=None,
    widget_plan=None,
    widget_compose=None,
):
    """Compile the lesson machine.

    `retrieve`, `plan` and `invoke` are the teaching turn's three optional
    capabilities -- knowledge-base grounding, widget planning, and the model
    that writes the words. Injected rather than constructed here for the reason
    the Q&A subgraph gives: each has a different availability story, and a
    subgraph that built them itself could not start when one was missing.

    Every one defaults to None, which is the configuration every existing test
    uses: the lesson falls back to the curriculum's authored text and the
    machine behaves exactly as it did before there was a model in it.

    The five arguments after `invoke` belong to the topic tutor:

        embed             an utterance to a vector, for concept resolution
        teach_retrieve    knowledge-base rows for the RAG-teach fallback
        disambiguate      one structured call between two candidate concepts
        widget_plan       which primitive, if any
        widget_compose    that primitive's JSON

    Kept separate from `retrieve` and `plan` rather than reusing them, because the
    two paths ask different questions of the same capability: `retrieve` searches
    on a placed LESSON'S objective, and `teach_retrieve` searches on what the
    learner actually said. Sharing one argument would have meant one of the two
    silently searching for the wrong thing.
    """
    graph = StateGraph(AspireState)

    graph.add_node("resume_or_place", make_resume_or_place(curriculum, store))
    # The name is load-bearing: `INTERNAL_NODES` suppresses this node's model
    # call by name, and without that the planner's JSON streams to the child.
    graph.add_node("plan_widget", make_plan_widget(curriculum, retrieve=retrieve, plan=plan))
    graph.add_node("teach", make_teach(curriculum, invoke=invoke))
    graph.add_node("check", make_check(curriculum))
    graph.add_node("branch", make_branch(curriculum))
    graph.add_node("hint_ladder", make_hint_ladder(curriculum))
    graph.add_node("reteach", make_reteach(curriculum, retrieve=retrieve, invoke=invoke))
    graph.add_node("explain_back", make_explain_back(curriculum))
    graph.add_node("mastery_update", make_mastery_update(curriculum, store))
    graph.add_node("wrap_session", make_wrap_session(store))

    from app.agents.learn.nodes.widget_result import make_widget_result
    from app.agents.learn.tools.games import make_game_result_node

    graph.add_node("widget_result", make_widget_result(store))
    graph.add_node("game_result", make_game_result_node(store))

    # The topic tutor. Named `tutor` and the name is load-bearing twice over:
    # `INTERNAL_NODES` suppresses its raw model tokens by name so that nothing
    # unvalidated reaches a reader, and `evals/learning_agent.py` asserts on it.
    from app.agents.learn.tutor import make_tutor

    graph.add_node(
        "tutor",
        make_tutor(
            embed=embed,
            retrieve=teach_retrieve,
            disambiguate=disambiguate,
            invoke=invoke,
            plan=widget_plan,
            compose=widget_compose,
            mastery=store,
        ),
    )
    # Straight to END. The tutor emits its own prose and its own widget directive
    # and has nothing to hand on -- routing it into `check` would ask a second
    # question after the one it already asked.
    graph.add_edge("tutor", END)

    graph.add_conditional_edges(
        START,
        _entry,
        [
            "tutor",
            "resume_or_place",
            "plan_widget",
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
    graph.add_conditional_edges("resume_or_place", _after_place, ["plan_widget", END])
    graph.add_edge("plan_widget", "teach")
    graph.add_edge("teach", "check")
    graph.add_conditional_edges("check", _after_check, [END])
    graph.add_conditional_edges(
        "branch", _after_branch, ["hint_ladder", "explain_back", "resume_or_place", END]
    )
    graph.add_conditional_edges("hint_ladder", _after_hint, ["reteach", END])
    graph.add_edge("reteach", "mastery_update")
    graph.add_conditional_edges("explain_back", _after_explain, ["mastery_update", END])
    graph.add_conditional_edges(
        "mastery_update", _after_mastery, ["wrap_session", "resume_or_place"]
    )
    graph.add_edge("wrap_session", END)

    return graph.compile()


async def _retrieve(query: str, k: int, audience: str):
    """Dense knowledge-base search, filtered to what this audience may see.

    Deliberately the SAME retriever the Q&A subgraph uses -- one knowledge base,
    one ingestion, one embedding model. A second retrieval path over the same
    corpus is a second place for the audience filter to be got wrong, and the
    one that gets forgotten is always the one serving children.

    Dense only, with no BM25 half and no fusion. Q&A needs the lexical retriever
    because a question can name an exact term the embedding misses; a lesson is
    grounded in a concept the curriculum already named, so there is no rare term
    to catch and nothing for fusion to reconcile.
    """
    from app.agents.qa.graph import _search
    from app.agents.qa.nodes import _permitted

    chunks = await _search(query, k)
    return [chunk for chunk in chunks if _permitted(chunk, audience)]


async def _teach_invoke(messages):
    """The answer model, writing the lesson.

    The answer model rather than the classifier's, unlike `rewrite_query`: this
    is the prose a child reads, and it is the one call in the lesson where the
    quality of the writing IS the product.
    """
    from app.agent import build_chat_model

    response = await build_chat_model().ainvoke(messages)
    content = response.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


async def _teach_retrieve(query: str):
    """Knowledge-base rows for the RAG-teach fallback, searched on the UTTERANCE.

    The other retriever searches on a placed lesson's objective, which is right
    for a lesson the scheduler chose and wrong for a question the learner asked.
    That distinction is not a nicety: the RAG-teach path exists precisely because
    no concept covered the question, so searching for anything other than the
    question would return rows about something else and teach from them.

    Youth-filtered, like every other learner-facing retrieval. `audience_for`
    cannot be used here because it reads the agent name off graph state and this
    is called from the resolver, which is deliberately given no state -- the
    narrow slice is the safe default and the preview path pays a little recall
    for it.
    """
    from app.agents.qa.graph import _search
    from app.agents.qa.nodes import _permitted

    chunks = await _search(query, 8)
    return [chunk for chunk in chunks if _permitted(chunk, "youth")]


async def _embed(text: str):
    """The utterance as a vector, through the product's cached embedder.

    `embed_query_cached` rather than a fresh call: the four landing starter chips
    are the highest-collision strings in the product and every one of them is a
    learning question, so the cache hit rate here is high and each hit is a
    network round trip a child does not wait through.
    """
    from app.rag import embed_query_cached

    return await embed_query_cached(text)


def _structured(model_setting: str):
    """A `(system, user) -> dict` caller on a named model tier.

    One factory for the three cheap structured jobs -- concept disambiguation,
    widget planning, widget composition -- so that "which model does this?" is
    answered by one line of config rather than by three call sites that drifted.

    Returns `{}` rather than raising on any failure. Every caller treats a falsy
    answer as "no decision", which degrades to no widget or to the RAG-teach
    fallback: both are outcomes the lesson survives.
    """

    async def call(*, system: str, user: str) -> dict:
        import json as _json

        from langchain_core.messages import HumanMessage, SystemMessage

        from app.agent import build_chat_model
        from app.config import get_settings

        settings = get_settings()
        chosen = getattr(settings, model_setting, "") or settings.chat_model
        try:
            response = await build_chat_model(model=chosen).ainvoke(
                [SystemMessage(content=system), HumanMessage(content=user)]
            )
        except Exception:
            logger.info("Structured call on %s failed.", chosen, exc_info=True)
            return {}

        text = _text_of_response(response).strip()
        # The composer returns a widget object; the planner and the disambiguator
        # return a small decision object. Both are JSON, and both arrive fenced
        # often enough that unwrapping here is cheaper than a retry.
        from app.agents.learn.widgets import _unfence

        try:
            parsed = _json.loads(_unfence(text))
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    return call


def _compose_caller():
    """The widget composer. Returns the raw JSON string, not a dict.

    Raw because `widgets.validate` parses it itself -- gate 1 exists to reject
    malformed JSON with a named gate, and parsing it here would turn that into a
    silent empty return with no gate attached to the failure.
    """

    async def call(*, system: str, user: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.agent import build_chat_model
        from app.config import get_settings

        settings = get_settings()
        chosen = settings.learn_widget_compose_model or settings.chat_model
        response = await build_chat_model(model=chosen).ainvoke(
            [SystemMessage(content=system), HumanMessage(content=user)]
        )
        return _text_of_response(response)

    return call


def _text_of_response(response) -> str:
    content = getattr(response, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def build_production_learn():
    from app.learning.mastery import PostgresMasteryStore
    from app.widgets.planner import make_planner

    from app.graph.nodes.classify import default_invoke

    return build_learn_graph(
        store=PostgresMasteryStore(),
        retrieve=_retrieve,
        # The planner runs on the small model. It picks one name from a list of
        # at most nine -- see `widgets/planner.py` on why that is deliberately
        # not a job for the answer model.
        plan=make_planner(default_invoke),
        invoke=_teach_invoke,
        # The topic tutor's five. Every model here is named in `Settings`
        # (`learn_*_model`) and nowhere else, which is the whole of the brief's
        # model-tiering requirement: swapping the model that writes lessons is a
        # config change, and it cannot silently re-tune the widget planner.
        embed=_embed,
        teach_retrieve=_teach_retrieve,
        disambiguate=_structured("learn_resolve_model"),
        widget_plan=_structured("learn_widget_plan_model"),
        widget_compose=_compose_caller(),
    )


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
