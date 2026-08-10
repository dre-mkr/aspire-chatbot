"""The tutor adapts, and each of the nine scenarios says how.

These drive the real `tutor` node with fake model callers, so what is asserted
is the graph's behaviour rather than a prompt's wording. Every model call is
deterministic: the point is the DECISIONS, and a decision that depends on what
an LLM felt like saying is not a decision the graph is making.
"""

from __future__ import annotations

import pytest

from app.agents.learn import tutor as tutor_module
from app.agents.learn.evaluate import (
    Diagnosis,
    Verdict,
    evaluate_answer,
    match_accept_list,
    triage,
)
from app.agents.learn.planner import Move
from app.agents.learn.strategy import LADDER, Strategy, find_prerequisite, next_strategy
from app.learning.concepts import (
    CheckItem,
    ConceptStore,
    Misconception,
    TeachingConcept,
    set_store,
)
from app.learning.mastery import Evidence, MasteryStore


# ── the material ─────────────────────────────────────────────────────────────


def check(**changes) -> CheckItem:
    base = dict(
        id="chk_1",
        band="9_12",
        type="numeric",
        question="If you save EC$100 and the bank adds EC$3, how much do you have?",
        answer="103",
        accept=("103", "EC$103", "one hundred and three"),
        hints=("Add the extra on.", "EC$100 plus EC$3.", "Put the two amounts together."),
        explanation_on_correct="Right -- the interest joins the money already there.",
        explanation_on_wrong="The interest is added to what you already had.",
    )
    base.update(changes)
    return CheckItem(**base)


def compound() -> TeachingConcept:
    return TeachingConcept(
        id="CON-0042",
        slug="compound_interest",
        locale="en",
        title="Compound interest",
        domain="saving",
        band_min="9-12",
        band_max="adult",
        aliases=("interest on interest",),
        bodies={
            "9-12": (
                "When you keep money in a savings account the bank pays you a little "
                "extra for leaving it there, and that extra is called interest. The "
                "year after, the bank pays you extra on your money AND on the interest "
                "you already earned, so your savings start growing on their own."
            )
        },
        local_example="Put EC$100 in at 3 percent and you have EC$103 after a year.",
        misconceptions=(
            Misconception(
                wrong="Interest is only ever worked out on the amount you first put in.",
                right="Interest already earned joins the balance and earns interest too.",
            ),
        ),
        check_bank=(check(),),
        numeric_anchors={"principal": 100, "rate": 0.03},
        widget_hints=("growth_stack",),
        status="approved",
    )


def percentages() -> TeachingConcept:
    """The prerequisite. `slug` matches a curriculum concept id, which is the link."""
    return TeachingConcept(
        id="CON-0001",
        slug="save",
        locale="en",
        title="Saving",
        domain="saving",
        band_min="5-8",
        band_max="adult",
        bodies={"5-8": "Saving is keeping some of your money for later."},
        check_bank=(check(id="chk_save", band="5_8", question="What is saving?", answer="keeping"),),
        status="approved",
    )


A_LESSON = (
    "Here is something worth knowing. When you leave money in a savings account the "
    "bank pays you a little extra for keeping it there, and that extra is called "
    "interest. The clever part comes the year after: the bank pays you extra on your "
    "money and on the interest you already earned. Put EC$100 in at 3 percent and you "
    "have EC$103 after a year, and the next year the bank pays interest on all of it. "
    "If you save EC$100 and the bank adds EC$3, how much do you have?"
)


@pytest.fixture
def store():
    holder = ConceptStore()
    holder.load([compound(), percentages()])
    set_store(holder)
    yield holder
    set_store(None)


@pytest.fixture
def mastery():
    return MasteryStore()


class Teacher:
    """An `invoke` that returns a lesson and keeps every prompt it was given."""

    def __init__(self, reply: str = A_LESSON):
        self.reply = reply
        self.prompts: list[str] = []

    async def __call__(self, messages):
        self.prompts.append("\n\n".join(str(message.content) for message in messages))
        return self.reply

    @property
    def last(self) -> str:
        assert self.prompts, "the teaching model was never called"
        return self.prompts[-1]


def grader(**payload):
    """A `grade` caller returning one fixed structured verdict."""

    async def call(*, system: str, user: str) -> dict:
        return dict(payload)

    return call


def tutor(*, mastery=None, grade=None, invoke=None, **extra):
    return tutor_module.make_tutor(
        embed=None,
        invoke=invoke or Teacher(),
        plan=None,
        compose=None,
        cache=None,
        mastery=mastery,
        grade=grade,
        **extra,
    )


def turn(text: str, *, learning: dict | None = None, band: str = "9-12", **extra) -> dict:
    from langchain_core.messages import HumanMessage

    state = {
        "messages": [HumanMessage(content=text)],
        "age_band": band,
        "locale": "en",
        "active_agent": "learn_agent",
        "user_id": "11111111-1111-4111-8111-111111111111",
        "learning": learning if learning is not None else {"active_concept_id": "CON-0042"},
    }
    state.update(extra)
    return state


def learned(result: dict) -> dict:
    return result.get("learning") or {}


def said(result: dict) -> str:
    messages = result.get("messages") or []
    return str(messages[-1].content) if messages else ""


# ── scenario 1: a plain question is answered as a lesson ─────────────────────


class TestScenario1AnExplanation:
    pytestmark = pytest.mark.asyncio

    async def test_a_question_produces_a_lesson_not_a_definition(self, store, mastery):
        result = await tutor(mastery=mastery)(turn("What is compound interest?"))

        assert said(result), "a learning turn must always produce prose"
        assert learned(result)["move"] == Move.TEACH.value
        assert learned(result)["active_concept_id"] == "CON-0042"

    async def test_the_first_explanation_is_the_first_rung(self, store, mastery):
        result = await tutor(mastery=mastery)(turn("What is compound interest?"))
        assert learned(result)["teaching_strategy"] == Strategy.DEFINITION.value


# ── scenario 2: teach me X is a flow, not a lookup ───────────────────────────


class TestScenario2ALearningFlow:
    pytestmark = pytest.mark.asyncio

    async def test_teaching_ends_with_a_question_outstanding(self, store, mastery):
        """The difference between teaching and answering: the turn hands back."""
        result = await tutor(mastery=mastery)(turn("Teach me about compound interest"))

        state = learned(result)
        assert state["awaiting_check_answer"] is True
        assert state["pending_check_id"] == "chk_1"

    async def test_the_next_message_is_read_as_an_answer(self, store, mastery):
        node = tutor(mastery=mastery, grade=grader(verdict="CORRECT"))
        first = await node(turn("Teach me about compound interest"))
        second = await node(turn("103", learning=learned(first)))

        assert learned(second)["last_verdict"] == Verdict.CORRECT.value


# ── scenario 3: "I don't understand" changes the strategy ────────────────────


class TestScenario3ADifferentExplanation:
    pytestmark = pytest.mark.asyncio

    async def test_confusion_reteaches_rather_than_repeats(self, store, mastery):
        node = tutor(mastery=mastery)
        first = await node(turn("What is compound interest?"))
        second = await node(turn("I don't understand", learning=learned(first)))

        assert learned(second)["move"] == Move.RETEACH.value

    async def test_each_failure_moves_down_the_ladder(self, store, mastery):
        """§14. Definition, then analogy, then a number -- never round in a circle."""
        node = tutor(mastery=mastery)
        state = learned(await node(turn("What is compound interest?")))
        assert state["teaching_strategy"] == Strategy.DEFINITION.value

        rungs = []
        for _ in range(3):
            state = learned(await node(turn("I still don't understand", learning=state)))
            rungs.append(state["teaching_strategy"])

        assert rungs == [
            Strategy.ANALOGY.value,
            Strategy.NUMERIC_EXAMPLE.value,
            Strategy.WALKTHROUGH.value,
        ]

    async def test_confusion_is_never_marked_as_a_wrong_answer(self, store, mastery):
        """It is three words, so it matches no accept term and reads as a bad answer."""
        node = tutor(mastery=mastery)
        first = await node(turn("Teach me about compound interest"))
        second = await node(turn("I don't understand", learning=learned(first)))

        state = learned(second)
        assert state["last_verdict"] != Verdict.WRONG.value
        assert state["prior_wrong_answers"] == [], "admitting confusion is not an attempt"
        assert await mastery.all_for("11111111-1111-4111-8111-111111111111") == [], (
            "and it must not cost them mastery"
        )

    async def test_the_reteach_prompt_forbids_the_approach_that_failed(self, store, mastery):
        teacher = Teacher()
        node = tutor(mastery=mastery, invoke=teacher)
        first = await node(turn("What is compound interest?"))
        await node(turn("I don't understand", learning=learned(first)))

        assert "DIFFERENT APPROACH" in teacher.last
        assert "comparison" in teacher.last, "the analogy rung must reach the model"


# ── scenario 4 and 8: practice and quiz use what already exists ──────────────


class TestScenario4And8Widgets:
    pytestmark = pytest.mark.asyncio

    async def test_a_widget_is_offered_through_the_existing_pipeline(self, store, mastery):
        """The tutor decides WHEN; the widget pipeline decides what and whether."""
        planned: list[dict] = []

        async def plan(*, system: str, user: str) -> dict:
            planned.append({"user": user})
            return {"kind": "none"}

        node = tutor_module.make_tutor(
            embed=None, invoke=Teacher(), plan=plan, compose=None, cache=None, mastery=mastery
        )
        await node(turn("Give me a practice question"))

        assert planned, "the existing widget planner must be consulted"

    async def test_asking_to_practise_asks_a_question_rather_than_recapping(
        self, store, mastery
    ):
        """§10. 'Give me a practice question' names no topic, so it used to decline."""
        node = tutor(mastery=mastery)
        first = await node(turn("Teach me about compound interest"))
        state = learned(first)
        # They have answered the outstanding check, so nothing is pending.
        state["awaiting_check_answer"] = False
        state["pending_check_id"] = None

        second = await node(turn("Give me a practice question", learning=state))

        assert learned(second)["active_concept_id"] == "CON-0042", (
            "a practice request continues the lesson rather than starting nothing"
        )
        assert learned(second)["move"] == Move.CHECK.value

    async def test_a_long_stint_on_one_concept_launches_a_real_game(self, store, mastery):
        """`plan_move` could return GAME since Track L and nothing ever launched one."""
        node = tutor(mastery=mastery)
        result = await node(
            turn(
                "more",
                learning={
                    "active_concept_id": "CON-0042",
                    "concepts_touched": ["CON-0042"],
                    "turns_on_concept": {"CON-0042": 4},
                },
            )
        )

        assert learned(result)["move"] == Move.GAME.value
        directives = result.get("ui_directives") or []
        assert any(
            (d.get("type") or d.get("kind")) == "game" or "game" in str(d).lower()
            for d in directives
        ), f"the game directive must reach the client, got {directives}"

    async def test_a_game_turn_offers_no_widget_beside_it(self, store, mastery):
        """Two interactive things at once is exactly what §4 warns against."""
        composed: list[str] = []

        async def plan(*, system: str, user: str) -> dict:
            composed.append(user)
            return {"kind": "growth_stack"}

        node = tutor_module.make_tutor(
            embed=None, invoke=Teacher(), plan=plan, compose=None, cache=None, mastery=mastery
        )
        await node(
            turn(
                "more",
                learning={
                    "active_concept_id": "CON-0042",
                    "concepts_touched": ["CON-0042"],
                    "turns_on_concept": {"CON-0042": 4},
                },
            )
        )

        assert composed == [], "a game turn must not also plan a widget"

    async def test_a_widget_result_tells_the_tutor_what_was_practised(self, store, mastery):
        from app.agents.learn.nodes.widget_result import make_widget_result

        node = make_widget_result(mastery)
        result = await node(
            turn(
                "",
                learning={},
                safety_flags={
                    "widget_interaction": {
                        "widget_kind": "growth_stack",
                        "concept_id": "CON-0042",
                        "final_state": {
                            "principal_cents": 10000,
                            "contribution_cents": 0,
                            "rate": 0.03,
                            "periods": 5,
                        },
                        "computed": {},
                    }
                },
            )
        )

        state = learned(result)
        assert state["active_concept_id"] == "CON-0042"
        assert "CON-0042" in state["concepts_touched"]
        # Practice IS a check, so the tutor must not immediately demand one.
        assert state["turns_since_check"] == 0

    async def test_a_poor_game_score_makes_the_next_turn_reteach(self, store, mastery):
        from app.agents.learn.tools.games import make_game_result_node

        after_game = await make_game_result_node(mastery)(
            turn(
                "",
                learning={"active_concept_id": "CON-0042"},
                safety_flags={
                    "game_result": {
                        "game": "scramble",
                        "concept_id": "CON-0042",
                        "score": 2,
                        "max_score": 10,
                        "completed": True,
                    }
                },
            )
        )
        assert learned(after_game)["reteach_pending"] is True

        following = await tutor(mastery=mastery)(
            turn("ok", learning=learned(after_game))
        )
        assert learned(following)["move"] == Move.RETEACH.value
        assert learned(following)["reteach_pending"] is False, "the flag is spent once"


# ── scenario 5: a correct answer is recognised and raises the bar ────────────


class TestScenario5Success:
    pytestmark = pytest.mark.asyncio

    async def test_a_correct_answer_is_recorded_as_mastery(self, store, mastery):
        node = tutor(mastery=mastery, grade=grader(verdict="CORRECT"))
        first = await node(turn("Teach me about compound interest"))
        await node(turn("EC$103", learning=learned(first)))

        rows = await mastery.all_for("11111111-1111-4111-8111-111111111111")
        assert [row.concept_id for row in rows] == ["CON-0042"]
        assert rows[0].score == 1, "the loop must actually write to the scale"

    async def test_repeated_success_reaches_mastery_and_advances(self, store, mastery):
        node = tutor(mastery=mastery, grade=grader(verdict="CORRECT"))
        state = learned(await node(turn("Teach me about compound interest")))

        moves = []
        for _ in range(4):
            state["awaiting_check_answer"] = True
            state["pending_check_id"] = "chk_1"
            state = learned(await node(turn("EC$103", learning=state)))
            moves.append(state["move"])

        assert Move.ADVANCE.value in moves, (
            "three correct answers must reach the top of the scale and move on"
        )

    async def test_success_without_hints_is_recorded_as_independent(self, store, mastery):
        """§15. Correct unaided is a different rung from correct with support."""
        node = tutor(mastery=mastery, grade=grader(verdict="CORRECT"))
        first = await node(turn("Teach me about compound interest"))
        second = await node(turn("EC$103", learning=learned(first)))

        assert learned(second)["independent_correct"] == ["CON-0042"]


# ── scenario 6: a wrong answer is diagnosed and scaffolded ───────────────────


class TestScenario6Struggle:
    pytestmark = pytest.mark.asyncio

    async def test_a_wrong_answer_produces_a_hint_not_the_answer(self, store, mastery):
        node = tutor(
            mastery=mastery,
            grade=grader(verdict="WRONG", diagnosis="CALCULATION_ERROR"),
        )
        first = await node(turn("Teach me about compound interest"))
        second = await node(turn("EC$130", learning=learned(first)))

        assert learned(second)["move"] == Move.HINT.value
        assert learned(second)["hint_rung_now"] == 1

    async def test_the_hint_given_is_the_authored_rung(self, store, mastery):
        teacher = Teacher()
        node = tutor(
            mastery=mastery,
            invoke=teacher,
            grade=grader(verdict="WRONG", diagnosis="CALCULATION_ERROR"),
        )
        first = await node(turn("Teach me about compound interest"))
        await node(turn("EC$130", learning=learned(first)))

        assert "Add the extra on." in teacher.last

    async def test_assistance_increases_with_each_miss(self, store, mastery):
        node = tutor(
            mastery=mastery,
            invoke=Teacher(),
            grade=grader(verdict="WRONG", diagnosis="CALCULATION_ERROR"),
        )
        state = learned(await node(turn("Teach me about compound interest")))

        rungs = []
        for _ in range(2):
            state = learned(await node(turn("EC$130", learning=state)))
            rungs.append(state["hint_rung_now"])

        assert rungs == [1, 2], "the ladder must climb, not repeat its first rung"

    async def test_a_wrong_answer_is_remembered_verbatim(self, store, mastery):
        node = tutor(
            mastery=mastery, grade=grader(verdict="WRONG", diagnosis="CALCULATION_ERROR")
        )
        first = await node(turn("Teach me about compound interest"))
        second = await node(turn("EC$130", learning=learned(first)))

        assert "EC$130" in learned(second)["prior_wrong_answers"]

    async def test_asking_for_the_answer_gets_it(self, store, mastery):
        """§12. The ladder helps them think; it does not withhold on request."""
        node = tutor(mastery=mastery)
        first = await node(turn("Teach me about compound interest"))
        second = await node(turn("just tell me the answer", learning=learned(first)))

        assert learned(second)["move"] == Move.ANSWER.value


# ── scenario 7: a repeated conceptual error is named and addressed ───────────


class TestScenario7Misconceptions:
    pytestmark = pytest.mark.asyncio

    async def test_a_matched_misconception_is_recorded(self, store, mastery):
        wrong = "Interest is only ever worked out on the amount you first put in."
        node = tutor(
            mastery=mastery,
            grade=grader(
                verdict="WRONG", diagnosis="CONCEPTUAL_MISUNDERSTANDING", misconception=wrong
            ),
        )
        first = await node(turn("Teach me about compound interest"))
        second = await node(turn("You always get EC$3", learning=learned(first)))

        state = learned(second)
        assert state["misconceptions"] == [wrong]
        assert state["move"] == Move.CORRECT_MISCONCEPTION.value
        assert state["last_diagnosis"] == Diagnosis.CONCEPTUAL.value

    async def test_the_correction_reaches_the_model_with_what_is_true(self, store, mastery):
        wrong = "Interest is only ever worked out on the amount you first put in."
        teacher = Teacher()
        node = tutor(
            mastery=mastery,
            invoke=teacher,
            grade=grader(
                verdict="WRONG", diagnosis="CONCEPTUAL_MISUNDERSTANDING", misconception=wrong
            ),
        )
        first = await node(turn("Teach me about compound interest"))
        await node(turn("You always get EC$3", learning=learned(first)))

        assert wrong in teacher.last
        assert "joins the balance" in teacher.last, "the authored correction must be given"

    async def test_the_same_misconception_twice_is_not_duplicated(self, store, mastery):
        wrong = "Interest is only ever worked out on the amount you first put in."
        node = tutor(
            mastery=mastery,
            grade=grader(
                verdict="WRONG", diagnosis="CONCEPTUAL_MISUNDERSTANDING", misconception=wrong
            ),
        )
        state = learned(await node(turn("Teach me about compound interest")))
        for _ in range(3):
            state["awaiting_check_answer"] = True
            state["pending_check_id"] = "chk_1"
            state = learned(await node(turn("You always get EC$3", learning=state)))

        assert state["misconceptions"] == [wrong]


# ── scenario 9: demonstrated understanding stops the over-explaining ─────────


class TestScenario9StrongUnderstanding:
    @pytest.mark.asyncio
    async def test_what_they_have_shown_reaches_the_teaching_prompt(self, store, mastery):
        teacher = Teacher()
        node = tutor(mastery=mastery, invoke=teacher, grade=grader(verdict="CORRECT"))
        first = await node(turn("Teach me about compound interest"))
        second = await node(turn("EC$103", learning=learned(first)))
        await node(turn("more", learning=learned(second)))

        assert "answered correctly and unaided" in teacher.last
        assert "Compound interest" in teacher.last

    @pytest.mark.asyncio
    async def test_nothing_demonstrated_says_nothing_about_them(self, store, mastery):
        """A learner who has shown nothing is not described as having shown nothing."""
        teacher = Teacher()
        await tutor(mastery=mastery, invoke=teacher)(turn("What is compound interest?"))
        assert "answered correctly and unaided" not in teacher.last

    def test_difficulty_rises_only_once_they_have_earned_it(self):
        from app.agents.learn.tutor import difficulty_for

        assert difficulty_for(0, wrong_on_concept=0, hinted=False) == 0
        assert difficulty_for(2, wrong_on_concept=0, hinted=False) == 1
        # §15's "correct with support" rung does not promote.
        assert difficulty_for(2, wrong_on_concept=0, hinted=True) == 0
        assert difficulty_for(3, wrong_on_concept=2, hinted=False) == -1


# ── §17: the prerequisite step back ──────────────────────────────────────────


class TestPrerequisites:
    def test_the_curriculums_authored_chain_is_followed(self, store):
        """The curriculum says `goal` requires `save`, and the slugs are the link."""
        from app.curriculum.schema import load_all

        # `goal` is a curriculum concept id, so a teachable row with that slug
        # inherits its authored prerequisites without a new table.
        a_goal = TeachingConcept(
            id="CON-0002",
            slug="goal",
            locale="en",
            title="A saving goal",
            domain="saving",
            band_min="5-8",
            band_max="adult",
            bodies={"5-8": "A goal is the thing you are saving for."},
            status="approved",
        )
        store.load([a_goal, percentages()])

        found = find_prerequisite(
            a_goal, band="9-12", store=store, mastery={}, curriculum=load_all()
        )
        assert found is not None
        assert found.concept.slug == "save"
        assert found.source == "authored"

    def test_a_synthesised_concept_falls_back_to_a_heuristic_and_says_so(self, store):
        """`compound_interest` is in no module, so the guess must be labelled one."""
        from app.curriculum.schema import load_all

        found = find_prerequisite(
            compound(), band="9-12", store=store, mastery={}, curriculum=load_all()
        )
        assert found is not None
        assert found.concept.slug == "save"
        assert found.source == "heuristic", "a guess must never be filed as authored"

    def test_a_secure_prerequisite_is_not_stepped_back_to(self, store):
        """Sending a learner who HAS the prerequisite backwards is patronising."""
        from app.curriculum.schema import load_all

        found = find_prerequisite(
            compound(),
            band="9-12",
            store=store,
            mastery={"CON-0001": 3},
            curriculum=load_all(),
        )
        assert found is None

    @pytest.mark.asyncio
    async def test_repeated_failure_teaches_the_prerequisite_instead(self, store, mastery):
        node = tutor(
            mastery=mastery,
            grade=grader(verdict="WRONG", diagnosis="REASONING_ERROR"),
        )
        state = learned(await node(turn("Teach me about compound interest")))

        moves = []
        for _ in range(3):
            state["awaiting_check_answer"] = True
            state["pending_check_id"] = "chk_1"
            state = learned(await node(turn("EC$130", learning=state)))
            moves.append(state["move"])

        assert Move.STEP_BACK.value in moves
        # The step back teaches the earlier concept and says so in state.
        assert state["deferred_concept_id"] == "CON-0042"
        assert state["active_concept_id"] == "CON-0001"

    @pytest.mark.asyncio
    async def test_the_tutor_returns_to_what_the_step_back_interrupted(
        self, store, mastery
    ):
        """A step back that never comes back has just changed the subject."""
        node = tutor(mastery=mastery, grade=grader(verdict="CORRECT"))
        stepped_back = {
            "active_concept_id": "CON-0001",
            "deferred_concept_id": "CON-0042",
            "concepts_touched": ["CON-0042", "CON-0001"],
            "awaiting_check_answer": True,
            "pending_check_id": "chk_save",
        }
        result = await node(turn("keeping money for later", learning=stepped_back))

        state = learned(result)
        assert state["active_concept_id"] == "CON-0042", "it must resume the real lesson"
        assert state["move"] == Move.ADVANCE.value
        assert state["deferred_concept_id"] is None, "and stop deferring it"


# ── the grader itself ────────────────────────────────────────────────────────


class TestTheGrader:
    def test_an_authored_accept_term_settles_it_without_a_model(self):
        assert match_accept_list(check(), "EC$103") is True
        assert match_accept_list(check(), "103") is True

    def test_a_short_wrong_answer_is_decided_without_a_model(self):
        assert match_accept_list(check(), "EC$130") is False

    def test_a_long_answer_is_left_to_the_model(self):
        """An unmatched essay may still be right in its own words."""
        verdict = match_accept_list(
            check(),
            "you would have the hundred you started with plus whatever the bank put on",
        )
        assert verdict is None

    def test_a_question_with_no_accept_list_is_never_marked_wrong_on_it(self):
        """Punishing a learner for an author's omission is the bug this prevents."""
        bare = check(answer="", accept=())
        assert match_accept_list(bare, "anything at all") is None

    @pytest.mark.parametrize(
        "text", ["just tell me the answer", "what's the answer", "I give up", "show me how"]
    )
    def test_a_request_for_the_answer_is_recognised(self, text):
        assert triage(text) is Verdict.ASKS_FOR_ANSWER

    @pytest.mark.parametrize(
        "text", ["I don't know", "dunno", "idk", "not sure", "no idea", "?"]
    )
    def test_not_knowing_is_not_a_wrong_answer(self, text):
        assert triage(text) is Verdict.DONT_KNOW

    @pytest.mark.parametrize(
        "text", ["I don't understand", "I'm lost", "say that again", "makes no sense"]
    )
    def test_not_following_is_confusion_rather_than_not_knowing(self, text):
        """The two are answered differently, so they must be told apart here."""
        from app.agents.learn.tutor import sounds_confused

        assert sounds_confused(text)
        assert triage(text) is None, "confusion is not a verdict on the question"

    @pytest.mark.asyncio
    async def test_grading_survives_a_model_that_raises(self):
        async def explode(**_):
            raise RuntimeError("the grader is down")

        result = await evaluate_answer(
            "some long answer the accept list cannot decide about at all",
            item=check(),
            concept=compound(),
            invoke=explode,
        )
        # PARTIAL, not WRONG: we could not tell, and saying "wrong" would be a lie.
        assert result.verdict is Verdict.PARTIAL

    @pytest.mark.asyncio
    async def test_a_correct_answer_keeps_the_authored_explanation(self):
        result = await evaluate_answer("EC$103", item=check(), concept=compound())
        assert result.correct
        assert result.feedback == "Right -- the interest joins the money already there."
        assert result.source == "accept_list"

    def test_not_knowing_earns_no_mastery_penalty(self):
        from app.agents.learn.evaluate import Evaluation, evidence_for

        assert evidence_for(Evaluation(verdict=Verdict.DONT_KNOW), hinted=False) is None
        assert (
            evidence_for(Evaluation(verdict=Verdict.CORRECT), hinted=False) is Evidence.CORRECT
        )
        assert (
            evidence_for(Evaluation(verdict=Verdict.CORRECT), hinted=True)
            is Evidence.CORRECT_AFTER_HINTS
        )


# ── the strategy ladder in isolation ─────────────────────────────────────────


class TestTheStrategyLadder:
    def test_it_never_returns_the_rung_that_just_failed(self):
        for rung in LADDER[:-1]:
            assert next_strategy(rung.value) is not rung

    def test_it_settles_at_the_bottom_rather_than_wrapping(self):
        """Wrapping would restart the definition that failed five turns ago."""
        assert next_strategy(LADDER[-1].value) is LADDER[-1]

    def test_an_unknown_rung_starts_at_the_top(self):
        assert next_strategy(None) is Strategy.DEFINITION
        assert next_strategy("NOT_A_STRATEGY") is Strategy.DEFINITION

    def test_a_calculation_slip_shows_the_numbers_rather_than_an_analogy(self):
        """Their model is fine. An analogy would teach what they already know."""
        assert (
            next_strategy(Strategy.DEFINITION.value, diagnosis=Diagnosis.CALCULATION)
            is Strategy.NUMERIC_EXAMPLE
        )
