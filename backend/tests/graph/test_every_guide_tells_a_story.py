"""Every guide can carry a story, and every story is an adventure to play.

The mandate this file exists for: *all* of them, not the two that were
demonstrated. A story is the same machine behind every persona -- the arc, the
EC$100 wallet, the priced choices -- and only the shape of the prose differs.
That is easy to say and easy to break, because the prose shapes live in a
per-persona table and the wallet does not. One guide quietly losing its wallet
would turn an adventure back into a bedtime story with nobody noticing.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.qa.nodes import _STORY_BY_PERSONA, _story_instruction, follow_up_chips
from app.graph.nodes.cards import STORY_BEATS, make_intent_gate
from app.graph.state import initial_state

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


gate = make_intent_gate()

#: Every guide, with a band it is actually read in.
GUIDES: tuple[tuple[str, str], ...] = (
    ("stella", "5-8"),
    ("kaleb", "9-12"),
    ("orion", "13-15"),
    ("orion", "16-18"),
    ("aurora", "adult"),
    ("nova", "adult"),
    ("guest", "adult"),
)

ASKS: dict[str, str] = {
    "en": "tell me a story",
    "es": "cuentame una historia",
    "fr": "raconte-moi une histoire",
}


def _state(message, persona, band, locale="en", **over):
    s = initial_state(
        session_id="s", user_id="u", device_id="d",
        persona=persona, age_band=band, account_status="active", locale=locale,
    )
    s["messages"] = [HumanMessage(content=message)]
    s.update(over)
    return s


class TestEveryGuideCanBeAskedForOne:
    @pytest.mark.parametrize("persona,band", GUIDES)
    async def test_asking_opens_the_topic_question(self, persona, band):
        out = await gate(_state("tell me a story", persona, band))
        assert out["awaiting_story_topic"] is True
        assert out["messages"][0].content
        assert out["quick_replies"], "a child should not have to invent a topic"

    @pytest.mark.parametrize("persona,band", GUIDES)
    @pytest.mark.parametrize("locale", ["en", "es", "fr"])
    async def test_all_three_languages_reach_the_story(self, persona, band, locale):
        out = await gate(_state(ASKS[locale], persona, band, locale=locale))
        assert out["awaiting_story_topic"] is True


class TestEveryGuideGetsAnAdventure:
    """The wallet is what makes it playable rather than told."""

    @pytest.mark.parametrize("persona,band", GUIDES)
    async def test_the_topic_opens_an_arc_with_a_wallet(self, persona, band):
        out = await gate(
            _state("Saving up for something", persona, band, awaiting_story_topic=True)
        )
        arc = out["story_arc"]
        assert arc["beat"] == 1
        assert arc["wallet"] == 100, f"{persona} lost the adventure"
        assert arc["inventory"] == []
        assert out["story_topic"] == "Saving up for something"

    @pytest.mark.parametrize("persona,band", GUIDES)
    async def test_a_topic_of_their_own_making_is_honoured(self, persona, band):
        """"Create their own adventure" -- not only the three suggested topics."""
        out = await gate(
            _state("a girl who wants a telescope", persona, band, awaiting_story_topic=True)
        )
        assert out["story_arc"]["topic"] == "a girl who wants a telescope"
        assert out["story_arc"]["wallet"] == 100

    @pytest.mark.parametrize("persona,band", GUIDES)
    async def test_a_priced_choice_spends_the_wallet(self, persona, band):
        out = await gate(
            _state(
                "Buy the rope (EC$30)", persona, band,
                story_arc={"topic": "Saving up", "beat": 1, "wallet": 100, "inventory": []},
            )
        )
        arc = out["story_arc"]
        assert arc["wallet"] == 70, f"{persona} did not pay for the rope"
        assert arc["beat"] == 2

    @pytest.mark.parametrize("persona,band", GUIDES)
    async def test_steering_changes_the_story_rather_than_ending_it(self, persona, band):
        """"Create their own adventure": the reader's sentence steers the plot."""
        out = await gate(
            _state(
                "make her a fisherman", persona, band,
                story_arc={"topic": "Saving up", "beat": 2, "wallet": 100, "inventory": []},
            )
        )
        assert out["story_arc"]["direction"] == "make her a fisherman"
        assert out["story_arc"]["beat"] == 3


class TestEveryGuideIsToldHowToWriteIt:
    @pytest.mark.parametrize("persona,band", GUIDES)
    def test_the_guide_has_its_own_shape(self, persona, band):
        state = _state("x", persona, band, story_topic="Saving up",
                       story_arc={"topic": "Saving up", "beat": 1, "wallet": 100})
        line = _story_instruction(state)
        assert line, f"{persona} was given no story instruction"

    @pytest.mark.parametrize("persona,band", GUIDES)
    def test_the_last_beat_is_told_to_land(self, persona, band):
        state = _state("x", persona, band, story_topic="Saving up",
                       story_arc={"topic": "Saving up", "beat": STORY_BEATS, "wallet": 100})
        line = _story_instruction(state)
        assert "LAST part" in line, "a story with no ending is a treadmill"

    def test_an_unknown_guide_still_gets_a_story(self):
        """A persona key that is not in the table falls back rather than failing."""
        state = _state("x", "someone-new", "9-12", story_topic="Saving up",
                       story_arc={"topic": "Saving up", "beat": 1, "wallet": 100})
        assert _story_instruction(state)

    def test_every_guide_in_the_product_has_a_shape(self):
        for persona, _ in GUIDES:
            assert persona in _STORY_BY_PERSONA, f"{persona} has no story shape"


class TestTheChoicesReachTheReader:
    @pytest.mark.parametrize("persona,band", GUIDES)
    def test_priced_lines_become_the_chips(self, persona, band):
        answer = (
            "Mara counted her money.\n"
            "Buy the juice (EC$8)\n"
            "Buy the bell (EC$12)\n"
            "Walk home (free)"
        )
        state = _state("x", persona, band, story_topic="Saving up",
                       story_arc={"topic": "Saving up", "beat": 2, "wallet": 100})
        state["messages"].append(AIMessage(content=answer))
        chips = follow_up_chips(state, [], set(), answer)
        assert chips == ["Buy the juice (EC$8)", "Buy the bell (EC$12)", "Walk home (free)"]
