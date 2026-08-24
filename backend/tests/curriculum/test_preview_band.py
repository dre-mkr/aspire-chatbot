"""A parent looking at her child's lesson is asking for a band that is not hers."""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from app.agents.learn.state import band_of
from app.agents.learn.teach import persona_of
from app.graph.nodes.intents import band_requested

SCORING = "learn_agent"
WATCHING = ("learning_preview", "learning_sample")


class TestReadingTheRequest:
    @pytest.mark.parametrize(
        ("said", "expected"),
        [
            ("Give me a demonstration of a lesson for a 9 year old", "9-12"),
            ("Can I see the lesson my 7 year old would get", "5-8"),
            ("my daughter is 14", "13-15"),
            ("a lesson for my Form 2 class", "13-15"),
            ("what do you have for Form 5", "16-18"),
            ("something for the Infant Department", "5-8"),
            ("for Grade 4", "9-12"),
            ("upper secondary material", "16-18"),
        ],
    )
    def test_a_band_named_for_somebody_else(self, said, expected):
        assert band_requested(said) == expected

    @pytest.mark.parametrize(
        "said",
        ["show me what you teach", "provide me a tutorial", "I have 2 children",
         "EC$25 a week", "what is saving"],
    )
    def test_and_nothing_when_none_is_named(self, said):
        assert band_requested(said) is None


class TestAPreviewIsAWindowNotAWayIn:
    """The safety property, and it is structural rather than a written rule."""

    @pytest.mark.parametrize("agent", WATCHING)
    def test_a_watching_agent_renders_the_band_asked_for(self, agent):
        assert band_of({"age_band": "adult", "preview_band": "9-12", "active_agent": agent}) == "9-12"

    def test_the_tutor_ignores_it_entirely(self):
        """Nothing a real learner types can move their own band.

        `learn_agent` never consults `preview_band`, so the caps, the vocabulary
        ladder and the link strip all stay where the session put them.
        """
        state = {"age_band": "5-8", "preview_band": "adult", "active_agent": SCORING}
        assert band_of(state) == "5-8"

    def test_a_child_cannot_type_their_way_older(self):
        for asked in ("9-12", "13-15", "16-18", "adult"):
            assert band_of({"age_band": "5-8", "preview_band": asked, "active_agent": SCORING}) == "5-8"

    def test_without_a_preview_nothing_changes(self):
        for agent in (*WATCHING, SCORING):
            assert band_of({"age_band": "adult", "active_agent": agent}) == "adult"


class TestAPreviewShowsTheChildsOwnVoice:
    """She wants to see what HE sees, not her lesson re-pitched."""

    ADULT = {"persona": "aurora", "age_band": "adult", "active_agent": "learning_sample"}

    @pytest.mark.parametrize(
        ("preview", "voice"),
        [("5-8", "stella"), ("9-12", "kaleb"), ("13-15", "orion"), ("16-18", "orion")],
    )
    def test_the_voice_follows_the_band_previewed(self, preview, voice):
        assert persona_of({**self.ADULT, "preview_band": preview}) == voice

    def test_her_own_band_stays_her_own_voice(self):
        assert persona_of({**self.ADULT, "preview_band": "adult"}) == "aurora"
        assert persona_of(self.ADULT) == "aurora"

    def test_the_tutor_still_speaks_as_the_reader(self):
        state = {**self.ADULT, "preview_band": "5-8", "active_agent": SCORING}
        assert persona_of(state) == "aurora"


@pytest.mark.asyncio
class TestEndToEnd:
    @staticmethod
    async def _preview(preview_band):
        from app.agents.learn.graph import build_learn_graph
        from app.curriculum.schema import load_all

        graph = build_learn_graph(curriculum=load_all(), store=None)
        out = await graph.ainvoke(
            {
                "messages": [HumanMessage(content="show me the lesson")],
                "persona": "aurora", "age_band": "adult", "preview_band": preview_band,
                "locale": "en", "active_agent": "learning_sample",
                "session_id": "s", "user_id": None,
                "learning": {"lesson_id": "l05_a_simple_plan", "concept_id": "budget",
                             "phase": "teaching"},
                "retrieved": [],
            }
        )
        said = [m for m in out.get("messages", []) if getattr(m, "type", None) == "ai"]
        return str(said[0].content), str(said[-1].content)

    async def test_the_teaching_and_the_question_move_together(self):
        """Before this, only the reader's band existed, so neither moved."""
        teaching, question = {}, {}
        for band in ("5-8", "9-12", "13-15"):
            teaching[band], question[band] = await self._preview(band)

        assert len(set(teaching.values())) == 3, "the teaching did not follow the band"
        assert len(set(question.values())) == 3, "the question did not follow the band"
        assert teaching["5-8"].startswith("A plan says where your money goes")

    async def test_her_own_lesson_is_still_hers(self):
        teaching, _ = await self._preview(None)
        assert teaching.startswith("A plan is one decision made in the calm")
