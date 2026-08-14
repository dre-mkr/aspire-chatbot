"""The lesson machine."""

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
            # Wrong answers do not raise mastery, so without this the same lesson gets re-picked.
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


#: Learning agents whose turns are watched rather than taken, and therefore score nobody.
NON_SCORING_AGENTS: frozenset[str] = frozenset({"learning_preview", "learning_sample"})


def _learner(state: AspireState) -> str | None:
    """The learner this session writes mastery against, or None for nobody."""
    if state.get("active_agent") in NON_SCORING_AGENTS:
        return None
    user_id = state.get("user_id")
    return str(user_id) if user_id else None


# ── teach ────────────────────────────────────────────────────────────────────


# `plan_widget`, `teach` and `reteach` live in `teach.py`.
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
            # The options ARE the interaction.
            "quick_replies": list(question.options) or _chips(band, ["Tell me"]),
            "learning": merge(learning, question_id=question.id, phase="checking"),
        }

    return check


# ── the branch after an answer ───────────────────────────────────────────────


#: A learner asking for a different lesson, rather than answering this one.
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
    """Whether this message asks to be taught something other than this."""
    return bool(_WANTS_ANOTHER.search(text or ""))


def grade_answer(question: CheckQuestion, answer: str) -> bool:
    """Whether the child got it."""
    text = (answer or "").strip().lower()
    if not text:
        return False
    if question.answer is not None and question.options:
        correct = question.options[question.answer].strip().lower()
        if text == correct or correct in text:
            return True
        # A tapped chip sends the option text; a typed answer may be the option's index.
        if text in {str(question.answer), str(question.answer + 1)}:
            return True
        return False
    return any(word.lower() in text for word in question.accept)


def make_branch(curriculum=None):
    """Decide what happens after the child answers."""

    def branch(state: AspireState) -> dict[str, Any]:
        book = curriculum or load_all()
        learning = state.get("learning") or {}
        lesson = _lesson(book, learning)
        if lesson is None:
            # There is no lesson to answer against -- the tutor taught this
            # conversation and never set one, or a phase outlived its lesson.
            # Returning nothing here ends the turn without a word, which is how
            # a reader gets an empty message; place a lesson instead, which is
            # what the phase this arrived in was already asking for.
            logger.warning(
                "branch reached with no lesson (phase=%s lesson_id=%r); placing one "
                "rather than ending the turn silently.",
                learning.get("phase"),
                learning.get("lesson_id"),
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

        from app.graph.nodes.safety_in import latest_user_text

        # BEFORE the digression check, and that order is the fix.
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
    """Answer the off-topic question briefly, then steer back."""
    band = _band(state)
    count = int(learning.get("digression_count") or 0) + 1
    example = (lesson.examples_for(band) or ["what we were doing"])[0]
    subject = example.split(".")[0][:60]

    # Every band names the subject, INCLUDING the fallback.
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
            # NOT an attempt.
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
    """Record the evidence, then decide whether to continue or wrap."""

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
    """End at a natural stopping point, with a progress directive."""

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
    """Chips, capped at four and at four words each."""
    return [" ".join(option.split()[:4]) for option in options[:4]]


# ── routing ──────────────────────────────────────────────────────────────────


def _after_place(state: AspireState) -> str:
    learning = state.get("learning") or {}
    return {"teaching": "plan_widget", "done": END}.get(str(learning.get("phase")), END)


def _after_check(state: AspireState) -> str:
    """The graph pauses here on a real turn, waiting for the child's answer."""
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

#: Verbs that ask for a lesson without naming one.
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
    """Whether this message names something specific the learner wants explained."""
    body = (text or "").strip()
    if not body or _NAMES_NOTHING.match(body):
        return False
    return bool(_ASKS_ABOUT.search(body))


def _entry(state: AspireState) -> str:
    """Where this turn starts, from the phase the last one left behind."""
    # A widget interaction or a game result is a TURN and it jumps the queue.
    flags = state.get("safety_flags") or {}
    if flags.get("widget_interaction"):
        return "widget_result"
    if flags.get("game_result"):
        return "game_result"

    learning = state.get("learning") or {}

    # ── the tutor's claim on the turn ───────────────────────────────────────
    from app.graph.nodes.safety_in import latest_user_text

    # An empty concept store means nothing has been seeded, and the tutor would decline every turn.
    from app.learning.concepts import get_store

    if len(get_store()):
        text = latest_user_text(state)
        # Asking to move on is a request the phase table already knows how to honour
        # (`branch` places another lesson). The claim below would swallow it, and then
        # nothing could ever leave a concept: `branch` is only reached from the phase
        # table, which this claim returns before.
        if wants_a_different_lesson(text):
            # `branch` is where the request is honoured, and it can only be reached
            # from the phase table below; without a lesson to move on from, place one.
            return "branch" if learning.get("lesson_id") else "resume_or_place"

        # The tutor declined last turn and offered concepts instead, so this
        # message is the learner choosing one. A bare title -- "Building a
        # saving habit" -- asks nothing and names no lesson, so every claim
        # below reads False and the phase table sent it to `branch`, which had
        # no lesson to answer it against and ended the turn in silence. Only
        # the tutor can resolve a topic, and it resolves these: the titles it
        # offers come out of its own store.
        if learning.get("awaiting_topic_choice"):
            return "tutor"

        if (
            learning.get("active_concept_id")
            and learning.get("resolution_source") != "none"
        ):
            return "tutor"
        if asks_about_a_topic(text) and not learning.get("question_id"):
            return "tutor"
        # "Teach me something" names no topic and used to fall through to the
        # lesson machine below -- which cannot emit a widget and never sets
        # `active_concept_id`, so the session never found its way back here.
        # The tutor places a concept itself when the learner names none.
        from app.agents.learn.resolve import wants_a_lesson

        if wants_a_lesson(text) and not learning.get("question_id"):
            return "tutor"

    phase = str(learning.get("phase") or "placing")
    return {
        "placing": "resume_or_place",
        # `plan_widget`, never `teach` directly.
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
    grade=None,
):
    """Compile the lesson machine."""
    graph = StateGraph(AspireState)

    graph.add_node("resume_or_place", make_resume_or_place(curriculum, store))
    # Name is load-bearing: `INTERNAL_NODES` suppresses "plan_widget", so its JSON never streams.
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

    # The topic tutor.
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
            grade=grade,
            # The authored prerequisite graph, which the teachable-concept rows
            # inherit through their slugs. A tutor that cannot see what comes
            # first can only ever reteach what came second.
            curriculum=curriculum,
        ),
    )
    # Straight to END.
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
    # Both end the turn.
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
    """Dense knowledge-base search, filtered to what this audience may see."""
    from app.agents.qa.graph import _search
    from app.agents.qa.nodes import _permitted

    chunks = await _search(query, k)
    return [chunk for chunk in chunks if _permitted(chunk, audience)]


async def _teach_invoke(messages):
    """The answer model, writing the lesson."""
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
    """Knowledge-base rows for the RAG-teach fallback, searched on the UTTERANCE."""
    from app.agents.qa.graph import _search
    from app.agents.qa.nodes import _permitted

    chunks = await _search(query, 8)
    return [chunk for chunk in chunks if _permitted(chunk, "youth")]


async def _embed(text: str):
    """The utterance as a vector, through the product's cached embedder."""
    from app.rag import embed_query_cached

    return await embed_query_cached(text)


def _structured(model_setting: str):
    """A `(system, user) -> dict` caller on a named model tier."""

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
        # Planner and disambiguator return a small decision object; the composer a widget.
        from app.agents.learn.widgets import _unfence

        try:
            parsed = _json.loads(_unfence(text))
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    return call


def _compose_caller():
    """The widget composer."""

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
        # The planner runs on the small model.
        plan=make_planner(default_invoke),
        invoke=_teach_invoke,
        # The topic tutor's five.
        embed=_embed,
        teach_retrieve=_teach_retrieve,
        disambiguate=_structured("learn_resolve_model"),
        widget_plan=_structured("learn_widget_plan_model"),
        widget_compose=_compose_caller(),
        # `learn_evaluate_model` has been in the settings since Track L and had
        # no call site: the grader it was tiered for was specified and never
        # built, so no learning turn ever looked at what the learner answered.
        grade=_structured("learn_evaluate_model"),
    )


def register() -> None:
    """Register the lesson machine for all three learning agent names."""
    from app.graph.main_graph import register_agent

    for name in ("learn_agent", "learning_preview", "learning_sample"):
        register_agent(name, build_production_learn)
