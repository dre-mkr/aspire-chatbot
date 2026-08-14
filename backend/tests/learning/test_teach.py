"""The teaching turn: what the model is given, and what happens when it is not."""

from __future__ import annotations

import pytest

from app.agents.learn import teach as teaching
from app.agents.learn.graph import build_learn_graph
from app.agents.learn.state import OPENING_WORDS, new_session, remember_opening
from app.curriculum.schema import load_all
from app.graph.nodes.safety_out import WORD_CAPS
from app.graph.state import KBChunk, initial_state
from app.widgets.planner import Plan

pytestmark = pytest.mark.asyncio

LESSON = "l01_what_is_saving"


@pytest.fixture(scope="module")
def curriculum():
    return load_all(refresh=True)


@pytest.fixture
def lesson(curriculum):
    return curriculum.lessons[LESSON]


class Recorder:
    """An `invoke` that returns a fixed string and keeps every prompt it saw."""

    def __init__(self, reply: str = "Saving is keeping some of it for later. Ready?"):
        self.reply = reply
        self.prompts: list[str] = []
        self.raises: BaseException | None = None

    async def __call__(self, messages):
        self.prompts.append(messages[0].content)
        if self.raises is not None:
            raise self.raises
        return self.reply

    @property
    def system(self) -> str:
        assert self.prompts, "the model was never called"
        return self.prompts[-1]


def state_for(band: str = "9-12", *, agent: str = "learn_agent", **overrides):
    state = initial_state(
        session_id="s-teach",
        user_id="u-teach",
        device_id="d",
        persona="stella",
        age_band=band,
        account_status="beneficiary",
    )
    state["active_agent"] = agent
    state["learning"] = dict(new_session(learner_id="u-teach"), lesson_id=LESSON, phase="teaching")
    state.update(overrides)
    return state


def chunks(*texts: str) -> list[KBChunk]:
    return [KBChunk(kb_id=f"ASP-{i:03d}", content=text) for i, text in enumerate(texts, 1)]


async def run_teach(*, retrieve=None, plan=None, invoke=None, curriculum=None, **state_kwargs):
    """Both nodes, in order, as the graph runs them."""
    state = state_for(**state_kwargs)
    prepared = await teaching.make_plan_widget(
        curriculum, retrieve=retrieve, plan=plan
    )(state)
    state.update(prepared)
    return await teaching.make_teach(curriculum, invoke=invoke)(state)


def said(update) -> str:
    return update["messages"][0].content


# ── the model writes it ──────────────────────────────────────────────────────


class TestTheModelWritesTheLesson:
    async def test_the_reply_is_the_models_words(self, curriculum, lesson):
        model = Recorder("Money you keep today is money you still have on Friday.")
        update = await run_teach(invoke=model, curriculum=curriculum)

        assert said(update) == "Money you keep today is money you still have on Friday."
        assert said(update) != teaching.authored_body(lesson, "9-12")

    async def test_the_teach_points_are_in_the_prompt_as_the_spine(
        self, curriculum, lesson
    ):
        """Authored content is what the model must convey, not what it may ignore."""
        model = Recorder()
        await run_teach(invoke=model, curriculum=curriculum)

        for point in lesson.teach_for("9-12"):
            assert point in model.system

    async def test_the_prompt_states_the_bands_own_word_cap(self, curriculum):
        """A prompt naming a different cap than the gate enforces means a re-prompt every turn."""
        for band in ("5-8", "9-12", "13-15"):
            model = Recorder()
            await run_teach(invoke=model, curriculum=curriculum, band=band)
            assert str(WORD_CAPS[band]) in model.system

    async def test_the_band_vocabulary_ladder_reaches_the_prompt(self, curriculum):
        """Both halves of it: what this band may say, and what it may not."""
        model = Recorder()
        await run_teach(invoke=model, curriculum=curriculum, band="5-8")

        assert "compound" in model.system  # banned at 5-8
        assert "coin" in model.system  # on the 5-8 ladder

    async def test_it_is_told_not_to_ask_its_own_question(self, curriculum):
        """`check` asks the check question on the next node."""
        model = Recorder()
        await run_teach(invoke=model, curriculum=curriculum)
        flat = " ".join(model.system.split())
        assert "do not ask one" in flat
        assert "do not invite them to reply" in flat


# ── grounding ────────────────────────────────────────────────────────────────


class TestKnowledgeBaseGrounding:
    async def test_the_retrieved_rows_reach_the_prompt(self, curriculum):
        async def retrieve(query, k, audience):
            return chunks("An ASPIRE account opens with EC$1,000 from the government.")

        model = Recorder()
        await run_teach(retrieve=retrieve, invoke=model, curriculum=curriculum)

        assert "EC$1,000 from the government" in model.system

    async def test_the_query_is_built_from_the_lesson_not_the_chat(self, curriculum, lesson):
        seen: list[tuple] = []

        async def retrieve(query, k, audience):
            seen.append((query, k, audience))
            return []

        await run_teach(retrieve=retrieve, invoke=Recorder(), curriculum=curriculum)

        query, k, audience = seen[0]
        assert lesson.objective in query
        assert k == teaching.RETRIEVE_K
        assert audience == "youth"

    @pytest.mark.parametrize(
        ("agent", "audience"),
        [
            ("learn_agent", "youth"),
            ("learning_sample", "public"),
            ("learning_preview", "all"),
        ],
    )
    async def test_the_corpus_slice_follows_the_agent_name(
        self, agent, audience, curriculum
    ):
        """One graph, three names, three audiences -- the same shape as Q&A."""
        seen: list[str] = []

        async def retrieve(query, k, aud):
            seen.append(aud)
            return []

        await run_teach(
            retrieve=retrieve, invoke=Recorder(), curriculum=curriculum, agent=agent
        )
        assert seen == [audience]

    async def test_the_model_is_told_not_to_quote_or_cite(self, curriculum):
        """A lesson is not a Q&A answer. "[ASP-042]" means nothing to a child."""
        async def retrieve(query, k, audience):
            return chunks("Applications close on 31 March.")

        model = Recorder()
        await run_teach(retrieve=retrieve, invoke=model, curriculum=curriculum)

        assert "Never quote it" in model.system
        assert "never cite a reference number" in model.system

    async def test_with_nothing_retrieved_it_is_told_to_invent_no_figures(
        self, curriculum
    ):
        async def retrieve(query, k, audience):
            return []

        model = Recorder()
        await run_teach(retrieve=retrieve, invoke=model, curriculum=curriculum)

        assert "no amounts, dates or deadlines" in model.system

    async def test_a_retrieval_failure_costs_grounding_not_the_turn(self, curriculum):
        async def retrieve(query, k, audience):
            raise RuntimeError("pgvector is down")

        model = Recorder()
        update = await run_teach(retrieve=retrieve, invoke=model, curriculum=curriculum)

        assert said(update) == model.reply
        assert "no reference material" in model.system


# ── widgets ──────────────────────────────────────────────────────────────────


class TestTheWidget:
    async def test_a_planned_kind_no_longer_reaches_the_teaching_prompt(self, curriculum):
        """The inline sentinel path is hard-disabled."""
        async def plan(**kwargs):
            return Plan(kind="compare", rationale="asked what it is")

        model = Recorder()
        await run_teach(plan=plan, invoke=model, curriculum=curriculum)

        assert "⟦widget⟧" not in model.system
        assert "Emit ONE compare widget" not in model.system

    async def test_the_planner_sees_what_it_needs_to_avoid_repeating(self, curriculum):
        seen: dict = {}

        async def plan(**kwargs):
            seen.update(kwargs)
            return Plan(kind=None)

        await run_teach(
            plan=plan,
            invoke=Recorder(),
            curriculum=curriculum,
            learning=dict(
                new_session(),
                lesson_id=LESSON,
                phase="teaching",
                last_widget_kinds=["compare", "timeline"],
            ),
        )

        assert seen["recent_widget_kinds"] == ["compare", "timeline"]
        assert seen["concept_id"] == "save"
        assert seen["age_band"] == "9-12"

    async def test_null_from_the_planner_adds_no_instructions(self, curriculum):
        async def plan(**kwargs):
            return Plan(kind=None, rationale="acknowledgement")

        model = Recorder()
        await run_teach(plan=plan, invoke=model, curriculum=curriculum)

        assert "⟦widget⟧" not in model.system

    async def test_a_planner_failure_costs_the_widget_not_the_turn(self, curriculum):
        async def plan(**kwargs):
            raise RuntimeError("the small model timed out")

        model = Recorder()
        update = await run_teach(plan=plan, invoke=model, curriculum=curriculum)

        assert said(update) == model.reply
        assert "⟦widget⟧" not in model.system

    async def test_a_kind_asked_for_but_not_written_is_not_remembered(
        self, curriculum
    ):
        """The model can be handed a composition prompt and write prose anyway."""
        async def plan(**kwargs):
            return Plan(kind="compare")

        update = await run_teach(
            plan=plan,
            invoke=Recorder("Saving is keeping some for later."),  # no sentinel
            curriculum=curriculum,
        )

        assert update["learning"]["last_widget_kinds"] == []

    async def test_this_node_records_no_widget_at_all_now(self, curriculum):
        """`last_widget_kinds` stays empty on the authored-lesson path."""
        async def plan(**kwargs):
            return Plan(kind="compare")

        update = await run_teach(
            plan=plan,
            invoke=Recorder('Look. ⟦widget⟧{"kind":"compare"}⟦/widget⟧ Which?'),
            curriculum=curriculum,
        )

        assert update["learning"]["last_widget_kinds"] == []

    async def test_the_authored_fallback_claims_no_widget_was_shown(self, curriculum):
        """A widget planned but never composed must not count as seen."""
        async def plan(**kwargs):
            return Plan(kind="compare")

        update = await run_teach(plan=plan, invoke=None, curriculum=curriculum)

        assert update["learning"]["last_widget_kinds"] != ["compare"]


# ── repetition ───────────────────────────────────────────────────────────────


class TestItDoesNotRepeatItself:
    async def test_the_opening_is_recorded(self, curriculum):
        model = Recorder("Saving is keeping some of your money for later on.")
        update = await run_teach(invoke=model, curriculum=curriculum)

        assert update["learning"]["recent_openings"] == [
            " ".join(model.reply.split()[:OPENING_WORDS])
        ]

    async def test_a_second_teaching_is_shown_how_the_first_one_opened(
        self, curriculum
    ):
        model = Recorder()
        await run_teach(
            invoke=model,
            curriculum=curriculum,
            learning=dict(
                new_session(),
                lesson_id=LESSON,
                phase="teaching",
                recent_openings=["Saving means keeping money for later"],
            ),
        )

        assert "Saving means keeping money for later" in model.system
        assert "begin differently" in model.system

    async def test_a_learner_returning_on_another_day_still_gets_a_new_angle(
        self, curriculum
    ):
        """The case `recent_openings` cannot see, and the one that was reported."""
        model = Recorder()
        await run_teach(
            invoke=model,
            curriculum=curriculum,
            learning=dict(
                new_session(),
                lesson_id=LESSON,
                phase="teaching",
                recent_openings=[],  # a fresh conversation
                concept_seen_before=True,  # but not a fresh learner
            ),
        )

        assert "on another day" in model.system
        assert "do not lead with the definition" in model.system

    async def test_the_in_conversation_signal_wins_when_both_are_present(
        self, curriculum
    ):
        """Exact openings beat "seen it sometime"."""
        model = Recorder()
        await run_teach(
            invoke=model,
            curriculum=curriculum,
            learning=dict(
                new_session(),
                lesson_id=LESSON,
                phase="teaching",
                recent_openings=["Saving means keeping money for later"],
                concept_seen_before=True,
            ),
        )

        assert "Saving means keeping money for later" in model.system
        assert "on another day" not in model.system

    async def test_it_is_told_not_to_narrate_what_it_is_doing(self, curriculum):
        """A live session narrated the instruction itself, so the prompt forbids narration."""
        model = Recorder()
        await run_teach(invoke=model, curriculum=curriculum)

        assert "Never describe what you are doing" in model.system
        assert "hand" not in model.system.lower().split("HOW TO SAY IT")[-1]

    async def test_a_first_teaching_is_not_told_to_avoid_anything(self, curriculum):
        """Nothing to differ from yet, so asking for difference only invites a worse opening."""
        model = Recorder()
        await run_teach(invoke=model, curriculum=curriculum)
        assert "begin differently" not in model.system

    async def test_the_lessons_teach_count_climbs(self, curriculum):
        update = await run_teach(invoke=Recorder(), curriculum=curriculum)
        assert update["learning"]["teach_count"][LESSON] == 1

    async def test_openings_are_capped_and_deduplicated(self):
        state = new_session()
        for text in ("one two three", "one two three", "four five six", "seven eight"):
            state["recent_openings"] = remember_opening(state, text)

        assert state["recent_openings"] == ["one two three", "four five six", "seven eight"]

    async def test_an_opening_is_only_its_first_few_words(self):
        long = " ".join(f"w{i}" for i in range(40))
        assert len(remember_opening(new_session(), long)[0].split()) == OPENING_WORDS


# ── degradation ──────────────────────────────────────────────────────────────


class TestWithoutAModel:
    async def test_no_model_serves_the_authored_lesson_unchanged(
        self, curriculum, lesson
    ):
        """The floor."""
        update = await run_teach(invoke=None, curriculum=curriculum)
        assert said(update) == teaching.authored_body(lesson, "9-12")

    async def test_a_model_failure_falls_back_rather_than_failing_the_turn(
        self, curriculum, lesson
    ):
        model = Recorder()
        model.raises = RuntimeError("429")
        update = await run_teach(invoke=model, curriculum=curriculum)

        assert said(update) == teaching.authored_body(lesson, "9-12")

    async def test_an_empty_reply_falls_back_too(self, curriculum, lesson):
        """A model that returns "" has not written a lesson."""
        update = await run_teach(invoke=Recorder("   "), curriculum=curriculum)
        assert said(update) == teaching.authored_body(lesson, "9-12")

    async def test_the_turn_still_advances_and_still_offers_chips(self, curriculum):
        update = await run_teach(invoke=None, curriculum=curriculum)
        assert update["learning"]["phase"] == "checking"
        assert len(update["quick_replies"]) >= 2


# ── reteach ──────────────────────────────────────────────────────────────────


class TestReteach:
    async def test_it_explains_why_rather_than_restating_the_answer(self, curriculum):
        model = Recorder("Because the money is still yours -- it just has not been spent.")
        node = teaching.make_reteach(curriculum, invoke=model)
        update = await node(state_for())

        assert said(update) == model.reply
        assert "WHY it is that" in model.system
        assert "do not ask another" in model.system

    async def test_it_says_nothing_about_the_attempt(self, curriculum):
        model = Recorder()
        node = teaching.make_reteach(curriculum, invoke=model)
        await node(state_for())
        assert "not say anything about their attempt" in model.system

    async def test_it_plans_no_widget(self, curriculum):
        """A child who has just been shown an answer needs a sentence, not a slider."""
        import inspect

        assert "plan" not in inspect.signature(teaching.make_reteach).parameters

    async def test_it_falls_back_to_the_authored_last_point(self, curriculum, lesson):
        node = teaching.make_reteach(curriculum, invoke=None)
        update = await node(state_for())
        assert said(update) == lesson.teach_for("9-12")[-1]

    async def test_it_still_records_the_wrong_outcome(self, curriculum):
        """The reveal path must reach `mastery_update` with a wrong answer, model or not."""
        node = teaching.make_reteach(curriculum, invoke=Recorder())
        update = await node(state_for())

        assert update["learning"]["phase"] == "updating_mastery"
        assert update["learning"]["outcome"] == "wrong"


# ── the machine around it ────────────────────────────────────────────────────


class TestAskingForADifferentLesson:
    """Reported live: "teach me something else" -> "Good question!"""

    @pytest.mark.parametrize(
        "text",
        [
            "teach me something else",
            "can we do something different",
            "next topic",
            "a different lesson",
            "change the subject",
            "show me another topic",
            "skip this",
        ],
    )
    async def test_these_ask_to_move_on(self, text):
        from app.agents.learn.graph import wants_a_different_lesson

        assert wants_a_different_lesson(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "next",  # an authored chip meaning "continue"
            "Saving",
            "ok",
            "you keep the money for later",
            "why is the sky blue",
            # All three contain "something else" / "new" and are lesson answers.
            "i want to buy something else with my money",
            "i saved something else last week",
            "my goal is a new bike",
        ],
    )
    async def test_these_do_not(self, text):
        """A false positive abandons a lesson somebody was halfway through."""
        from app.agents.learn.graph import wants_a_different_lesson

        assert wants_a_different_lesson(text) is False

    async def test_it_places_a_new_lesson_in_the_same_turn(self, curriculum):
        """Not next turn."""
        from langchain_core.messages import HumanMessage

        graph = build_learn_graph(curriculum=curriculum)
        state = initial_state(
            session_id="s",
            user_id=None,
            device_id="d",
            persona="stella",
            age_band="9-12",
            account_status="prospect",
        )
        state["active_agent"] = "learn_agent"

        first = await graph.ainvoke(state)
        first["messages"] = list(first["messages"]) + [
            HumanMessage(content="teach me something else")
        ]
        # What `safety_in` actually sets for this message, and used to win.
        first["safety_flags"] = {"off_topic": True}

        second = await graph.ainvoke(first)

        assert second["learning"]["lesson_id"] != first["learning"]["lesson_id"]
        assert second["learning"]["phase"] == "checking"
        assert "back to" not in second["messages"][-2].content.lower()

    async def test_a_real_digression_is_still_steered_back(self, curriculum):
        """The move-on check runs first and must not swallow a real digression."""
        from langchain_core.messages import HumanMessage

        graph = build_learn_graph(curriculum=curriculum)
        state = initial_state(
            session_id="s",
            user_id=None,
            device_id="d",
            persona="stella",
            age_band="9-12",
            account_status="prospect",
        )
        state["active_agent"] = "learn_agent"

        first = await graph.ainvoke(state)
        first["messages"] = list(first["messages"]) + [
            HumanMessage(content="why is the sky blue")
        ]
        first["safety_flags"] = {"off_topic": True}

        second = await graph.ainvoke(first)

        assert second["learning"]["lesson_id"] == first["learning"]["lesson_id"]
        assert second["learning"]["digression_count"] == 1

    @pytest.mark.parametrize("band", ["5-8", "9-12", "13-15", "16-18", "adult"])
    async def test_every_band_names_what_it_is_steering_back_to(
        self, band, curriculum
    ):
        """Every band must name the lesson, not fall back on "back to what we were doing"."""
        from app.agents.learn.graph import _digress

        lesson = curriculum.lessons[LESSON]
        state = state_for(band=band)

        for count in (0, 5):  # under the cap, and past it
            update = _digress(state, {"digression_count": count}, lesson)
            said = update["messages"][0].content
            assert "what we were doing" not in said, (band, count)
            assert said.rstrip().endswith("."), (band, count)


class TestWhoGetsScored:
    """A preview is watched, not taken. Reported from a live aurora session."""

    @pytest.mark.parametrize("agent", ["learning_preview", "learning_sample"])
    async def test_a_watched_lesson_scores_nobody(self, agent):
        from app.agents.learn.graph import _learner

        state = state_for(agent=agent)
        assert state["user_id"]  # signed in, and still not the learner
        assert _learner(state) is None

    async def test_the_real_lesson_still_scores_the_learner(self):
        from app.agents.learn.graph import _learner

        assert _learner(state_for(agent="learn_agent")) == "u-teach"

    async def test_a_guardian_still_gets_the_whole_lesson(self, curriculum):
        """Non-scoring is not read-only."""
        graph = build_learn_graph(curriculum=curriculum, invoke=Recorder())
        state = initial_state(
            session_id="s",
            user_id="u-parent",
            device_id="d",
            persona="aurora",
            age_band="adult",
            account_status="guardian",
        )
        state["active_agent"] = "learning_preview"

        result = await graph.ainvoke(state)

        assert result["learning"]["lesson_id"]
        assert result["learning"]["phase"] == "checking"
        assert result["learning"]["question_id"]


class TestTheGraphStillHoldsItsShape:
    async def test_a_model_backed_lesson_still_reaches_the_check_question(
        self, curriculum
    ):
        """The end-to-end property: generated prose changes the words and nothing else."""
        graph = build_learn_graph(curriculum=curriculum, invoke=Recorder())
        state = initial_state(
            session_id="s",
            user_id=None,
            device_id="d",
            persona="stella",
            age_band="9-12",
            account_status="prospect",
        )
        state["active_agent"] = "learn_agent"

        result = await graph.ainvoke(state)

        assert result["learning"]["phase"] == "checking"
        assert result["learning"]["question_id"]
        assert len(result["quick_replies"]) >= 2

    async def test_a_widget_travels_the_whole_way_to_a_directive(self, curriculum):
        """teach -> safety_out -> transport, exercised end to end in one test."""
        import json

        from app.graph.nodes.safety_out import make_safety_out
        from app.graph.stream_interceptor import StreamInterceptor

        widget = json.load(
            open("app/widgets/fewshots/compare_9-12.json", encoding="utf-8")
        )[0]["widget"]
        composed = (
            "Money you keep is money you still have on Friday. "
            f"⟦widget⟧{json.dumps(widget, ensure_ascii=False)}⟦/widget⟧"
            " Which one would you pick?"
        )

        async def invoke(messages):
            return composed

        async def plan(**kwargs):
            return Plan(kind="compare")

        state = state_for()
        update = await run_teach(plan=plan, invoke=invoke, curriculum=curriculum)
        state["messages"] = list(state["messages"]) + update["messages"]
        state["quick_replies"] = update["quick_replies"]

        gated = await make_safety_out(None)(state)
        text = (
            gated["messages"][0].content
            if "messages" in gated
            else state["messages"][-1].content
        )
        assert gated["safety_flags"]["outbound"] == {"widgets_carried": 1}

        machine = StreamInterceptor(active_agent="learn_agent", age_band="9-12", locale="en")
        events = []
        for start in range(0, len(text), 7):
            events.extend(machine.feed(text[start : start + 7]))

        directives = [event for event in events if event.event == "directive"]
        prose = "".join(event.data["t"] for event in events if event.event == "token")

        assert len(directives) == 1
        assert directives[0].data["d"]["payload"]["kind"] == "compare"
        assert "⟦" not in prose
        assert prose.strip().startswith("Money you keep")

    async def test_the_planner_runs_in_a_node_the_transport_suppresses(self):
        """The planner's JSON is kept from the child only by the node's name."""
        import inspect

        from app.graph.stream_interceptor import INTERNAL_NODES

        graph = build_learn_graph(curriculum=None)
        assert "plan_widget" in graph.get_graph().nodes
        assert "plan_widget" in INTERNAL_NODES
        assert "teach" not in INTERNAL_NODES  # it streams; that is its job
        assert "plan" not in inspect.signature(teaching.make_teach).parameters

    async def test_a_resumed_teaching_turn_still_grounds_and_plans(self, curriculum):
        """Entry from a `teaching` phase must land on `plan_widget`."""
        from app.agents.learn.graph import _entry

        state = state_for()
        state["learning"] = dict(state["learning"], phase="teaching")
        assert _entry(state) == "plan_widget"

    async def test_the_pending_widget_is_cleared_once_composed(self, curriculum):
        """Left set, a turn re-entering `teach` composes the same widget twice."""
        async def plan(**kwargs):
            return Plan(kind="compare")

        update = await run_teach(plan=plan, invoke=Recorder(), curriculum=curriculum)
        assert update["learning"]["pending_widget"] is None

    async def test_grading_is_untouched_by_any_of_this(self):
        """Grading must not acquire a model just because the lesson around it gained one."""
        from app.agents.learn.graph import grade_answer
        from app.curriculum.schema import CheckQuestion

        question = CheckQuestion(
            id="q1", prompt={"9-12": "Which one?"}, options=["Saving", "Spending"], answer=0
        )
        assert grade_answer(question, "Saving") is True
        assert grade_answer(question, "Spending") is False


# ── the tutor's decline, in the reader's language ────────────────────────────


class TestTheDeclineSpeaksTheReadersLanguage:
    """
    `render.decline_text` was English with no locale parameter anywhere in
    scope, so a Spanish or French child who asked about something the tutor
    could not resolve was declined in English -- inside an otherwise translated
    lesson. Both callers had the locale to hand; only the parameter was missing.
    """

    @pytest.mark.parametrize(
        ("locale", "marker"),
        [("en", "I do not know"), ("es", "todavía no me la sé"), ("fr", "je ne la sais pas encore")],
    )
    async def test_a_young_learner_is_declined_in_their_own_words(self, locale, marker):
        from app.agents.learn.render import decline_text

        assert marker in decline_text("5-8", (), locale)

    async def test_an_unknown_locale_falls_back_to_english(self):
        from app.agents.learn.render import decline_text

        assert decline_text("5-8", (), "de") == decline_text("5-8", (), "en")

    async def test_the_offer_is_localised_around_the_corpus_title(self):
        """
        The frame is translated; the concept title is quoted as the corpus has
        it. Exactly what `escalation/decline.py` already does, and the same
        reason: the corpus is English and translating a title would invent one.
        """
        from app.agents.learn.render import decline_text

        class _Concept:
            def __init__(self, title):
                self.title = title

        text = decline_text("9-12", [_Concept("Saving basics")], "es")

        assert "Puedo enseñarte sobre" in text
        assert "saving basics" in text
