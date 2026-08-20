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
        "Am I too old?",
        "¿Puedo inscribirme?",
        "¿Soy demasiado mayor?",
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
        # Questions about the RULES and the PROCESS. These used to open the
        # card -- a form carrying no prose -- so asking one got you a form and
        # no answer. `evals/golden.yaml` expected them answered all along
        # (en-02 -> ASP-026, en-03 -> ASP-045), and the latency probe measured
        # five of thirty golden questions producing no visible token because of
        # it: en-02, en-03, es-02, es-03, fr-03.
        "Who is eligible for ASPIRE?",
        "who can join",
        "How do I apply?",
        "What documents do I need?",
        "What documents do I need to register my child?",
        "What do I need to apply?",
        "¿Quién puede participar?",
        "¿Cómo me inscribo?",
        "Qui peut participer ?",
        "Comment s'inscrire ?",
        "What is the minimum age?",
        "What is the maximum age for ASPIRE?",
        "What is the age limit?",
        "Does Nevis count?",
        "how old do you have to be",
        "Is there an income limit?",
        # Broke the injection detector too: "act as" inside an ordinary question.
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

    update = await gate(_state("can we play true or false", age_band="5-8", persona="stella"))

    directive = update["ui_directives"][0]
    assert directive["t"] == "game"
    assert directive["game"] == "true_false"
    # No puzzle and no answer may ride on a game directive.
    assert set(directive) == {"t", "game", "concept", "difficulty"}
    assert "messages" not in update


async def test_asking_to_play_without_choosing_asks_which() -> None:
    """It asks. It does not pick one on the child's behalf."""
    gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: True)

    update = await gate(_state("can we play a game", age_band="9-12", persona="stella"))

    assert isinstance(update["messages"][0], AIMessage)
    # Every game the band may play, by the name a reader is shown. A game that
    # reaches this list without a row in `_GAME_LABELS` shows as its wire id.
    assert set(update["quick_replies"]) == {
        "True or false",
        "Word scramble",
        "Millionaire",
        "Hangman",
    }
    assert "ui_directives" not in update


async def test_a_band_that_may_not_play_a_named_game_is_offered_what_it_can() -> None:
    """A five-year-old asking for the spelling game is not told no and dropped."""
    gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: True)

    update = await gate(_state("word scramble please", age_band="5-8", persona="stella"))

    assert update["quick_replies"] == ["True or false", "Hangman"]
    assert "ui_directives" not in update


async def test_a_disabled_module_never_opens_its_card() -> None:
    gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: False)
    assert await gate(_state("Am I eligible?")) == {}
    assert await gate(_state("let's play a game")) == {}


# ── registration intent, for the personas that cannot register ───────────────


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


# ── the game card is gated on persona, not only on band ──────────────────────


class TestWhoIsOfferedAGame:
    """Aurora and Nova are adult bands, and adult bands cleared the band gate.

    So the card opened for a guardian or a teacher and `POST /api/games/start`
    then refused the same request with `not_available_for_persona` -- the card
    rendered and sat dead on the page. The two gates disagreed; this is the band
    gate learning what the engine already knew.
    """

    async def test_a_guardian_is_not_offered_a_game(self) -> None:
        gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: True)
        update = await gate(
            _state("can we play a game", persona="aurora", age_band="adult")
        )
        assert update == {}

    async def test_a_teacher_is_not_offered_a_game(self) -> None:
        gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: True)
        update = await gate(
            _state("can we play a game", persona="nova", age_band="adult")
        )
        assert update == {}

    @pytest.mark.parametrize(
        ("persona", "band"),
        [("stella", "9-12"), ("orion", "13-15"), ("everyone", "13-15")],
    )
    async def test_a_playing_persona_still_gets_the_card(self, persona, band) -> None:
        gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: True)
        update = await gate(_state("can we play a game", persona=persona, age_band=band))
        assert update.get("quick_replies")


class TestALongQuestionIsNotACard:
    """The measured failure the word-count guard exists for."""

    async def test_a_question_containing_eligible_is_answered_not_formed_at(self) -> None:
        gate = make_intent_gate(eligibility_on=lambda: True, games_on=lambda: True)
        update = await gate(
            _state("Can my daughter play a game about who is eligible?", persona="aurora")
        )
        assert update == {}

    async def test_a_question_about_how_signing_up_works_reaches_the_model(self) -> None:
        gate = make_intent_gate(eligibility_on=lambda: True, games_on=lambda: True)
        update = await gate(
            _state("How does signing up work for a nine-year-old?", persona="aurora")
        )
        assert update == {}

    async def test_the_short_command_still_answers_instantly(self) -> None:
        gate = make_intent_gate(eligibility_on=lambda: True, games_on=lambda: False)
        update = await gate(_state("Am I eligible?", persona="aurora"))
        assert update != {}


class TestTheStoryFlowIsAlwaysAskedFor:
    """The client's rule: the assistant must never start telling stories itself.

    The guarantee is structural rather than a prompt line. `story_topic` is what
    turns a turn into a story, `cards._story_turn` is the only thing that sets
    it, and it only ever sets it after `wants_story` matched the reader's own
    text. Nothing in the planner, the tutor or the router can reach it.
    """

    def test_asking_for_a_story_asks_what_about_rather_than_telling_one(self):
        from langchain_core.messages import AIMessage, HumanMessage

        from app.graph.nodes.cards import make_intent_gate
        import asyncio

        gate = make_intent_gate()
        update = asyncio.run(
            gate({"messages": [HumanMessage("tell me a story")], "locale": "en"})
        )
        assert update["awaiting_story_topic"] is True
        # A card, so the turn ends here and nothing is generated yet.
        assert update["safety_flags"]["card"] == "story_topic"
        assert isinstance(update["messages"][0], AIMessage)
        assert update["quick_replies"]
        # Crucially, no topic yet — so no story can be written this turn.
        assert "story_topic" not in update

    def test_the_next_message_becomes_the_topic_and_is_not_a_card(self):
        """Turn two must reach an agent: a story is prose, not a form."""
        from langchain_core.messages import HumanMessage

        from app.graph.nodes.cards import make_intent_gate
        import asyncio

        gate = make_intent_gate()
        update = asyncio.run(
            gate(
                {
                    "messages": [HumanMessage("saving money")],
                    "locale": "en",
                    "awaiting_story_topic": True,
                }
            )
        )
        assert update == {"awaiting_story_topic": False, "story_topic": "saving money"}

    def test_an_ordinary_question_never_starts_a_story(self):
        from langchain_core.messages import HumanMessage

        from app.graph.nodes.cards import make_intent_gate
        import asyncio

        gate = make_intent_gate()
        for question in (
            "what is ASPIRE",
            "how do I save money",
            "what is the story with my application",
        ):
            update = asyncio.run(
                gate({"messages": [HumanMessage(question)], "locale": "en"})
            )
            assert "story_topic" not in update, question
            assert not update.get("awaiting_story_topic"), question

    def test_a_story_is_measured_against_the_story_cap(self):
        """The youngest band's chat cap is 35 words, which truncates a story."""
        from app.graph.nodes.safety_out import cap_for

        for band in ("5-8", "9-12", "13-15"):
            plain = cap_for(band, None)
            story = cap_for(band, None, story=True)
            assert plain is not None and story is not None
            assert story > plain, band


def test_a_story_gets_more_room_than_the_same_turn_would_otherwise():
    """The measurement, not just the table.

    `cap_for` having a story column proves nothing on its own: the flag has to
    reach `safety_out` and be passed to `over_cap` on the way. This runs the
    real node twice over the same over-long story and asserts the only
    difference -- `story_topic` -- changes where it is cut.
    """
    import asyncio

    from langchain_core.messages import AIMessage, HumanMessage

    from app.graph.nodes.safety_out import make_safety_out

    # Comfortably over the 5-8 QA cap (120) and the story cap (160).
    story = ("In Basseterre, Maya wanted a gift for her brother. " * 22).strip()
    base = {
        "age_band": "5-8",
        "persona": "stella",
        "locale": "en",
        "active_agent": "qa_agent_public",
        "messages": [HumanMessage("saving money"), AIMessage(story)],
    }

    async def run(state):
        return await make_safety_out(None)(state)

    plain = asyncio.run(run({**base}))
    told = asyncio.run(run({**base, "story_topic": "saving money"}))

    plain_words = len(plain["messages"][0].content.split())
    told_words = len(told["messages"][0].content.split())
    assert told_words > plain_words, (plain_words, told_words)
