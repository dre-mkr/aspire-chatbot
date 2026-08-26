"""ASPIRE Path: it must be true, quiet, and unable to cost anybody an answer."""

from __future__ import annotations

import pytest

from app.graph.path import STAGES, emit, labels, should_show, title


class TestTheStagesAreTheReadersNotTheGraphs:
    @pytest.mark.parametrize("persona", ["stella", "kaleb", "orion", "aurora", "nova", "guest"])
    @pytest.mark.parametrize("locale", ["en", "es", "fr"])
    def test_every_guide_speaks_every_language(self, persona, locale):
        names = labels(persona, locale)
        assert names, f"{persona}/{locale} has no stages"
        assert all(name.strip() for name in names)

    @pytest.mark.parametrize("persona", ["stella", "kaleb", "orion", "aurora", "nova", "guest"])
    def test_no_more_than_four_and_no_fewer_than_three(self, persona):
        """A reader glancing at a strip reads four things and skims six."""
        assert 3 <= len(labels(persona, "en")) <= 4

    def test_no_stage_ever_names_the_machinery(self):
        """A reader is shown the work, never the graph."""
        forbidden = (
            "classif", "retriev", "rerank", "node", "agent", "llm", "model",
            "token", "prompt", "score", "embedding", "vector", "tool call",
        )
        for persona in ("stella", "kaleb", "orion", "aurora", "nova", "guest"):
            for locale in ("en", "es", "fr"):
                for name in labels(persona, locale):
                    lowered = name.lower()
                    for word in forbidden:
                        assert word not in lowered, f"{persona}/{locale}: {name!r}"

    def test_an_unknown_guide_falls_back_rather_than_failing(self):
        assert labels("nobody", "en") == labels("guest", "en")
        assert labels("orion", "de") == labels("orion", "en")

    def test_the_title_is_translated_too(self):
        assert title("es") != title("en")
        assert title("fr") != title("en")


class TestItErrsTowardsSilence:
    def test_a_plain_question_to_a_non_agentic_agent_shows_nothing(self):
        assert should_show({"active_agent": "servicing_agent"}) is False
        assert should_show({"active_agent": "escalate_agent"}) is False

    def test_a_story_shows_nothing(self):
        """One long generation is not a sequence of steps."""
        assert should_show({"active_agent": "qa_agent", "story_topic": "saving"}) is False
        assert should_show({"active_agent": "qa_agent", "story_arc": {"beat": 2}}) is False

    def test_the_multi_step_agents_do_show(self):
        for agent in ("qa_agent", "learn_agent", "register_agent", "register_agent_step1"):
            assert should_show({"active_agent": agent}) is True

    def test_no_agent_at_all_shows_nothing(self):
        assert should_show({}) is False


class TestItCannotCostAnybodyAnAnswer:
    def test_emitting_outside_a_graph_run_is_a_no_op(self):
        """There is no stream writer under test, and that must be fine."""
        emit({"active_agent": "qa_agent", "persona": "orion"}, "aim")

    def test_an_unknown_stage_is_logged_not_raised(self, caplog):
        emit({"active_agent": "qa_agent"}, "not_a_stage")
        assert "Unknown Path stage" in caplog.text

    def test_every_wired_stage_name_is_real(self):
        """A typo in a call site would silently stop that stage appearing."""
        for stage in ("aim", "source", "plan", "interact", "recommend", "enable"):
            assert stage in STAGES
