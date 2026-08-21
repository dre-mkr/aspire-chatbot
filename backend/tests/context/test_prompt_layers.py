"""Three layers, one builder, and a prefix that can actually cache."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.context.session_context import (
    SessionContext,
    Turn,
    conversation_reference,
)
from app.graph.state import KBChunk
from app.prompting import GLOBAL, build_messages, persona_card
from app.prompting.global_rules import LOAD_BEARING
from app.prompting.personas import FALLBACK, KNOWN
from app.prompting.personas.names import NAMES, display_name

ROLE = "Answer the question from the reference material."


def _context(**overrides) -> SessionContext:
    fields = {
        "persona": "stella",
        "age_band": "9-12",
        "locale": "en",
        "account_status": "beneficiary",
    }
    fields.update(overrides)
    return SessionContext(**fields)


class TestTheGlobalLayerIsAliveAgain:
    @pytest.mark.parametrize("clause", LOAD_BEARING)
    def test_every_load_bearing_clause_survives_verbatim(self, clause):
        """Each clause is a deliberate safety decision, easily lost to a prose edit."""
        assert " ".join(clause.split()) in " ".join(GLOBAL.split())

    def test_it_reaches_the_prompt(self):
        messages = build_messages(context=_context(), agent_role=ROLE, user_text="hi")
        assert "Never invent a figure" in messages[0].content

    def test_the_retrieval_rules_did_NOT_move_here(self):
        """Answering from retrieved rows is the Q&A agent's job, not a global rule."""
        assert "according to the knowledge base" not in GLOBAL
        assert "Answer from those entries" not in GLOBAL


class TestPersonaCards:
    @pytest.mark.parametrize("persona", sorted(KNOWN))
    def test_every_persona_has_one(self, persona):
        assert persona_card(persona).strip()

    def test_they_differ_from_each_other(self):
        cards = {persona: persona_card(persona) for persona in KNOWN}
        assert len(set(cards.values())) == len(KNOWN)

    def test_an_unknown_persona_falls_back_to_the_most_restrictive_card(self):
        """
        The direction matters, and this test did not pin it.

        Comparing an unknown persona against `FALLBACK` passes whichever way
        `FALLBACK` points, so it went on passing when the fallback was `aurora`
        -- and an unknown persona, a URL typo, a value from an older client, a
        token minted before a rename, lost every piece of child-safety wording
        at once and was answered as a guardian. A fallback is reached when
        something has already gone wrong, which is the worst moment to widen
        what may be said. Named now, not just referenced.
        """
        assert FALLBACK == "stella"
        assert persona_card("nonsense") == persona_card("stella")
        assert persona_card(None) == persona_card("stella")
        assert persona_card("nonsense") != persona_card("aurora")

    def test_the_card_reaches_the_prompt(self):
        stella = build_messages(context=_context(), agent_role=ROLE, user_text="hi")
        aurora = build_messages(
            context=_context(persona="aurora", age_band="adult", account_status="guardian"),
            agent_role=ROLE,
            user_text="hi",
        )
        # Read from the name table, never spelled out. The label is a client's
        # choice and changes in one line; pinning it here is what turns that one
        # line back into a hunt through the test suite. Looked up WITH the band,
        # because `stella` answers to Skye at 5-8 and Kaleb at 9-12.
        assert f"You are {display_name('stella', '9-12')}" in stella[0].content
        assert f"You are {display_name('aurora', 'adult')}" in aurora[0].content
        assert stella[0].content != aurora[0].content


class TestTheCacheBreakpoint:
    def test_the_prefix_is_byte_identical_across_turns(self):
        """The one property the whole layout exists for."""
        first = build_messages(context=_context(), agent_role=ROLE, user_text="what is saving")
        later = build_messages(
            context=_context(
                running_summary="They are learning about saving.",
                recent_turns=[
                    Turn(role="user", text="what is saving"),
                    Turn(role="assistant", text="Keeping some for later."),
                ],
                display_name="Ana",
            ),
            agent_role=ROLE,
            user_text="why?",
            retrieved=[KBChunk(kb_id="ASP-001", content="Saving means keeping money.")],
        )

        assert first[0].content == later[0].content

    def test_nothing_per_turn_leaks_into_the_prefix(self):
        context = _context(display_name="Ana", running_summary="A summary.")
        prefix = build_messages(context=context, agent_role=ROLE, user_text="hi")[0].content

        assert "Ana" not in prefix
        assert "A summary." not in prefix
        assert "Today is" not in prefix

    def test_retrieved_chunks_go_in_the_human_turn(self):
        """In the system block they would break the cacheable prefix every turn."""
        messages = build_messages(
            context=_context(),
            agent_role=ROLE,
            user_text="what is the deposit",
            retrieved=[KBChunk(kb_id="ASP-003", content="The minimum deposit is EC$25.")],
        )

        systems = [m.content for m in messages[:-1]]
        assert not any("ASP-003" in block for block in systems)
        assert "ASP-003" in messages[-1].content
        assert "EC$25" in messages[-1].content

    def test_an_extra_instruction_lands_below_the_breakpoint(self):
        """A widget composition prompt is present on some turns and absent on others."""
        plain = build_messages(context=_context(), agent_role=ROLE, user_text="hi")
        with_widget = build_messages(
            context=_context(), agent_role=ROLE, user_text="hi", extra_instruction="Emit ONE compare widget."
        )

        assert plain[0].content == with_widget[0].content
        assert "Emit ONE compare widget." in with_widget[1].content


class TestHistoryFinallyArrives:
    def test_the_last_turns_are_included_verbatim(self):
        messages = build_messages(
            context=_context(
                recent_turns=[
                    Turn(role="user", text="what is saving"),
                    Turn(role="assistant", text="Keeping some for later."),
                ]
            ),
            agent_role=ROLE,
            user_text="why?",
        )

        block = messages[1].content
        assert "user: what is saving" in block
        assert "assistant: Keeping some for later." in block

    def test_the_running_summary_is_included(self):
        """Computed and checkpointed since launch, read by no prompt until now."""
        messages = build_messages(
            context=_context(running_summary="They are working on saving."),
            agent_role=ROLE,
            user_text="hi",
        )
        assert "They are working on saving." in messages[1].content

    def test_the_date_is_included(self):
        """Without it, every deadline question is answered without knowing today."""
        messages = build_messages(context=_context(), agent_role=ROLE, user_text="hi")
        assert "Today is" in messages[1].content

    def test_an_opening_turn_adds_no_empty_history_block(self):
        messages = build_messages(context=_context(), agent_role=ROLE, user_text="hi")
        assert "The conversation so far" not in messages[1].content
        assert "Earlier in this conversation" not in messages[1].content


class TestTheLearnAgentUsesIt:
    @pytest.mark.asyncio
    async def test_the_teaching_call_carries_all_three_layers_and_history(self):
        from app.agents.learn import teach as teaching
        from app.curriculum.schema import load_all
        from app.graph.state import initial_state

        seen: list = []

        async def invoke(messages):
            seen.append(messages)
            return "Money you keep today is money you still have on Friday."

        state = initial_state(
            session_id="s",
            user_id="u",
            device_id="d",
            persona="stella",
            age_band="9-12",
            account_status="beneficiary",
        )
        state["active_agent"] = "learn_agent"
        state["context"] = _context(
            running_summary="They have been learning about saving.",
            recent_turns=[Turn(role="user", text="what is saving")],
        )
        state["learning"] = {"lesson_id": "l01_what_is_saving", "phase": "teaching"}

        await teaching.make_teach(load_all(refresh=True), invoke=invoke)(state)

        prefix, per_turn = seen[-1][0].content, seen[-1][1].content
        assert "Never invent a figure" in prefix
        assert f"You are {display_name('stella', '9-12')}" in prefix
        assert "THE IDEA" in prefix
        assert "what is saving" in per_turn
        assert "learning about saving" in per_turn


class TestTheReaderIsDescribedToTheModel:
    """
    `SessionContext` carried the band and the locale and wrote neither into a
    message. The reader's age reached the model only by implication, through
    which persona card got composed, and the language not at all.

    So both were stated for the first time in `safety_out`'s re-prompt -- the
    band after the model had already written past the cap, the language after it
    had already answered in the wrong one. Each of those is a whole extra model
    call spent rewriting an answer the reader already has.
    """

    @pytest.mark.parametrize("band", ["5-8", "9-12", "13-15", "16-18", "adult"])
    def test_the_band_is_stated_outright(self, band):
        messages = build_messages(context=_context(age_band=band), agent_role=ROLE, user_text="What is saving?")
        composed = "\n".join(str(message.content) for message in messages)

        assert band in composed

    @pytest.mark.parametrize(
        ("locale", "named"), [("en", "English"), ("es", "Spanish"), ("fr", "French")]
    )
    def test_the_language_is_named_not_coded(self, locale, named):
        """"es" is a string; Spanish is a language."""
        messages = build_messages(context=_context(locale=locale), agent_role=ROLE, user_text="¿Qué es ahorrar?")
        composed = "\n".join(str(message.content) for message in messages)

        assert named in composed

    def test_the_contact_details_reach_the_model(self):
        """
        GLOBAL says to offer them and never to invent one. Neither was
        satisfiable while nothing said what they are.
        """
        from app.config import get_settings

        settings = get_settings()
        messages = build_messages(context=_context(), agent_role=ROLE, user_text="How do I contact ASPIRE?")
        composed = "\n".join(str(message.content) for message in messages)

        assert settings.aspire_contact_email in composed
        assert settings.aspire_contact_phone in composed


class TestTheCardsRuntimePlaceholders:
    """A card quotes ASPIRE's details inside the script it reads out loud.

    `_contact_block` states them once and says, in the prompt, that they are the
    only ones. The six persona cards then quote them again inside the escalation
    sentence a reader is actually given -- "email {email} or call {phone}" --
    because a script with the details in it is the one the model reads back, and
    a script that says "the contact details above" is the one it paraphrases.

    Two places saying a phone number is one place saying it wrong, so the cards
    carry placeholders and the builder fills them from settings. The same goes
    for the conversation reference, which belongs to the session rather than to
    the deployment.
    """

    def _prefix(self, **overrides) -> str:
        return build_messages(
            context=_context(**overrides), agent_role=ROLE, user_text="hi"
        )[0].content

    def test_no_placeholder_survives_into_the_prompt(self):
        """A reader must never be told to quote a brace."""
        import re

        for persona, band in (
            ("stella", "5-8"),
            ("stella", "9-12"),
            ("orion", "13-15"),
            ("orion", "16-18"),
            ("aurora", "adult"),
            ("nova", "adult"),
            ("everyone", "5-8"),
        ):
            prefix = self._prefix(
                persona=persona,
                age_band=band,
                conversation_ref=conversation_reference("a-session"),
            )
            assert re.search(r"\{[A-Za-z0-9_]+\}", prefix) is None, (persona, band)

    def test_both_published_numbers_reach_the_model(self):
        """The cards offer two lines, so the block that authorises them must list two."""
        settings = get_settings()
        prefix = self._prefix()
        assert settings.aspire_contact_phone in prefix
        assert settings.aspire_contact_phone_alt in prefix

    def test_the_card_quotes_the_settings_value_not_a_literal(self, monkeypatch):
        """Change the number in one place and the escalation script follows."""
        from app.config import get_settings as fresh

        monkeypatch.setenv("ASPIRE_CONTACT_PHONE", "+1 (869) 555-0000")
        fresh.cache_clear()
        try:
            prefix = self._prefix()
            assert "+1 (869) 555-0000" in prefix
            assert "667-5566" not in prefix
        finally:
            fresh.cache_clear()

    def test_the_reference_is_the_sessions_own(self):
        reference = conversation_reference("session-one")
        assert reference.startswith("ASP-") and reference[4:].isdigit()
        assert len(reference[4:]) == 5
        assert reference in self._prefix(conversation_ref=reference)

    def test_the_reference_is_the_same_on_every_turn_of_a_session(self):
        """A reader given it, who hangs up and comes back, must get the same one."""
        assert conversation_reference("session-one") == conversation_reference("session-one")
        assert conversation_reference("session-one") != conversation_reference("session-two")

    def test_the_reference_does_not_break_the_cache_breakpoint(self):
        """It sits in the stable prefix, so it has to be stable."""
        reference = conversation_reference("session-one")
        first = self._prefix(conversation_ref=reference)
        later = self._prefix(conversation_ref=reference, display_name="Ana")
        assert first == later

    def test_a_sessionless_context_gets_a_phrase_rather_than_a_dangling_prefix(self):
        """"Tell them so they know we talked" is a sentence with a hole in it."""
        prefix = self._prefix(conversation_ref="")
        assert "your conversation reference" in prefix
        assert "ASP-#####" not in prefix
