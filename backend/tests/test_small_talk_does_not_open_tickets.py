"""Saying hello must not open a support ticket."""

from __future__ import annotations

import pytest

from app.agents.qa.nodes import _small_talk_reply


def _state(text: str, locale: str = "en") -> dict:
    from langchain_core.messages import HumanMessage

    return {"messages": [HumanMessage(content=text)], "locale": locale}


def _reply(text: str, locale: str = "en") -> str | None:
    command = _small_talk_reply(_state(text, locale))
    if command is None:
        return None
    return command.update["messages"][0].content


@pytest.mark.parametrize(
    "text",
    [
        "hello", "Hello!", "  hi  ", "hey", "Good morning", "hola", "bonjour",
        "thanks!", "Thank you", "gracias", "merci",
        "ok", "okay", "sure", "got it", "yes", "no",
        "who are you?", "What are you?",
        "can you say that again?", "sorry, can you explain that more simply?",
        "wait, I don't understand", "what did I just ask you?",
        "bye", "goodbye", "au revoir",
    ],
)
def test_ordinary_asides_get_a_conversational_reply(text):
    reply = _reply(text)
    assert reply, f"{text!r} still falls through to an escalation"


@pytest.mark.parametrize("text", ["hello", "thanks!", "ok", "who are you?", "bye"])
def test_the_reply_offers_the_thing_this_service_is_for(text):
    """Every aside except a re-ask should point back at the programme."""
    assert "ASPIRE" in (_reply(text) or "")


@pytest.mark.parametrize(
    "text",
    [
        # The whole reason the matcher is anchored.
        "hello, my dad hits me when he is angry",
        "hi, I don't want to be here anymore",
        "thanks, but my mum says she cannot afford food this week",
        "ok so what is the minimum age to join ASPIRE?",
        "no one at home knows I am using this",
        "yes I want to report something bad",
        "who are you going to tell about what I said?",
        "bye, I am going to hurt myself",
        # Ordinary questions, which must reach retrieval.
        "What is the ASPIRE Programme?",
        "How much does the government contribute per child?",
    ],
)
def test_anything_that_is_not_purely_an_aside_is_left_alone(text):
    assert _small_talk_reply(_state(text)) is None, (
        f"{text!r} was treated as small talk; it must reach the normal path"
    )


def test_the_length_guard_holds_independently_of_the_anchoring():
    """Two guards, so neither has to be perfect on its own."""
    assert _small_talk_reply(_state("hello " * 20)) is None


def test_replies_are_localised():
    for locale, needle in (("es", "¡Hola!"), ("fr", "Bonjour")):
        reply = _reply("hello", locale)
        assert reply and needle in reply, f"{locale} greeting fell back to English"


def test_an_empty_turn_is_not_small_talk():
    assert _small_talk_reply(_state("")) is None


def test_the_reply_is_marked_grounded_so_it_is_not_re_escalated():
    command = _small_talk_reply(_state("hello"))
    assert command is not None
    assert command.update["groundedness"] == 1.0
    assert command.update["citations"] == []
