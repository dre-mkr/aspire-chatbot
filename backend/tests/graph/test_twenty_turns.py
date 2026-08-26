"""A conversation has to survive being a long one.

Nothing in this graph caps a conversation: `memory_window_turns` bounds what is
REPLAYED to the model, not what may be said, and a rolling summary carries the
rest. That is the design, and this file is the proof -- because the way a
twenty-turn conversation actually breaks is not a limit being hit. It is one
activity's state outliving its welcome and claiming turns that belong to the
next thing: a story arc that will not close, a plan that becomes a mode, an
offered video that answers a "yes" three turns later.

So this drives every guide through a long, mixed session -- questions, a game,
a video, a lesson, a plan, a story, and out the other side -- and asserts the
reader can still be heard at turn twenty.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from app.graph.nodes.cards import make_intent_gate
from app.graph.state import initial_state
from tests.graph.test_every_guide_tells_a_story import GUIDES

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


gate = make_intent_gate()

#: The keys the cards node owns and carries between turns. `story_topic` and
#: `plan_goal` are deliberately absent: `hydrate` clears both every turn, and a
#: session that carried them would prove the opposite of what this file claims.
CARRIED = (
    "story_arc", "plan_arc", "offered_video", "awaiting_story_topic",
    "awaiting_teen_age", "pledge", "collectibles", "tin",
)

#: Twenty-two turns of a real conversation, in the order a reader has them.
SCRIPT: tuple[str, ...] = (
    "hi",
    "what is ASPIRE",
    "do i get money from it",
    "how much do i get",
    "i want a game",
    "True or false",
    "what is a need",
    "teach me about saving",
    "make it simpler",
    "what is interest",
    "how do i save up for a bike",
    "how much should i put away each week",
    "how long will that take",
    "what video do you have about savings",
    "watch a video",
    "tell me a story",
    "Saving up for something",
    "Buy the juice (EC$8)",
    "make her a fisherman",
    "what happens next",
    "thanks, that helps",
    "bye",
)


async def _drive(persona, band, locale="en", script=SCRIPT):
    """Run the script through the cards node, carrying its own state forward."""
    carried: dict = {}
    seen = []
    for turn, message in enumerate(script, start=1):
        state = initial_state(
            session_id="s", user_id="u", device_id="d",
            persona=persona, age_band=band, account_status="active", locale=locale,
        )
        state.update(carried)
        state["messages"] = [HumanMessage(content=message)]
        update = await gate(state)
        for key in CARRIED:
            if key in update:
                carried[key] = update[key]
        seen.append((turn, message, update))
    return seen, carried


class TestTwentyTurnsHold:
    @pytest.mark.parametrize("persona,band", GUIDES)
    async def test_the_session_survives_the_whole_script(self, persona, band):
        seen, _ = await _drive(persona, band)
        assert len(seen) == len(SCRIPT) >= 20

    @pytest.mark.parametrize("persona,band", GUIDES)
    async def test_the_reader_is_still_heard_at_turn_twenty(self, persona, band):
        """The real failure mode: state from turn six eating turn twenty."""
        _, carried = await _drive(persona, band)
        state = initial_state(
            session_id="s", user_id="u", device_id="d",
            persona=persona, age_band=band, account_status="active", locale="en",
        )
        state.update(carried)
        state["messages"] = [HumanMessage(content="tell me a story")]
        out = await gate(state)
        assert out.get("awaiting_story_topic") is True, (
            "after twenty turns a story request was swallowed by leftover state"
        )

    @pytest.mark.parametrize("persona,band", GUIDES)
    async def test_no_activity_outlives_the_conversation(self, persona, band):
        """A plan is a short exchange, not a mode; a closed story is closed."""
        _, carried = await _drive(persona, band)
        arc = carried.get("plan_arc") or {}
        assert not arc or arc.get("turns", 0) <= 4

    @pytest.mark.parametrize("locale", ["en", "es", "fr"])
    async def test_length_is_not_an_english_privilege(self, locale):
        seen, _ = await _drive("kaleb", "9-12", locale=locale)
        assert len(seen) == len(SCRIPT)


class TestTheLongSessionStillDoesTheWork:
    async def test_the_story_actually_ran_inside_it(self):
        """Not just "no exception" -- the story really opened and was played."""
        seen, carried = await _drive("kaleb", "9-12")
        by_message = {m: u for _, m, u in seen}
        assert by_message["tell me a story"].get("awaiting_story_topic") is True
        opened = by_message["Saving up for something"]["story_arc"]
        assert opened["beat"] == 1 and opened["wallet"] == 100
        spent = by_message["Buy the juice (EC$8)"]["story_arc"]
        assert spent["wallet"] == 92, "the wallet did not survive a long session"
        steered = by_message["make her a fisherman"]["story_arc"]
        assert steered["direction"] == "make her a fisherman"

    async def test_the_plan_ran_inside_it(self):
        seen, _ = await _drive("kaleb", "9-12")
        by_message = {m: u for _, m, u in seen}
        assert by_message["how do i save up for a bike"]["plan_goal"] == "a bike"
        assert by_message["how much should i put away each week"]["plan_goal"] == "a bike"

    async def test_the_video_ran_inside_it(self):
        seen, _ = await _drive("kaleb", "9-12")
        by_message = {m: u for _, m, u in seen}
        played = by_message["what video do you have about savings"]
        assert (played.get("safety_flags") or {}).get("card") == "video"

    async def test_a_hundred_turns_is_no_different_from_twenty(self):
        """There is no cap, so saying so once is worth more than assuming it."""
        long_script = SCRIPT * 5
        seen, _ = await _drive("kaleb", "9-12", script=long_script)
        assert len(seen) == len(long_script) >= 100
