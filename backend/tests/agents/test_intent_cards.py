"""The two turns that are cards, and the many that only look like them.

The interesting half of this file is `test_lookups_stay_prose`. A matcher that
opens the eligibility card on "what is the minimum age?" interrupts a one-line
question with a six-step form, and it is the failure that is easy to ship
because every phrase in it genuinely is about eligibility.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.graph.nodes.cards import make_intent_gate
from app.graph.nodes.intents import named_game, wants_eligibility, wants_game
from app.graph.state import initial_state

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _state(message: str, **overrides):
    state = initial_state(
        session_id="s-1",
        user_id="u-1",
        device_id="d-1",
        persona=overrides.pop("persona", "aurora"),
        age_band=overrides.pop("age_band", "13-15"),
        account_status=overrides.pop("account_status", "active"),
        locale=overrides.pop("locale", "en"),
    )
    state["messages"] = [HumanMessage(content=message)]
    state.update(overrides)
    return state


# ── the matcher ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        "Am I eligible?",
        "Can I join ASPIRE?",
        "can my daughter sign up",
        "Do I qualify?",
        "Who is eligible for ASPIRE?",
        "who can join",
        "Am I too old?",
        "How do I apply?",
        "What documents do I need?",
        "¿Puedo inscribirme?",
        "¿Quién puede participar?",
        "¿Soy demasiado mayor?",
        "Qui peut participer ?",
        "Puis-je m'inscrire ?",
        "Suis-je trop âgé ?",
        # No apostrophe at all, as a phone keyboard produces it.
        "puis-je minscrire",
    ],
)
def test_personal_eligibility_questions_open_the_card(question: str) -> None:
    assert wants_eligibility(question)


@pytest.mark.parametrize(
    "question",
    [
        "What is the minimum age?",
        "What is the maximum age for ASPIRE?",
        "What is the age limit?",
        "Does Nevis count?",
        "how old do you have to be",
        "Is there an income limit?",
        # The one that broke the injection detector for the same reason: a
        # phrase that contains an eligibility word and asks nothing about
        # eligibility.
        "How do I act as a good saver?",
        "What is interest?",
        "How does compound interest work?",
    ],
)
def test_lookups_stay_prose(question: str) -> None:
    """A question about ONE rule gets a cited answer, not a form.

    Both halves matter. The first three would match the eligibility patterns
    outright if `_LOOKUP` did not win ties.
    """
    assert not wants_eligibility(question)


@pytest.mark.parametrize(
    "message",
    [
        "can we play a game",
        "let us play",
        "let's play a game",
        "I want to play",
        "play true or false",
        "word scramble please",
        "what games are there",
        "quiero jugar",
        "je veux jouer",
    ],
)
def test_asking_to_play_is_recognised(message: str) -> None:
    assert wants_game(message)


def test_a_game_is_never_started_unprompted() -> None:
    """Nothing that is not a request to play may start one."""
    for message in (
        "how do interest rates work",
        "my brother plays football at school",
        "what is a savings plan",
    ):
        assert not wants_game(message)


def test_naming_a_game_is_optional() -> None:
    assert named_game("play true or false") == "true_false"
    assert named_game("word scramble please") == "scramble"
    assert named_game("can we play a game") is None


# ── the node ─────────────────────────────────────────────────────────────────


async def test_the_eligibility_card_is_the_whole_turn() -> None:
    """A directive, and NO message.

    This is the property v1 needed `TurnBuffer` to hold: the model wrote prose
    alongside the card and it had to be discarded before it crossed the wire.
    Here there is nothing to discard, because no model was asked.
    """
    started: list[tuple[str, str]] = []
    gate = make_intent_gate(
        start_check=lambda session, locale: started.append((session, locale)),
        check_running=lambda session: False,
        eligibility_on=lambda: True,
        games_on=lambda: False,
    )

    update = await gate(_state("Can I join?", locale="fr"))

    assert started == [("s-1", "fr")]
    assert update["safety_flags"]["card"] == "eligibility"
    assert "messages" not in update
    directive = update["ui_directives"][0]
    assert directive["t"] == "eligibility"
    assert directive["language"] == "fr"
    # No rule, no verdict, no criterion. The card holds those.
    assert set(directive) == {"t", "check", "language"}


async def test_a_check_already_open_is_left_alone() -> None:
    """Somebody four questions in has not asked to start again."""
    gate = make_intent_gate(
        start_check=lambda session, locale: pytest.fail("restarted an open check"),
        check_running=lambda session: True,
        eligibility_on=lambda: True,
        games_on=lambda: False,
    )
    assert await gate(_state("so can I join?")) == {}


async def test_a_named_game_becomes_a_directive() -> None:
    gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: True)

    update = await gate(_state("can we play true or false", age_band="5-8"))

    directive = update["ui_directives"][0]
    assert directive["t"] == "game"
    assert directive["game"] == "true_false"
    # No puzzle and no answer may ride on a game directive.
    assert set(directive) == {"t", "game", "concept", "difficulty"}
    assert "messages" not in update


async def test_asking_to_play_without_choosing_asks_which() -> None:
    """It asks. It does not pick one on the child's behalf."""
    gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: True)

    update = await gate(_state("can we play a game", age_band="9-12"))

    assert isinstance(update["messages"][0], AIMessage)
    assert set(update["quick_replies"]) == {"True or false", "Word scramble"}
    assert "ui_directives" not in update


async def test_a_band_that_may_not_play_a_named_game_is_offered_what_it_can() -> None:
    """A five-year-old asking for the spelling game is not told no and dropped."""
    gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: True)

    update = await gate(_state("word scramble please", age_band="5-8"))

    assert update["quick_replies"] == ["True or false"]
    assert "ui_directives" not in update


async def test_a_disabled_module_never_opens_its_card() -> None:
    gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: False)
    assert await gate(_state("Am I eligible?")) == {}
    assert await gate(_state("let's play a game")) == {}
