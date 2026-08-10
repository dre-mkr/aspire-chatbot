"""Three layers, one builder, and a prefix that can actually cache."""

from __future__ import annotations

import pytest

from app.context.session_context import SessionContext, Turn
from app.graph.state import KBChunk
from app.prompting import GLOBAL, build_messages, persona_card
from app.prompting.global_rules import LOAD_BEARING
from app.prompting.personas import FALLBACK, KNOWN

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
        """Each is a safety decision somebody made on purpose, and each is the kind of line an editor tightening prose w…"""
        assert " ".join(clause.split()) in " ".join(GLOBAL.split())

    def test_it_reaches_the_prompt(self):
        messages = build_messages(context=_context(), agent_role=ROLE, user_text="hi")
        assert "Never invent a figure" in messages[0].content

    def test_the_retrieval_rules_did_NOT_move_here(self):
        """GROUNDING and ANSWER-DO-NOT-NARRATE are about answering from retrieved rows, which is the Q&A agent's job and…"""
        assert "according to the knowledge base" not in GLOBAL
        assert "Answer from those entries" not in GLOBAL


class TestPersonaCards:
    @pytest.mark.parametrize("persona", sorted(KNOWN))
    def test_every_persona_has_one(self, persona):
        assert persona_card(persona).strip()

    def test_they_differ_from_each_other(self):
        cards = {persona: persona_card(persona) for persona in KNOWN}
        assert len(set(cards.values())) == len(KNOWN)

    def test_an_unknown_persona_falls_back_to_the_adult_card(self):
        """The direction matters."""
        assert persona_card("nonsense") == persona_card(FALLBACK)
        assert persona_card(None) == persona_card(FALLBACK)

    def test_the_card_reaches_the_prompt(self):
        stella = build_messages(context=_context(), agent_role=ROLE, user_text="hi")
        aurora = build_messages(
            context=_context(persona="aurora", age_band="adult", account_status="guardian"),
            agent_role=ROLE,
            user_text="hi",
        )
        assert "You are Stella" in stella[0].content
        assert "You are Aurora" in aurora[0].content
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
        """`qa/nodes.py:485` put them in the system block via `GENERATE_SYSTEM.format(context=...)`, which is why that a…"""
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
        """Computed, PII-redacted and checkpointed since the graph shipped, and read by no prompt until now."""
        messages = build_messages(
            context=_context(running_summary="They are working on saving."),
            agent_role=ROLE,
            user_text="hi",
        )
        assert "They are working on saving." in messages[1].content

    def test_the_date_is_included(self):
        """No prompt in the product had it, so every deadline question was answered without knowing today."""
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
        assert "You are Stella" in prefix
        assert "THE IDEA" in prefix
        assert "what is saving" in per_turn
        assert "learning about saving" in per_turn
