"""The rolling window, the summary, and the token accounting.

The point of the memory change is that the prompt stops growing with the
conversation. That is a measurable claim, so it is measured rather than asserted
in a comment.
"""

from dataclasses import dataclass

import pytest

from app.db.repository import ConversationContext
from app.memory import SUMMARY_PREFACE, build_prompt, count_tokens


@dataclass
class _Turn:
    """Enough of a stored Message for `build_prompt` to consume."""

    role: str
    content: str
    seq: int = 0


def turns(n: int, *, words: int = 40) -> list[_Turn]:
    body = " ".join(["saving"] * words)
    return [
        _Turn(role="user" if i % 2 == 0 else "assistant", content=f"{body} {i}", seq=i + 1)
        for i in range(n)
    ]


class TestWindow:
    def test_only_the_window_is_sent(self):
        context = ConversationContext(recent=turns(6), older_turn_count=40)
        prepared = build_prompt("and now?", context)

        # Six messages plus the new question. The forty older ones are absent.
        assert len(prepared.messages) == 7
        assert prepared.messages[-1].content == "and now?"
        assert prepared.windowed_turns == 6
        assert prepared.summarized_turns == 40

    def test_summary_is_prepended_and_framed_as_a_record(self):
        context = ConversationContext(
            summary="The user is 12 and saving for a bicycle.", recent=turns(2)
        )
        prepared = build_prompt("how much more?", context)

        first = prepared.messages[0]
        assert first.type == "system"
        assert "bicycle" in first.content
        # Framed as reference material, so a summary that happens to contain an
        # instruction is far less likely to be obeyed as one.
        assert first.content.startswith(SUMMARY_PREFACE)

    def test_no_summary_means_no_extra_message(self):
        prepared = build_prompt("hello", ConversationContext(recent=turns(2)))
        assert all(m.type != "system" for m in prepared.messages)

    def test_an_empty_context_is_just_the_question(self):
        prepared = build_prompt("hello", ConversationContext())
        assert len(prepared.messages) == 1
        assert prepared.messages[0].content == "hello"


class TestPromptCost:
    def test_prompt_size_stops_growing_with_the_conversation(self):
        """The whole point of the change, stated as an assertion."""
        short = build_prompt("q", ConversationContext(recent=turns(6)))
        long_thread = build_prompt(
            "q", ConversationContext(recent=turns(6), older_turn_count=200)
        )
        # A 200-message thread costs the same as a 6-message one.
        assert short.tokens == long_thread.tokens

    def test_measured_saving_against_full_history(self):
        everything = [(t.role, t.content) for t in turns(60)]
        window = ConversationContext(recent=turns(60)[-6:], older_turn_count=54)

        prepared = build_prompt("q", window, full_history=everything)

        assert prepared.tokens < prepared.tokens_if_full_history
        # At sixty messages with a window of six the drop should be substantial,
        # not marginal -- if it is not, the change is not worth making.
        assert prepared.saved_percent > 80

    def test_saving_is_zero_when_nothing_was_dropped(self):
        context = ConversationContext(recent=turns(4))
        history = [(t.role, t.content) for t in turns(4)]
        prepared = build_prompt("q", context, full_history=history)
        assert prepared.saved == 0
        assert prepared.saved_percent == 0.0

    def test_token_count_is_not_a_character_count(self):
        # Guards the accounting itself: a broken encoder returning len() would
        # make every before/after number meaningless.
        text = "the quick brown fox jumps over the lazy dog"
        assert 0 < count_tokens(text) < len(text)


@pytest.mark.parametrize("role,expected", [("assistant", "ai"), ("user", "human")])
def test_roles_round_trip_to_message_types(role, expected):
    context = ConversationContext(recent=[_Turn(role=role, content="x", seq=1)])
    assert build_prompt("q", context).messages[0].type == expected


def test_the_window_is_off_by_default():
    """Enabling it changes what the assistant recalls, so it is opt-in."""
    from app.config import Settings

    assert Settings().memory_window_enabled is False
