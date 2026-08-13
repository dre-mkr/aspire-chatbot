"""Which turns may be replayed to somebody else, and the one that may not."""

from __future__ import annotations

import pytest

from app.turn import LESSON_AGENTS, TurnRecord, cacheable


def record(**overrides) -> TurnRecord:
    fields = {
        "thread_id": "t1",
        "question": "teach me about saving",
        "reply": "Saving is keeping some of it for later.",
        "language": "en",
        "persona": "stella",
        "account_status": "beneficiary",
        "age_band": "9-12",
    }
    fields.update(overrides)
    return TurnRecord(**fields)


class TestALessonIsNeverCached:
    @pytest.mark.parametrize("agent", sorted(LESSON_AGENTS))
    def test_no_learning_agent_turn_is_cacheable(self, agent):
        assert cacheable(record(agent=agent)) is False

    def test_chips_do_not_make_a_lesson_cacheable(self):
        """The exact shape that slipped through."""
        assert (
            cacheable(
                record(
                    agent="learn_agent",
                    directives=[{"t": "quick_replies", "d": ["Got it"]}],
                )
            )
            is False
        )

    def test_the_three_names_match_the_rest_of_the_system(self):
        """One subgraph, three registrations, four places that name the set."""
        from app.graph.nodes.safety_out import LEARNING_AGENTS
        from app.graph.stream_interceptor import WIDGET_AGENTS

        assert LESSON_AGENTS == LEARNING_AGENTS == WIDGET_AGENTS


class TestTheOtherExclusions:
    def test_a_card_turn_is_not_cacheable(self):
        assert cacheable(record(card="game", reply="")) is False

    def test_an_empty_reply_is_not_cacheable(self):
        assert cacheable(record(reply="   ")) is False

    def test_a_widget_directive_is_not_cacheable(self):
        assert cacheable(record(agent="qa_agent", directives=[{"t": "widget"}])) is False


class TestWhatStillIs:
    def test_a_plain_qa_answer_is_cacheable(self):
        """The case the cache exists for, and it must keep working."""
        assert cacheable(record(agent="qa_agent")) is True

    def test_citations_and_chips_are_still_allowed(self):
        assert (
            cacheable(
                record(
                    agent="qa_agent_public",
                    directives=[{"t": "citations"}, {"t": "quick_replies"}],
                )
            )
            is True
        )

    def test_an_unknown_agent_is_cacheable(self):
        """Permissive by default: the exclusion list is updated when an agent gains state."""
        assert cacheable(record(agent="servicing_agent")) is True
