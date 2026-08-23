"""A greeting is answered before the cache is consulted.

ORDER IS THE WHOLE POINT. The response cache is keyed on the question, so a turn
that was misrouted once is served from the shelf for ever after -- and a
greeting is the single most likely thing to be asked twice.

Measured on aspire.eccugenai.app, FRESH sessions, 23 August 2026:

    "hi"      -> "And how are you related to the child?"        78ms   cache
    "thanks"  -> "Pick the closest one -- mother, father, ..."  78ms   cache
    "ok"      -> the same                                      128ms   cache
    "bye"     -> the same                                       73ms   cache

The small-talk short-circuit exists precisely to answer "hi". It lived inside
the QA agent, three layers below the cache, so it never ran once: the cache
answered first, every time, with a question from a registration form. The very
first thing a new visitor says was answered by asking them how they are related
to a child they had not mentioned.
"""

from __future__ import annotations

import pytest

from app.agents.qa.nodes import small_talk_answer, small_talk_kind


class TestTheClosedClass:
    @pytest.mark.parametrize(
        "message,kind",
        [
            ("hi", "greeting"),
            ("hey!", "greeting"),
            ("hello", "greeting"),
            ("hola", "greeting"),
            ("bonjour", "greeting"),
            ("thanks", "thanks"),
            ("thank you", "thanks"),
            ("ok", "ack"),
            ("got it", "ack"),
            ("who are you", "identity"),
            ("say that again", "repeat"),
            ("bye", "bye"),
        ],
    )
    def test_it_is_recognised_without_a_graph_state(self, message: str, kind: str):
        assert small_talk_kind(message) == kind

    @pytest.mark.parametrize(
        "message",
        [
            "What is the minimum savings rate?",
            "How do I register my child?",
            "hi, how much does ASPIRE give me?",
            "Why does saving early matter?",
            "",
            "   ",
        ],
    )
    def test_a_real_question_falls_through_to_the_full_path(self, message: str):
        assert small_talk_kind(message) is None
        assert (
            small_talk_answer(message, locale="en", persona="kaleb", age_band="9-12")
            is None
        )

    def test_an_over_long_message_is_not_small_talk(self):
        """The length guard sits on top of the anchoring."""
        assert small_talk_kind("ok " * 40) is None


class TestNoneOfThemCanBeARegistrationQuestion:
    """The property, stated directly: whatever put those entries on the shelf,
    a greeting can no longer reach them, because it never reaches the shelf.
    """

    POISON = (
        "And how are you related to the child?",
        "Pick the closest one",
        "mother, father, grandmother",
    )

    @pytest.mark.parametrize("message", ["hi", "thanks", "ok", "bye", "who are you"])
    @pytest.mark.parametrize("locale", ["en", "es", "fr"])
    def test_the_answer_is_conversational(self, message: str, locale: str):
        reply = small_talk_answer(
            message, locale=locale, persona="stella", age_band="5-8"
        )
        assert reply, f"{message!r} produced nothing"
        for fragment in self.POISON:
            assert fragment.lower() not in reply.lower()


class TestItStillSpeaksAsTheRightGuide:
    def test_identity_names_the_persona(self):
        reply = small_talk_answer(
            "who are you", locale="en", persona="aurora", age_band="adult"
        )
        assert "Imani" in reply

    def test_and_in_the_readers_language(self):
        reply = small_talk_answer(
            "who are you", locale="fr", persona="nova", age_band="adult"
        )
        assert "Azuri" in reply and "guide" in reply.lower()

    def test_guest_stays_generic(self):
        reply = small_talk_answer(
            "who are you", locale="en", persona="guest", age_band="13-15"
        )
        assert "ASPIRE assistant" in reply


class TestTheStreamCallsItBeforeTheCache:
    """Structural: the ordering is the fix, so the ordering is the test."""

    def test_layer_zero_precedes_layer_one_in_the_source(self):
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1] / "app" / "api" / "stream.py"
        ).read_text(encoding="utf-8")
        small_talk_at = source.index("small_talk_answer(")
        cache_at = source.index("cached_answer(")
        assert small_talk_at < cache_at, (
            "the cache is consulted before small talk again; a poisoned entry "
            "for 'hi' would be served in preference to the greeting"
        )
