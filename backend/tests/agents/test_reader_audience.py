"""Whose questions belong in front of this reader."""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from app.agents.qa.nodes import (
    _for_this_reader,
    follow_up_chips,
    reader_audience,
    stated_role,
)


class _Chunk:
    def __init__(self, kb_id, question, audience):
        self.kb_id = kb_id
        self.title = question
        self.metadata = {"question": question, "audience": audience}
        self.content = question


def _state(persona="guest", *said):
    return {"persona": persona, "messages": [HumanMessage(content=m) for m in said]}


class TestThePersonaIsOnlyAStartingPoint:
    @pytest.mark.parametrize(
        ("persona", "expected"),
        [("nova", "teacher"), ("aurora", "parent"), ("kaleb", "student"),
         ("stella", "child"), ("orion", "student"), ("guest", "general")],
    )
    def test_each_persona_has_a_default(self, persona, expected):
        assert reader_audience(_state(persona, "hello")) == expected

    def test_saying_it_beats_picking_it(self):
        assert reader_audience(_state("aurora", "As a teacher I need materials")) == "teacher"
        assert reader_audience(_state("nova", "I have 2 children")) == "parent"


class TestTheSameAdultIsBoth:
    """A teacher on Monday and a parent on Tuesday, and both in one conversation."""

    def test_a_teacher_asking_about_their_own_child(self):
        state = _state(
            "nova",
            "As a teacher I need lesson materials",
            "But for my own child, what should I do?",
        )
        assert reader_audience(state) == "parent"

    def test_a_parent_who_turns_out_to_teach(self):
        state = _state(
            "aurora",
            "I have 2 children",
            "Actually as a teacher, my class needs materials too",
        )
        assert reader_audience(state) == "teacher"

    def test_the_latest_statement_wins(self):
        state = _state("guest", "as a teacher", "as a parent", "as a teacher")
        assert stated_role(state) == "teacher"

    @pytest.mark.parametrize(
        ("said", "expected"),
        [
            ("Tengo 2 hijos", "parent"),
            ("Como docente quiero preparar una lección", "teacher"),
            ("J'ai deux enfants", "parent"),
            ("En tant qu'enseignant, mes élèves", "teacher"),
        ],
    )
    def test_in_every_language(self, said, expected):
        assert reader_audience(_state("guest", said)) == expected


class TestChipsSortByAudience:
    """The failure: an educator offered "Is a phone a need or a want?"."""

    CHUNKS = [
        _Chunk("A", "Is a phone a need or a want?", "child"),
        _Chunk("B", "How should affirmations be used in a session?", "teacher"),
        _Chunk("C", "How do I talk to my child about money?", "parent"),
    ]

    def test_an_educator_gets_the_educators_question_first(self):
        chips = follow_up_chips(_state("nova", "how do I prepare a lesson"), self.CHUNKS, set())
        assert chips[0] == "How should affirmations be used in a session?"

    def test_a_guardian_gets_the_guardians(self):
        chips = follow_up_chips(_state("aurora", "what should I know"), self.CHUNKS, set())
        assert chips[0] == "How do I talk to my child about money?"

    def test_a_learner_gets_the_learners(self):
        chips = follow_up_chips(_state("kaleb", "tell me about money"), self.CHUNKS, set())
        assert chips[0] == "Is a phone a need or a want?"

    def test_nothing_is_lost_only_reordered(self):
        """A thin slice must not leave a reader with no follow-ups at all."""
        chips = follow_up_chips(_state("nova", "hello"), self.CHUNKS, set())
        assert set(chips) == {chunk.title for chunk in self.CHUNKS}


class TestTheFamilies:
    def test_general_belongs_to_everyone(self):
        for audience in ("teacher", "parent", "student", "child"):
            assert _for_this_reader(_Chunk("x", "q", "general"), audience)

    def test_an_untagged_row_belongs_to_everyone(self):
        assert _for_this_reader(_Chunk("x", "q", None), "teacher")

    def test_child_and_student_are_one_reader_at_two_ages(self):
        assert _for_this_reader(_Chunk("x", "q", "child"), "student")
        assert _for_this_reader(_Chunk("x", "q", "student"), "child")

    def test_an_adult_row_is_not_a_learners(self):
        assert not _for_this_reader(_Chunk("x", "q", "teacher"), "child")
        assert not _for_this_reader(_Chunk("x", "q", "parent"), "student")


@pytest.mark.asyncio
class TestTheSourcePanelFollowsTheReaderToo:
    """"Where this came from", in the language they are reading."""

    @staticmethod
    def _citation(**over):
        from app.graph.state import Citation

        base = dict(
            kb_id="ASP-001",
            title="How ASPIRE works",
            question="How do I open a bank account?",
            snippet="Every participant receives a savings account.",
            source_url="https://aspire.gov.kn/faq",
            site="ASPIRE",
            page="FAQ",
            domain="aspire.gov.kn",
            updated="2026-01-01",
        )
        base.update(over)
        return Citation(**base)

    async def test_english_is_left_alone(self):
        from app.agents.qa.nodes import localise_citations

        one = self._citation()
        assert await localise_citations([one], "en") == [one]

    async def test_the_prose_is_translated(self, monkeypatch):
        from app.agents.qa import nodes

        async def fake(lines, language):
            return [f"[{language}] {line}" for line in lines]

        monkeypatch.setattr("app.agent.localise_lines", fake)
        out = await nodes.localise_citations([self._citation()], "es")
        assert out[0].title == "[es] How ASPIRE works"
        assert out[0].question == "[es] How do I open a bank account?"
        assert out[0].snippet == "[es] Every participant receives a savings account."

    async def test_the_provenance_is_not(self, monkeypatch):
        """A site's name, its host and its URL are what they are."""
        from app.agents.qa import nodes

        async def fake(lines, language):
            return [f"[{language}] {line}" for line in lines]

        monkeypatch.setattr("app.agent.localise_lines", fake)
        out = await nodes.localise_citations([self._citation()], "fr")
        assert out[0].source_url == "https://aspire.gov.kn/faq"
        assert out[0].site == "ASPIRE"
        assert out[0].domain == "aspire.gov.kn"
        assert out[0].page == "FAQ"
        assert out[0].updated == "2026-01-01"

    async def test_a_failure_leaves_the_panel_standing(self, monkeypatch):
        from app.agents.qa import nodes

        async def boom(lines, language):
            raise RuntimeError("no model today")

        monkeypatch.setattr("app.agent.localise_lines", boom)
        one = self._citation()
        assert await nodes.localise_citations([one], "es") == [one]


class TestTheRouterReadsTheRole:
    """A field on the call that already happens, not a second call or a pattern list."""

    def test_the_router_wins_over_the_patterns(self):
        from app.agents.qa.nodes import speaking_as

        state = {
            "messages": [HumanMessage(content="my Form 2s need an activity")],
            "safety_flags": {"route": {"role": "parent"}},
        }
        assert speaking_as(state) == "parent", "this turn's message is the current truth"

    def test_the_patterns_carry_a_turn_the_router_never_saw(self):
        """Single-option turns, widget continuations and no-API-key all skip it."""
        from app.agents.qa.nodes import speaking_as

        state = {
            "messages": [
                HumanMessage(content="As a teacher I need materials"),
                HumanMessage(content="and what comes next"),
            ],
            "safety_flags": {},
        }
        assert speaking_as(state) == "teacher"

    def test_an_invented_role_is_dropped_not_trusted(self):
        from app.graph.nodes.classify import _parse

        assert _parse('{"agent":"qa_agent","confidence":0.9,"role":"headmaster"}')[3] == ""

    def test_the_router_returns_the_closed_set(self):
        from app.graph.nodes.classify import ROLES

        assert ROLES == {"teacher", "educator", "parent", "learner"}


class TestTheTwoReadersInsideAzuri:
    """One persona key, two jobs, and an answer for one lands wrong on the other."""

    @staticmethod
    def _said(text, **over):
        base = {"messages": [HumanMessage(content=text)]}
        base.update(over)
        return base

    @pytest.mark.parametrize(
        ("said", "expected"),
        [
            ("my Form 2s need an activity", "teacher"),
            ("my Grade 4s", "teacher"),
            ("do you have a plan for period 3", None),
            ("our school is considering this", "educator"),
            ("what does it cost us to roll it out", "educator"),
            ("as the principal, my staff asked", "educator"),
            ("nuestra escuela quiere adoptarlo", "educator"),
            ("notre école va l'adopter", "educator"),
        ],
    )
    def test_the_spines_own_signals(self, said, expected):
        from app.agents.qa.nodes import stated_role

        assert stated_role(self._said(said)) == expected

    def test_teacher_wins_when_the_signals_are_mixed(self):
        """The spine: answer the Teacher first and offer the Educator half."""
        from app.agents.qa.nodes import stated_role

        assert stated_role(self._said("My Form 2s, and our school policy")) == "teacher"

    def test_both_read_the_same_rows(self):
        """The corpus has no administrator tag; the split is register, not access."""
        from app.agents.qa.nodes import reader_audience

        for role in ("teacher", "educator"):
            state = self._said("x", safety_flags={"route": {"role": role}})
            assert reader_audience(state) == "teacher"

    def test_but_they_are_told_different_things(self):
        from app.agents.qa.nodes import _role_instruction

        teacher = _role_instruction(self._said("my Form 2s need an activity"))
        educator = _role_instruction(self._said("our school is adopting this"))
        assert "DELIVERY" in teacher
        assert "STEWARDSHIP" in educator
        assert teacher != educator

    def test_no_role_stated_shapes_nothing(self):
        from app.agents.qa.nodes import _role_instruction

        assert _role_instruction(self._said("what is compound interest")) is None


class TestTheJourneyStage:
    """`account_status` was signed into the token and then thrown away."""

    @pytest.mark.parametrize(
        "status", ["prospect", "applicant", "beneficiary", "guardian"]
    )
    def test_every_status_shapes_the_answer(self, status):
        from app.agents.qa.nodes import _stage_instruction

        assert _stage_instruction({"account_status": status})

    def test_an_applicant_is_not_told_to_apply(self):
        from app.agents.qa.nodes import _stage_instruction

        assert "Do not tell them to apply" in _stage_instruction(
            {"account_status": "applicant"}
        )

    def test_no_status_shapes_nothing(self):
        from app.agents.qa.nodes import _stage_instruction

        assert _stage_instruction({}) is None

    def test_role_and_stage_stack(self):
        from app.agents.qa.nodes import _shaping_instructions

        out = _shaping_instructions(
            {
                "messages": [HumanMessage(content="our school is considering this")],
                "account_status": "prospect",
            }
        )
        assert "STEWARDSHIP" in out
        assert "has not applied" in out
