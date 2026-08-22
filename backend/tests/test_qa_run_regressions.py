"""The four defects the 21 Aug reasoning run found, pinned so they stay fixed.

Every case here is a verbatim turn from `qa/battle-plan/evidence/`, not an
invented one. The transcripts are the specification: each test names the file
and the turn it comes from, so a failure can be read against what a real reader
actually saw.
"""

from __future__ import annotations

import pytest

from app.agents.learn.graph import is_an_answer
from app.agents.qa.nodes import GENERATE_SYSTEM, is_self_contained_sum, qa_agent_role
from app.graph.access import allowed_agents
from app.graph.nodes.classify import TEACHING_AGENTS, routable
from app.prompting.global_rules import GLOBAL

USER = "user-1"


# ── 1. the router was never consulted ────────────────────────────────────────


class TestTheRouterGetsAChoice:
    """`rsn-*.md`: 22 of 22 nova turns were answered by `qa_agent`.

    Not because the router chose it 22 times -- because `routable()` returned a
    single candidate and `classify` took its no-model-call shortcut. A row with
    one option is a row with no routing.
    """

    @pytest.mark.parametrize(
        "persona,band",
        [
            ("stella", "5-8"),
            ("stella", "9-12"),
            ("orion", "13-15"),
            ("orion", "16-18"),
            ("aurora", "adult"),
            ("nova", "adult"),
            ("guest", "adult"),
        ],
    )
    def test_every_signed_in_row_offers_more_than_one_agent(self, persona, band):
        granted = allowed_agents(persona, band, "prospect", user_id=USER)
        assert len(routable(granted)) > 1, (
            f"{persona}/{band} offers the router one candidate, so `classify` "
            "short-circuits and no routing decision is ever made"
        )

    def test_the_anonymous_row_offers_more_than_one_too(self):
        granted = allowed_agents("guest", "adult", "prospect", user_id=None)
        assert len(routable(granted)) > 1

    @pytest.mark.parametrize(
        "persona,band",
        [
            ("stella", "5-8"),
            ("orion", "13-15"),
            ("aurora", "adult"),
            ("nova", "adult"),
        ],
    )
    def test_every_reader_can_reach_a_teacher(self, persona, band):
        """A question about how something works must have somewhere to go."""
        granted = routable(allowed_agents(persona, band, "prospect", user_id=USER))
        assert set(granted) & set(TEACHING_AGENTS), (
            f"{persona}/{band} can only be answered by fact-lookup"
        )


class TestWideningDidNotBreakTheGuards:
    """The two things the widening could have broken, and must not have."""

    @pytest.mark.parametrize("band", ["5-8", "9-12", "13-15"])
    def test_a_child_never_reaches_the_adult_corpus(self, band):
        """`_audience` keys the corpus slice off the AGENT NAME, not the band.

        So granting a child row `qa_agent` or `learning_preview` -- both of which
        resolve to audience "all" -- hands a five-year-old the adult corpus with
        nothing anywhere cross-checking their age.
        """
        persona = "stella" if band in {"5-8", "9-12"} else "orion"
        granted = allowed_agents(persona, band, "prospect", user_id=USER)
        assert "qa_agent" not in granted
        assert "learning_preview" not in granted
        assert "qa_agent_limited" in granted

    def test_nova_stays_a_subset_of_aurora(self):
        """`account._narrowing` is a subset test, and it fails OPEN.

        If `set(_NOVA)` stops being a subset of `set(_AURORA)`, `persona_for`
        silently returns `aurora` for every educator -- handing staff the
        registration walk that collects national IDs. No exception, no log line.
        """
        for band in ("adult",):
            nova = set(allowed_agents("nova", band, "prospect", user_id=USER))
            aurora = set(allowed_agents("aurora", band, "prospect", user_id=USER))
            assert nova <= aurora, sorted(nova - aurora)

    @pytest.mark.parametrize(
        "persona,band",
        [
            ("stella", "5-8"),
            ("orion", "16-18"),
            ("nova", "adult"),
        ],
    )
    def test_only_a_guardian_reaches_registration(self, persona, band):
        granted = allowed_agents(persona, band, "prospect", user_id=USER)
        assert "register_agent" not in granted


class TestASumIsRoutedToTheAgentThatCanDoIt:
    """Widening the rows created a second way to lose the same question.

    With `learn_agent` reachable, the classifier hands it money word problems --
    its card says to take anything about a mechanism, and `apply_stickiness`
    exempts moves INTO teaching from the confidence threshold, so it wins at any
    confidence. It then answers a sum with a curriculum check question.

    Measured on the 22 Aug run, after the access fix and before this one: five
    of five word problems routed to `learn_agent`, none answered. "A shop sells
    notebooks at 3 for EC$12" was met with "You move EC$25 into your account
    instead of spending it this week. What is that?"
    """

    @staticmethod
    def _route(question, allowed):
        import asyncio

        from langchain_core.messages import HumanMessage

        from app.graph.nodes.classify import make_classify

        async def never_called(system, user):  # pragma: no cover
            raise AssertionError("the router was consulted for a plain sum")

        state = {
            "messages": [HumanMessage(content=question)],
            "allowed_agents": allowed,
            "session_id": "s",
            "safety_flags": {},
        }
        return asyncio.run(make_classify(never_called)(state))

    SUMS = [
        "A shop sells notebooks at 3 for EC$12. How much do 7 notebooks cost?",
        "A bus leaves at 07:40 and the trip takes 95 minutes. What time does it arrive?",
        "EC$500 grows by 2% simple interest a year. What is it worth after 3 years?",
    ]

    @pytest.mark.parametrize("question", SUMS)
    def test_a_sum_goes_to_qa_not_the_tutor(self, question):
        update = self._route(
            question, ["qa_agent", "learn_agent", "learning_preview", "escalate_agent"]
        )
        assert update["active_agent"] == "qa_agent"

    @pytest.mark.parametrize("question", SUMS)
    def test_a_child_gets_their_own_band_filtered_qa_agent(self, question):
        update = self._route(
            question, ["qa_agent_limited", "learn_agent", "escalate_agent"]
        )
        assert update["active_agent"] == "qa_agent_limited"

    @pytest.mark.parametrize("question", SUMS)
    def test_a_signed_out_visitor_gets_the_public_one(self, question):
        update = self._route(
            question,
            ["qa_agent_public", "learning_sample", "register_agent_step1"],
        )
        assert update["active_agent"] == "qa_agent_public"

    def test_the_shortcut_never_fires_for_a_teaching_question(self):
        """It must not swallow the turns the access fix exists to enable."""
        import asyncio

        from langchain_core.messages import HumanMessage

        from app.graph.nodes.classify import make_classify

        called = {"yes": False}

        async def invoke(system, user):
            called["yes"] = True
            return '{"agent": "learn_agent", "confidence": 0.9, "reason": "teach"}'

        state = {
            "messages": [HumanMessage(content="Why does starting to save early matter?")],
            "allowed_agents": ["qa_agent", "learn_agent", "escalate_agent"],
            "session_id": "s",
            "safety_flags": {},
        }
        update = asyncio.run(make_classify(invoke)(state))
        assert called["yes"], "the router must still decide ordinary turns"
        assert update["active_agent"] == "learn_agent"


# ── 2. arithmetic was declined for want of a corpus row ──────────────────────


class TestASumTheReaderSetUp:
    """`rsn-01-logic.md`: four of five word problems answered with a decline."""

    #: Verbatim from the transcript, turns 2-5.
    DECLINED = [
        "A shop sells notebooks at 3 for EC$12. How much do 7 notebooks cost?",
        "A bus leaves at 07:40 and the trip takes 95 minutes. What time does it arrive?",
        "EC$500 grows by 2% simple interest a year. What is it worth after 3 years?",
        "Kofi is twice as old as his sister. In 5 years the sum of their ages "
        "will be 34. How old is Kofi now?",
    ]

    @pytest.mark.parametrize("question", DECLINED)
    def test_it_is_recognised_as_a_sum(self, question):
        assert is_self_contained_sum(question, question)

    #: Anything naming the programme keeps every gate it has today.
    PROGRAMME = [
        "Who is eligible to join ASPIRE?",
        "How much does ASPIRE pay?",
        "What documents do I need to register my child?",
        "What is the deadline for the application?",
        "How many branches are there and what are the 2 opening times?",
        # The adversarial one: two figures and an arithmetic cue, but it is a
        # claim about the programme wearing a sum's clothes.
        "Does ASPIRE pay EC$9,999 to each of the 2 children?",
    ]

    @pytest.mark.parametrize("question", PROGRAMME)
    def test_a_programme_question_is_never_treated_as_a_sum(self, question):
        assert not is_self_contained_sum(question, question)

    def test_a_rewrite_cannot_unlock_it(self):
        """`qa_query` is a model call, so it must not be able to grant the pass."""
        reader = "Who is eligible?"
        rewritten = "If 3 cost 12 how much do 7 cost"
        assert not is_self_contained_sum(reader, rewritten)

    def test_a_rewrite_that_drags_the_programme_in_closes_it(self):
        reader = "A shop sells notebooks at 3 for EC$12. How much do 7 cost?"
        rewritten = "What does ASPIRE say notebooks cost?"
        assert not is_self_contained_sum(reader, rewritten)

    def test_a_bare_question_with_no_figures_is_not_a_sum(self):
        for question in ("Is it riskier?", "What is compound interest?", "Why?"):
            assert not is_self_contained_sum(question, question)


class TestTheBypassOnlyFiresWhereTheCorpusIsSilent:
    """The predicate alone is not the gate; retrieval is the other half.

    A question can supply its own figures and still be a programme question --
    "if the minimum deposit is EC$25, what do 4 of them cost?" names no ASPIRE
    vocabulary but its premise IS a corpus row. Bypassing there would throw away
    a citation the reader is entitled to, so the bypass also requires that
    retrieval found nothing above the floor.
    """

    @staticmethod
    def _run(question, answer, chunks):
        import asyncio

        from langchain_core.messages import AIMessage, HumanMessage

        from app.agents.qa import nodes

        state = {
            "messages": [HumanMessage(content=question), AIMessage(content=answer)],
            "retrieved": chunks,
            "locale": "en",
            "session_id": "s",
            "active_agent": "qa_agent",
            "safety_flags": {},
            "qa_query": question,
        }
        command = asyncio.run(nodes.make_ground_check()(state))
        return command.update

    @staticmethod
    def _chunk(kb_id, content, relevance):
        from app.graph.state import KBChunk

        return KBChunk(
            kb_id=kb_id, title="t", content=content, score=relevance, relevance=relevance
        )

    def test_a_sum_with_nothing_retrieved_is_served_uncited(self):
        update = self._run(
            "A shop sells notebooks at 3 for EC$12. How much do 7 notebooks cost?",
            "Each is EC$12 / 3 = EC$4, so 7 cost EC$28.",
            [self._chunk("ASP-006", "ASPIRE was established in September 2024.", 0.21)],
        )
        assert not (update.get("safety_flags") or {}).get("declined")
        assert update["citations"] == []

    def test_a_sum_on_a_retrieved_fact_keeps_its_citation(self):
        update = self._run(
            "if the minimum deposit is EC$25, what do 4 of them cost?",
            "The minimum opening deposit is EC$25 [ASP-003], so four of them is EC$100.",
            [self._chunk("ASP-003", "The minimum opening deposit is EC$25.", 0.88)],
        )
        assert not (update.get("safety_flags") or {}).get("declined")
        assert [c.kb_id for c in update["citations"]] == ["ASP-003"]

    def test_a_programme_question_with_weak_retrieval_still_declines(self):
        """The fabrication guard the whole file exists for, unchanged."""
        update = self._run(
            "How much does ASPIRE pay each child?",
            "ASPIRE pays EC$5,000 to each child.",
            [self._chunk("ASP-006", "ASPIRE was established in September 2024.", 0.21)],
        )
        assert (update.get("safety_flags") or {})["declined"]


# ── 3. the lesson machine graded messages that were not answers ──────────────


class TestTheCheckReleasesTheReader:
    """`rsn-10-11-long-thread.md`, turns 2-4, agent=learning_sample."""

    @pytest.fixture
    def question(self):
        from app.curriculum.schema import CheckQuestion

        return CheckQuestion(
            id="q1",
            prompt={"en": "You move EC$25 into your account. What is that?"},
            options=["Saving", "Spending", "Sharing"],
            answer=0,
        )

    #: Verbatim from the transcript. None of these was an answer; all were graded.
    NOT_ANSWERS = [
        "My sister's name is Renata and she's applying too.",
        "What is a savings account?",
        "What does interest mean?",
        "Why do people invest?",
        "What is a budget?",
        "What is a need versus a want?",
    ]

    @pytest.mark.parametrize("text", NOT_ANSWERS)
    def test_it_is_not_read_as_an_attempt(self, question, text):
        assert not is_an_answer(question, text)

    #: A wrong answer MUST still read as an answer, or the hint ladder -- the
    #: thing that actually teaches -- stops running.
    ATTEMPTS = [
        "Saving",
        "saving",
        "Spending",
        "sharing",
        "1",
        "20",
        "yes",
        "no",
        "i don't know",
        "dunno",
        "because it grows",
        "putting it away for later",
    ]

    @pytest.mark.parametrize("text", ATTEMPTS)
    def test_an_attempt_is_still_graded(self, question, text):
        assert is_an_answer(question, text)

    def test_an_empty_message_is_not_an_attempt(self, question):
        assert not is_an_answer(question, "")
        assert not is_an_answer(question, "   ")


class TestEveryTeachingAgentCanDigress:
    """`safety_in` gated the digression path on `learn_agent` alone.

    So the escape hatch was dead for a guest and for a guardian -- the two
    audiences most likely to wander, and exactly the persona the failing run
    was driving.
    """

    def test_the_flag_covers_every_teaching_agent(self):
        from app.graph.nodes.safety_in import safety_in

        for agent in TEACHING_AGENTS:
            state = {
                "active_agent": agent,
                "messages": [
                    type("M", (), {"type": "human", "content": "who won the cricket?"})()
                ],
            }
            flags = safety_in(state).get("safety_flags") or {}
            assert flags.get("off_topic"), f"{agent} cannot digress"


# ── 4. the internal vocabulary reached the reader ────────────────────────────


class TestTheReaderIsNeverToldAboutTheCorpus:
    """`rsn-08`, `rsn-09`: "The extracts do not state whether...".

    The reader cannot see what the model was given and does not know it exists,
    so a sentence about what it does or does not contain is not an answer.
    """

    @pytest.mark.parametrize(
        "persona", ["stella", "orion", "aurora", "nova", "guest", "not-a-persona"]
    )
    def test_no_role_card_teaches_the_word(self, persona):
        assert "extract" not in qa_agent_role(persona).lower()

    def test_the_fallback_prompt_does_not_teach_it_either(self):
        assert "extract" not in GENERATE_SYSTEM.lower()

    def test_the_global_rules_do_not_teach_it(self):
        flat = " ".join(str(GLOBAL).split()).lower()
        assert "extract" not in flat

    def test_the_rule_forbidding_it_is_still_there(self):
        """Removing the vocabulary must not remove the rule."""
        flat = " ".join(str(GLOBAL).split()).lower()
        assert "answer, do not narrate" in flat
        assert "never name, describe or refer to whatever you were given" in flat

    def test_the_learn_agent_does_not_name_its_rows_either(self):
        from app.agents.learn.render import RAG_TEACH_ROLE

        flat = RAG_TEACH_ROLE.lower()
        assert "knowledge-base row" not in flat
        assert "the rows" not in flat
        assert "extract" not in flat
