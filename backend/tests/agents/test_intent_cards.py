"""The two turns that are cards, and the many that only look like them."""

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
        # The one that broke the injection detector for the same reason: a phrase that contains an eligibility word and…
        "How do I act as a good saver?",
        "What is interest?",
        "How does compound interest work?",
    ],
)
def test_lookups_stay_prose(question: str) -> None:
    """A question about ONE rule gets a cited answer, not a form."""
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
    """A directive, and NO message."""
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


# ── registration intent, for the personas that cannot register ─────────────── Reported from a live session on…


from app.graph.access import allowed_agents  # noqa: E402
from app.graph.nodes.intents import wants_registration  # noqa: E402


def _for(persona: str, band: str, message: str, **overrides):
    """State with the REAL access matrix applied, not a hand-written list."""
    state = _state(message, persona=persona, age_band=band, **overrides)
    state["allowed_agents"] = allowed_agents(
        persona, band, "prospect", user_id=state["user_id"]
    )
    return state


@pytest.mark.parametrize(
    "message",
    [
        "i want to register my child",
        "I want to sign up",
        "we would like to apply",
        "register my daughter please",
        "how do i register",
        "start an application",
        "quiero registrar a mi hijo",
    ],
)
def test_these_are_registration_intents(message: str) -> None:
    assert wants_registration(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "who registers a child for aspire",
        "what documents do i need to register",
        "at what age can i register",
        "is registration still open",
        "i want to save for a bike",
    ],
)
def test_questions_about_registering_are_not_intents(message: str) -> None:
    """A question has an answer in the corpus and must keep reaching it."""
    assert wants_registration(message) is False


@pytest.mark.parametrize(
    ("persona", "band"), [("orion", "16-18"), ("stella", "9-12"), ("nova", "adult")]
)
async def test_a_persona_that_cannot_register_is_answered_here(
    persona: str, band: str
) -> None:
    gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: False)

    update = await gate(_for(persona, band, "i want to register my child"))

    assert "parent or guardian" in update["messages"][0].content
    assert update["quick_replies"]
    # No ticket, no retrieval, no model call: the node returned prose.
    assert "ui_directives" not in update


async def test_a_guardian_still_reaches_the_registration_agent() -> None:
    """The case that must be UNTOUCHED."""
    gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: False)

    assert await gate(_for("aurora", "adult", "i want to register my child")) == {}


async def test_a_signed_out_visitor_still_reaches_step_one() -> None:
    """Anonymous holds `register_agent_step1`, which is somewhere to go."""
    gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: False)
    state = _state("i want to register my child")
    state["user_id"] = None
    state["allowed_agents"] = allowed_agents(
        "aurora", "adult", "prospect", user_id=None
    )

    assert await gate(state) == {}


async def test_the_reply_routes_straight_to_the_outbound_gate() -> None:
    """Not to the classifier."""
    from app.graph.main_graph import _after_cards

    gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: False)
    state = _for("orion", "16-18", "i want to register my child")
    update = await gate(state)
    state["messages"] = list(state["messages"]) + update["messages"]
    state["quick_replies"] = update["quick_replies"]

    assert _after_cards(state) == "safety_out"


@pytest.mark.parametrize("locale", ["en", "es", "fr"])
async def test_every_shipped_locale_has_its_own_copy(locale: str) -> None:
    gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: False)
    message = {"en": "i want to register my child",
               "es": "quiero registrar a mi hijo",
               "fr": "je veux inscrire mon enfant"}[locale]

    update = await gate(_for("orion", "16-18", message, locale=locale))

    assert update["messages"][0].content
    assert len(update["quick_replies"]) == 2


# ── the fallback is addressed to whoever is actually reading it ────────────── Reported live.


from app.graph.nodes.cards import _REGISTRATION_HELP  # noqa: E402


@pytest.mark.parametrize("audience", sorted(_REGISTRATION_HELP))
@pytest.mark.parametrize("locale", ["en", "es", "fr"])
def test_no_copy_tells_the_reader_to_pick_a_persona(audience: str, locale: str) -> None:
    """The bug that made this a loop rather than a dead end."""
    text = _REGISTRATION_HELP[audience][locale].lower()

    for persona in ("aurora", "stella", "orion", "nova"):
        assert persona not in text, (
            f"the {audience!r} copy in {locale!r} names {persona!r}; the reader "
            f"cannot select it, so this is advice that cannot be followed"
        )


async def test_a_teenager_applying_for_a_child_is_not_told_to_ask_a_parent() -> None:
    """The reported turn, verbatim."""
    gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: False)

    update = await gate(_for("orion", "16-18", "i want to register my daughter"))
    text = update["messages"][0].content

    assert "ask yours" not in text.lower()
    assert "guardian account" in text.lower()


async def test_a_child_is_still_told_to_ask_a_grown_up() -> None:
    """The half of the old behaviour that was right, and must survive."""
    gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: False)

    update = await gate(_for("stella", "9-12", "i want to register my child"))

    assert "ask yours" in update["messages"][0].content.lower()


async def test_a_teacher_is_not_told_to_fetch_their_parent() -> None:
    gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: False)

    update = await gate(_for("nova", "adult", "i want to register my child"))
    text = update["messages"][0].content.lower()

    assert "ask yours" not in text
    assert "school" in text


# ── the account card ─────────────────────────────────────────────────────────


async def test_the_offered_chip_actually_opens_the_wizard() -> None:
    """The chip the fallback offers must be a route, not a phrase."""
    gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: False)
    state = _for("orion", "16-18", "i want to register my daughter")
    chip = (await gate(state))["quick_replies"][0]

    update = await gate(_for("orion", "16-18", chip))

    assert update["ui_directives"] == [{"t": "signup", "role": "guardian"}]


async def test_a_child_asking_for_an_account_gets_no_guardian_branch() -> None:
    """A suggested role is a shape of account. Never suggest one they cannot hold."""
    gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: False)

    update = await gate(_for("stella", "9-12", "i want to create an account"))

    assert update["ui_directives"] == [{"t": "signup", "role": None}]


async def test_a_guardian_asking_for_an_account_is_still_answered() -> None:
    """Unlike the registration fallback, this one is not conditional on being unable to register."""
    gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: False)

    update = await gate(_for("aurora", "adult", "i want to create an account"))

    assert update["ui_directives"] == [{"t": "signup", "role": "guardian"}]


async def test_registering_a_child_is_not_mistaken_for_making_an_account() -> None:
    """The two matchers overlap in vocabulary and must not overlap in effect."""
    gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: False)

    assert await gate(_for("aurora", "adult", "i want to register my daughter")) == {}


async def test_the_signup_card_ends_the_turn_at_the_outbound_gate() -> None:
    """A card turn must not fall through to the classifier."""
    from app.graph.main_graph import _after_cards

    gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: False)
    state = _for("orion", "16-18", "i want to create an account")
    update = await gate(state)
    state["messages"] = list(state["messages"]) + update["messages"]
    state["safety_flags"] = update["safety_flags"]

    assert _after_cards(state) == "safety_out"
