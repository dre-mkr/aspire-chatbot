"""The teaching turn: what the model is given, and what happens when it is not.

Two halves, and the second is the one that matters more.

The first half is that a model writes the lesson now, grounded in the knowledge
base, sometimes with a widget attached. The second is that every one of those
three capabilities can be absent -- no provider key, an empty corpus, a planner
outage -- and a child still gets taught. Each test below that ends in "not the
turn" is asserting that a dependency failed and the lesson survived it.

`invoke` is recorded rather than mocked at the module level, so the assertions
are about what reached the PROMPT. A test that only checked the return value
would pass just as happily if the knowledge base, the word cap and the
repetition history were all silently dropped on the way in.
"""

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
    """Both nodes, in order, as the graph runs them.

    `plan_widget` grounds and plans into state; `teach` reads that state and
    writes. Driving them together is what the tests are about -- driving
    `teach` alone would let a change that stopped `plan_widget` handing
    anything over pass every assertion below.
    """
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
        """A prompt asking for a different number than the gate enforces means a
        re-prompt on every single turn, forever."""
        for band in ("5-8", "9-12", "13-15"):
            model = Recorder()
            await run_teach(invoke=model, curriculum=curriculum, band=band)
            assert str(WORD_CAPS[band]) in model.system

    async def test_the_band_vocabulary_ladder_reaches_the_prompt(self, curriculum):
        """Both halves of it: what this band may say, and what it may not.

        The banned list matters more than the allowed one. `safety_out` strips
        a banned term after the fact, so a prompt that omits it buys a rewrite
        and a re-prompt on every turn that would have used the word.
        """
        model = Recorder()
        await run_teach(invoke=model, curriculum=curriculum, band="5-8")

        assert "compound" in model.system  # banned at 5-8
        assert "coin" in model.system  # on the 5-8 ladder

    async def test_it_is_told_not_to_ask_its_own_question(self, curriculum):
        """`check` asks the check question on the next node. Two questions in a
        row is the lesson talking over itself."""
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
        """One graph, three names, three audiences -- the same shape as Q&A.

        A signed-out sample must not be grounded in rows written for enrolled
        families, and a guardian preview is an adult reading adult material.
        """
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
        """The inline sentinel path is hard-disabled. See `teach._widget_prompt`.

        One model call used to produce the lesson AND the widget's JSON, between
        `⟦widget⟧` markers inline in the prose. Three things followed: the widget's
        JSON competed with the lesson for the word budget, the transport stopped
        forwarding at the opening marker, and an UNTERMINATED marker caused the
        buffer to be discarded -- silently truncating the lesson mid-sentence.

        That last one is the reported defect's mechanism, and it is not fixable by
        prompting: a client shown half a JSON object has no correct move, so
        buffering is right and inline composition is what has to go. Widgets now
        come from `agents/learn/widgets.py`, on a separate task, from a separate
        call, emitted as their own directive AFTER validated prose.

        The planner still RUNS -- its accuracy stays measurable by
        `evals/widgets.jsonl` -- and its choice no longer reaches this prompt.
        """
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
        """The model can be handed a composition prompt and write prose anyway.

        Recording the kind on the strength of having ASKED means the planner
        then avoids a primitive this child has never seen -- and the more often
        the model declines, the more primitives get struck off.
        """
        async def plan(**kwargs):
            return Plan(kind="compare")

        update = await run_teach(
            plan=plan,
            invoke=Recorder("Saving is keeping some for later."),  # no sentinel
            curriculum=curriculum,
        )

        assert update["learning"]["last_widget_kinds"] == []

    async def test_this_node_records_no_widget_at_all_now(self, curriculum):
        """`last_widget_kinds` stays empty on the authored-lesson path.

        The rule it protects is unchanged and still right: only a kind that
        actually REACHED the reader may suppress that primitive next time, or the
        "do not repeat" rule starts excluding primitives a child has never seen.
        This node no longer emits any, so it records none -- even when the model
        writes something that looks like a widget block, which is now just
        characters in prose that `sentinel.split` will lift out.

        KNOWN GAP, recorded rather than hidden: curriculum lessons carry no widget
        until this node moves onto `widgets.build_widget`. A lesson with no widget
        is a complete lesson, which is the premise of the whole workstream.
        """
        async def plan(**kwargs):
            return Plan(kind="compare")

        update = await run_teach(
            plan=plan,
            invoke=Recorder('Look. ⟦widget⟧{"kind":"compare"}⟦/widget⟧ Which?'),
            curriculum=curriculum,
        )

        assert update["learning"]["last_widget_kinds"] == []

    async def test_the_authored_fallback_claims_no_widget_was_shown(self, curriculum):
        """A widget planned but never composed must not count as seen.

        Otherwise the "do not repeat a primitive" rule starts excluding
        primitives this child has never actually been shown.
        """
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
        """The case `recent_openings` cannot see, and the one that was reported.

        Learning state is checkpointed per thread, so a learner who comes back
        tomorrow and opens a new chat has an empty openings list. Spaced
        repetition then brings the concept round again, the prompt is identical
        to yesterday's, and the model writes close to the same words.
        `concept_seen_before` comes off the mastery row, which is the only thing
        about a learner that outlives the conversation.
        """
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
        """Exact openings beat "seen it sometime". Sending both would ask the
        model to avoid two things at once and get a worse answer than either."""
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
        """A live session produced: "Now hand the idea back in your own words:
        saving means keeping money instead of using it now."

        That is the model reading the instruction "end by handing the
        conversation back" as a line of dialogue. The instruction is now phrased
        as a stopping condition rather than an action, and the prohibition is
        explicit.
        """
        model = Recorder()
        await run_teach(invoke=model, curriculum=curriculum)

        assert "Never describe what you are doing" in model.system
        assert "hand" not in model.system.lower().split("HOW TO SAY IT")[-1]

    async def test_a_first_teaching_is_not_told_to_avoid_anything(self, curriculum):
        """There is nothing to differ from yet, and saying so invites the model
        to be different from the plainest correct way of putting it."""
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
        """The floor. This is byte-for-byte what the node produced before there
        was a model call in it, which is what lets a keyless deployment teach."""
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
        """A model that returns "" has not written a lesson. Serving it would
        show a child an empty message with two chips under it."""
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
        """A child who has just been shown an answer needs a sentence, not a
        slider. `make_reteach` takes no planner at all -- asserted because the
        obvious "improvement" is to give it one."""
        import inspect

        assert "plan" not in inspect.signature(teaching.make_reteach).parameters

    async def test_it_falls_back_to_the_authored_last_point(self, curriculum, lesson):
        node = teaching.make_reteach(curriculum, invoke=None)
        update = await node(state_for())
        assert said(update) == lesson.teach_for("9-12")[-1]

    async def test_it_still_records_the_wrong_outcome(self, curriculum):
        """The reveal path must reach `mastery_update` carrying a wrong answer,
        model or no model."""
        node = teaching.make_reteach(curriculum, invoke=Recorder())
        update = await node(state_for())

        assert update["learning"]["phase"] == "updating_mastery"
        assert update["learning"]["outcome"] == "wrong"


# ── the machine around it ────────────────────────────────────────────────────


class TestAskingForADifferentLesson:
    """Reported live: "teach me something else" -> "Good question! Now, back to
    what we were doing."

    `is_off_topic` asks whether the message contains a money word. It does not,
    so the most on-topic thing a learner can say inside a lesson was routed to
    the digression handler and steered back into the lesson they had just asked
    to leave.
    """

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
            # These are why the phrase must be attached to a teaching verb.
            "i want to buy something else with my money",
            "i saved something else last week",
            "my goal is a new bike",
        ],
    )
    async def test_these_do_not(self, text):
        """A false positive abandons a lesson somebody was halfway through,
        which is worse than the digression it replaces.

        Bare "next" matters most: it is a chip on the wrap-up and reteach turns
        where it means continue, and capturing it would turn a tap meaning
        "carry on" into a discarded lesson.
        """
        from app.agents.learn.graph import wants_a_different_lesson

        assert wants_a_different_lesson(text) is False

    async def test_it_places_a_new_lesson_in_the_same_turn(self, curriculum):
        """Not next turn. A learner who asks for something else and gets nothing
        back has been ignored."""
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
        """The move-on check runs first and must not swallow the case the
        digression handler exists for."""
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
        """"Back to what we were doing" is the reprimand `_digress` exists to
        avoid, and it was what `16-18` and `adult` got -- they were missing from
        the table and fell to a fallback that named nothing. `adult` is the band
        a guardian previews in, which is where it was seen.
        """
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
        """Non-scoring is not read-only. The parent sees what the child sees --
        the teaching, the widget, the check question -- or the preview is not
        showing them what their child is being taught."""
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
        """The end-to-end property: generated prose changes the words and
        nothing else. Teach still hands to check, and check still asks the
        authored question with its authored options."""
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
        """teach -> safety_out -> transport, in one test, because every seam
        between them was written before anything crossed it.

        The three failures this would have caught, each of which was live:
        `safety_out` counting the JSON against the band cap and re-prompting it
        away; `WIDGET_AGENTS` naming one of the three learning agents; and the
        composed widget never being reachable at all because the node it comes
        from did not call a model.

        Fed to the transport in seven-character chunks so the markers split
        across boundaries, which is the case the interceptor's buffer exists for.
        """
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
        """The planner's JSON must never reach a child, and the ONLY thing
        stopping it is the node's name.

        `stream_mode="messages"` streams tokens from every model call in the
        graph and the transport suppresses them by `langgraph_node`. Planning
        inside `teach` -- which is where it naturally wants to live, next to the
        thing it plans for -- puts `{"kind": "compare", "rationale": "..."}` in
        front of the lesson, exactly as the classifier's routing JSON once
        arrived in front of an answer.

        So: the node is named `plan_widget`, that name is in `INTERNAL_NODES`,
        and `teach` makes no planning call of its own. All three are asserted,
        because any one of them alone is a rename away from being false.
        """
        import inspect

        from app.graph.stream_interceptor import INTERNAL_NODES

        graph = build_learn_graph(curriculum=None)
        assert "plan_widget" in graph.get_graph().nodes
        assert "plan_widget" in INTERNAL_NODES
        assert "teach" not in INTERNAL_NODES  # it streams; that is its job
        assert "plan" not in inspect.signature(teaching.make_teach).parameters

    async def test_a_resumed_teaching_turn_still_grounds_and_plans(self, curriculum):
        """Entry from a `teaching` phase must land on `plan_widget`.

        A lesson spans turns and the entry point IS the resumption logic. Going
        straight to `teach` would leave `retrieved` and `pending_widget` unset,
        so a resumed lesson would quietly be the ungrounded, widgetless one.
        """
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
        """Named here because this file is about adding a model to the lesson,
        and this is the thing that must not acquire one."""
        from app.agents.learn.graph import grade_answer
        from app.curriculum.schema import CheckQuestion

        question = CheckQuestion(
            id="q1", prompt={"9-12": "Which one?"}, options=["Saving", "Spending"], answer=0
        )
        assert grade_answer(question, "Saving") is True
        assert grade_answer(question, "Spending") is False
