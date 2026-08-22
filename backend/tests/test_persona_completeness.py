"""Every persona has a row of its own in every table that shapes what it says.

WRITTEN AFTER THE FACT, because the Kaleb split shipped three silent
regressions and the whole suite stayed green through all of them:

  * `_QA_DEPTH.get(key, _QA_DEPTH["nova"])` -- Kaleb missed, and a nine-year-old
    was answered in the register written for a teacher.
  * `_STORY_BY_PERSONA.get(persona, ...["guest"])` -- Kaleb missed, and got the
    mixed-audience story shape instead of a child's.
  * `DEFAULT_PERSONA["9-12"]` still said `stella`, whose 9-12 card had moved, so
    a signed-in ten-year-old fell through to `stella.5-8.md` -- Skye's card and
    Skye's name.

None of them raised. Every one was a `.get` with a sensible-looking default,
which is the failure mode this file exists to catch: a fallback that is correct
for an UNKNOWN persona is wrong for a KNOWN one, because a known persona
missing a row is an omission, not an unknown.

So these tests assert on `Persona` itself rather than on a list written here. A
persona added to the enum without its rows fails immediately, by name, and
whoever adds the seventh never has to know this file exists.
"""

from __future__ import annotations

import pytest

from app.domain import Persona


@pytest.mark.parametrize("persona", list(Persona), ids=lambda p: p.value)
class TestEveryPersonaIsFullyFurnished:
    def test_it_has_a_card_that_is_its_own(self, persona: Persona) -> None:
        """Not a fallback to somebody else's voice."""
        from app.prompting.personas import persona_card
        from app.prompting.personas.names import NAMES

        card = persona_card(persona.value)
        assert NAMES[persona.value] in card, (
            f"{persona.value} loaded a card that never says its own name, which "
            f"means `_card_text` fell through to another persona's file."
        )

    def test_it_has_a_qa_depth_block(self, persona: Persona) -> None:
        """The default is `nova`, the teacher's block. A child must never reach it."""
        from app.agents.qa.nodes import _QA_DEPTH

        assert persona.value in _QA_DEPTH, (
            f"{persona.value} has no depth block, so `qa_agent_role` will hand it "
            f"the `nova` default -- an educator's answer shape."
        )

    def test_it_has_a_story_shape(self, persona: Persona) -> None:
        """The default is `guest`, which is nobody's voice in particular."""
        from app.agents.qa.nodes import _STORY_BY_PERSONA

        assert persona.value in _STORY_BY_PERSONA, (
            f"{persona.value} has no story shape and would fall back to `guest`."
        )

    def test_it_has_a_name(self, persona: Persona) -> None:
        from app.prompting.personas.names import NAMES

        assert NAMES.get(persona.value), f"{persona.value} has no label."

    def test_it_has_a_voice(self, persona: Persona) -> None:
        """Directly or through an understudy -- `validate` fails startup otherwise."""
        from app.voice.registry import _DELIVERY

        assert persona in _DELIVERY, (
            f"{persona.value} has no delivery settings, so it would speak at "
            f"another persona's pace."
        )

    def test_it_is_in_the_access_vocabulary(self, persona: Persona) -> None:
        """A persona outside `PERSONAS` is refused every agent from a signed token."""
        from app.graph.access import PERSONAS

        assert persona.value in PERSONAS

    def test_it_grants_something_at_a_band_it_owns(self, persona: Persona) -> None:
        """A persona that grants nothing at every band is a dead entry."""
        from app.graph.access import allowed_agents
        from app.graph.state import AGE_BANDS

        granted = any(
            allowed_agents(persona.value, band, "beneficiary", user_id="u")
            for band in AGE_BANDS
        )
        assert granted, (
            f"{persona.value} grants no agents at any band, so a reader assigned "
            f"to it can reach nothing at all."
        )


class TestTheDefaultsPointAtPersonasThatCanServeThem:
    """`DEFAULT_PERSONA` is the signed-in half, and it is the one that was wrong."""

    def test_every_band_default_has_a_card_for_that_band(self) -> None:
        from app.graph.account import DEFAULT_PERSONA
        from app.prompting.personas import bands_with_cards

        for band, persona in DEFAULT_PERSONA.items():
            owned = bands_with_cards(persona)
            assert not owned or band in owned, (
                f"a signed-in reader at {band} resolves to {persona!r}, which has "
                f"cards for {sorted(owned)} -- so the loader falls through to "
                f"another band's voice."
            )

    def test_every_anonymous_default_has_a_card_for_that_band(self) -> None:
        from app.graph.account import _ANONYMOUS_BANDS
        from app.prompting.personas import bands_with_cards

        for persona, band in _ANONYMOUS_BANDS.items():
            owned = bands_with_cards(persona)
            assert not owned or band in owned, (
                f"an anonymous {persona!r} reader is put at {band}, which that "
                f"persona has no card for."
            )
