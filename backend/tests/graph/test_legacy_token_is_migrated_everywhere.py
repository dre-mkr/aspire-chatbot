"""A token minted before the split must not get the old persona's world.

`TOKEN_TTL` is seven days, so for a week after `kaleb.9-12.md` took the 9-12
band there are live sessions whose token still says `stella` at that band.
`allowed_agents` migrated them for ROUTING and always did -- but it migrates a
local copy, and `identity_from` put the raw claim into state. Everything
downstream reads state.

Measured on the tree, 23 August 2026, for a legacy `stella/9-12` token:

    agents    correct -- access normalises its own copy
    CARD      Skye's 5-8 card, to a reader in secondary school. The exact
              defect the split existed to fix, arriving through the one door
              nobody had shut
    GAMES     Skye's 5-8 bank -- MONEY, COIN, SAVE -- not Kaleb's
    VOICE     resolved as `stella`, marked native, and PLAYED. The whole
              never-borrow rule was bypassed by the token saying stella
    identity  correct, and only because it had been patched separately

Fixed at the seam rather than at six call sites, because a seventh reader of
`state["persona"]` was always going to be written. These tests assert the seam
holds and, separately, that each downstream site now agrees.
"""

from __future__ import annotations

import pytest

from app.domain import Language, Persona, normalise_persona_band

LEGACY_PERSONA = "stella"
LEGACY_BAND = "9-12"
MIGRATED = "kaleb"


class TestTheSeam:
    """`identity_from` is the only place claims become state."""

    @staticmethod
    def _claims(**over):
        from app.graph.identity import SessionClaims

        base = dict(
            session_id="s",
            user_id="u",
            device_id="d",
            persona=LEGACY_PERSONA,
            age_band=LEGACY_BAND,
            account_status="beneficiary",
            locale="en",
        )
        base.update(over)
        return SessionClaims(**base)

    def test_state_carries_the_migrated_persona(self):
        from app.graph.nodes.hydrate import identity_from

        assert identity_from(self._claims())["persona"] == MIGRATED

    def test_a_current_token_is_untouched(self):
        from app.graph.nodes.hydrate import identity_from

        for persona, band in (("stella", "5-8"), ("kaleb", "9-12"), ("orion", "13-15")):
            state = identity_from(self._claims(persona=persona, age_band=band))
            assert state["persona"] == persona

    def test_the_band_is_not_rewritten(self):
        """Only the persona moved. The band is what it always was."""
        from app.graph.nodes.hydrate import identity_from

        assert identity_from(self._claims())["age_band"] == LEGACY_BAND

    def test_migration_is_idempotent(self):
        """Access normalises again downstream; that must cost nothing."""
        once = normalise_persona_band(LEGACY_PERSONA, LEGACY_BAND)
        assert normalise_persona_band(once, LEGACY_BAND) == once


class TestEverySiteAgrees:
    """The legacy pair and the current pair must reach the same world.

    Written as a comparison rather than as fixed expectations, so it keeps
    working when Kaleb's card, bank or voice changes.
    """

    def test_the_same_card(self):
        from app.prompting.personas import persona_card

        assert persona_card(MIGRATED, LEGACY_BAND) == persona_card(
            normalise_persona_band(LEGACY_PERSONA, LEGACY_BAND), LEGACY_BAND
        )

    def test_the_card_is_not_the_five_year_old_one(self):
        from app.prompting.personas import persona_card

        migrated = persona_card(normalise_persona_band(LEGACY_PERSONA, LEGACY_BAND), LEGACY_BAND)
        assert "Kaleb" in migrated
        assert migrated != persona_card("stella", "5-8")

    def test_the_same_name(self):
        from app.prompting.personas.names import display_name

        assert display_name(
            normalise_persona_band(LEGACY_PERSONA, LEGACY_BAND), LEGACY_BAND
        ) == display_name(MIGRATED, LEGACY_BAND)

    def test_the_same_identity_line(self):
        from app.agents.qa.nodes import _identity_reply

        legacy = _identity_reply(
            {"persona": LEGACY_PERSONA, "age_band": LEGACY_BAND}, "en"
        )
        current = _identity_reply({"persona": MIGRATED, "age_band": LEGACY_BAND}, "en")
        assert legacy == current
        assert "Kaleb" in legacy

    def test_the_same_agents(self):
        from app.graph.access import allowed_agents

        assert allowed_agents(
            LEGACY_PERSONA, LEGACY_BAND, "beneficiary", user_id="u"
        ) == allowed_agents(MIGRATED, LEGACY_BAND, "beneficiary", user_id="u")

    def test_the_same_videos(self):
        from app.videos.catalog import for_persona

        assert for_persona(Persona.KALEB) == for_persona(
            Persona(normalise_persona_band(LEGACY_PERSONA, LEGACY_BAND))
        )

    def test_the_voice_does_not_come_back_through_the_legacy_key(self):
        """Kaleb is silent until cast. A stale token must not un-silence him."""
        from app.voice.config import VoiceSettings
        from app.voice.registry import _resolve_voice_id

        settings = VoiceSettings(
            voice_stella="ID_SKYE",
            voice_orion="ID_ZION",
            voice_aurora="ID_IMANI",
            voice_nova="ID_AZURI",
            voice_guest="ID_GUEST",
        )
        migrated = Persona(normalise_persona_band(LEGACY_PERSONA, LEGACY_BAND))
        resolved = _resolve_voice_id(settings, migrated, Language.EN)
        assert resolved is not None
        assert resolved[1] is False, (
            "a pre-split token resolved to Stella and PLAYED, which is exactly "
            "the borrowing _NEVER_BORROWS_A_VOICE exists to stop"
        )

    @pytest.mark.parametrize(
        "game_type", ["hangman", "millionaire", "word_scramble", "truefalse"]
    )
    def test_the_same_game_bank(self, game_type: str):
        import inspect

        from app.games import hangman, millionaire, scramble, truefalse

        module = {
            "hangman": hangman,
            "millionaire": millionaire,
            "word_scramble": scramble,
            "truefalse": truefalse,
        }[game_type]
        cls = next(
            obj
            for obj in vars(module).values()
            if inspect.isclass(obj) and hasattr(obj, "sets_for")
        )
        game = cls()

        def items(persona: Persona) -> set[str]:
            return {
                entry.id
                for game_set in game.sets_for(Language.EN)
                for entry in game_set.entries
                if persona in entry.persona_bands
            }

        migrated = Persona(normalise_persona_band(LEGACY_PERSONA, LEGACY_BAND))
        assert items(migrated) == items(Persona.KALEB)
        assert items(migrated) != items(Persona.STELLA), (
            f"{game_type}: the migrated reader is still being served Skye's bank"
        )
