"""Four defects found by the 23 August 2026 production sweep, and their fixes.

Each was silent: green build, passing suite, no error anywhere. Each was found
by holding a conversation with aspire.eccugenai.app rather than by running the
tests, which is why each now has a test.
"""

from __future__ import annotations

import pytest

from app.domain import Language, Persona


# ── 1. every named guide says its own name ───────────────────────────────────


class TestEachGuideSaysItsOwnName:
    """All seven pairs returned the byte-identical "I'm the ASPIRE assistant".

    Six named guides -- Skye, Kaleb, Zion at two bands, Imani, Azuri -- with
    their own cards, artwork and voices, and not one said its own name. They
    always could: "Are you Kaleb?" answered "Yes. I'm Kaleb" from the card. Only
    the OPEN question was hard-coded, so the phrasing a reader is most likely to
    use was the one that lost the persona.
    """

    @pytest.mark.parametrize(
        "persona,band,expected",
        [
            ("stella", "5-8", "Skye"),
            ("kaleb", "9-12", "Kaleb"),
            ("orion", "13-15", "Zion"),
            ("orion", "16-18", "Zion"),
            ("aurora", "adult", "Imani"),
            ("nova", "adult", "Azuri"),
        ],
    )
    def test_the_guide_names_itself(self, persona: str, band: str, expected: str):
        from app.agents.qa.nodes import _identity_reply

        reply = _identity_reply({"persona": persona, "age_band": band}, "en")
        assert expected in reply, f"{persona}/{band} did not say {expected!r}"

    @pytest.mark.parametrize("locale", ["en", "es", "fr"])
    def test_it_names_itself_in_every_language(self, locale: str):
        from app.agents.qa.nodes import _identity_reply

        reply = _identity_reply({"persona": "kaleb", "age_band": "9-12"}, locale)
        assert "Kaleb" in reply

    def test_guest_stays_generic_because_it_has_no_name_to_give(self):
        """"Guest" is the absence of a name, not one."""
        from app.agents.qa.nodes import _identity_reply

        reply = _identity_reply({"persona": "guest", "age_band": "13-15"}, "en")
        assert "ASPIRE assistant" in reply
        assert "I'm Guest" not in reply

    def test_an_unknown_persona_falls_back_rather_than_erroring(self):
        from app.agents.qa.nodes import _identity_reply

        assert _identity_reply({}, "en")
        assert _identity_reply({"persona": "nobody"}, "en")


# ── 2. Kaleb is never HEARD in Skye's voice ──────────────────────────────────


class TestKalebIsSilentRatherThanBorrowed:
    """He boots on the understudy id and is refused audio in it.

    The client's ruling on the game banks was that Kaleb and Skye are different
    personas. A shared voice is that same borrowing in the one channel a reader
    cannot miss -- and he has his own avatar, a boy of about eleven, for it to
    contradict.
    """

    @staticmethod
    def _settings(**kw):
        from app.voice.config import VoiceSettings

        base = dict(
            voice_stella="ID_SKYE",
            voice_orion="ID_ZION",
            voice_aurora="ID_IMANI",
            voice_nova="ID_AZURI",
            voice_guest="ID_GUEST",
        )
        base.update(kw)
        return VoiceSettings(**base)

    @pytest.mark.parametrize("language", list(Language))
    def test_he_is_never_native_on_a_borrowed_id(self, language: Language):
        from app.voice.registry import _resolve_voice_id

        resolved = _resolve_voice_id(self._settings(), Persona.KALEB, language)
        assert resolved is not None, "he must still BOOT"
        _, native = resolved
        assert native is False, (
            f"kaleb/{language.value} would play in Skye's voice"
        )

    def test_setting_his_own_voice_turns_english_on(self):
        from app.voice.registry import _resolve_voice_id

        resolved = _resolve_voice_id(
            self._settings(voice_kaleb="ID_KALEB"), Persona.KALEB, Language.EN
        )
        assert resolved == ("ID_KALEB", True)

    def test_guest_still_speaks_because_it_has_no_face_to_contradict(self):
        """Silencing the default voice would cost more than it protects."""
        from app.voice.registry import _resolve_voice_id

        resolved = _resolve_voice_id(self._settings(), Persona.GUEST, Language.EN)
        assert resolved is not None and resolved[1] is True

    def test_nobody_else_was_silenced_by_the_change(self):
        from app.voice.registry import _resolve_voice_id

        for persona in (Persona.STELLA, Persona.ORION, Persona.AURORA, Persona.NOVA):
            resolved = _resolve_voice_id(self._settings(), persona, Language.EN)
            assert resolved is not None and resolved[1] is True, persona.value


# ── 3. the programme's own sums reach a five-year-old ────────────────────────


class TestTheProgrammeAmountsAreNotHiddenFromTheChildTheyBelongTo:
    """A five-year-old asking how much ASPIRE gives her was told to ask a
    grown-up -- about her own account, funded in her name, on a public poster.

    The exception is exactly two numbers wide. Everything the card's rationale
    actually targets -- a rate, a projection, a balance -- is still refused.
    """

    PUBLISHED = "ASPIRE gives you EC$1,000. EC$500 is saved and EC$500 is invested."

    def test_the_published_split_survives_when_programme_grounded(self):
        from app.graph.nodes.safety_out import has_figure

        assert has_figure(self.PUBLISHED) is True, "still blocked without the lift"
        assert has_figure(self.PUBLISHED, programme_scope=True) is False

    @pytest.mark.parametrize(
        "text,what",
        [
            ("The bank pays 2 percent a year.", "a rate"),
            ("The bank pays 2% a year.", "a percentage"),
            ("After one year you would have EC$510.05.", "a projection"),
            ("Your balance is EC$1,247.30.", "a balance"),
        ],
    )
    def test_what_the_card_actually_targets_is_still_refused(self, text, what):
        from app.graph.nodes.safety_out import has_figure

        assert has_figure(text, programme_scope=True) is True, (
            f"{what} reached a five-year-old"
        )

    def test_the_lift_needs_grounding_and_is_not_free(self):
        """No retrieval, no lift -- the conservative direction."""
        from app.graph.nodes.safety_out import grounded_in_the_programme

        assert grounded_in_the_programme({}) is False
        assert grounded_in_the_programme({"retrieved": []}) is False

    def test_the_reprompt_says_which_figures_may_stay(self):
        from app.graph.nodes.safety_out import figure_instruction

        scoped = figure_instruction(programme_scope=True)
        assert "EC$500" in scoped and "EC$1,000" in scoped
        assert "Remove every money amount" in figure_instruction()


# ── 4. games in an unauthored language say so kindly ─────────────────────────


class TestGamesNotYetInThisLanguage:
    """Every seed file is English. Spanish and French have no entries at all.

    The reader used to get the developer's sentence -- "No hangman set has been
    authored in fr yet" -- which reads as a fault rather than as a gap.
    """

    @pytest.mark.parametrize("language", list(Language))
    def test_the_message_exists_in_the_readers_own_language(self, language: Language):
        from app.games.engine import _not_yet_in_this_language

        assert _not_yet_in_this_language(language).strip()

    @pytest.mark.parametrize(
        "language,marker",
        [(Language.ES, "vuelve pronto"), (Language.FR, "reviens bient")],
    )
    def test_it_tells_them_to_come_back(self, language: Language, marker: str):
        from app.games.engine import _not_yet_in_this_language

        assert marker in _not_yet_in_this_language(language)

    @pytest.mark.parametrize("language", list(Language))
    def test_it_never_leaks_the_developers_wording(self, language: Language):
        from app.games.engine import _not_yet_in_this_language

        message = _not_yet_in_this_language(language).lower()
        for leak in ("authored", "set has been", "game_type", "no set"):
            assert leak not in message

    def test_english_still_has_content_so_the_offer_is_honest(self):
        """The message says English works now. It has to be true."""
        import inspect

        from app.games import hangman, millionaire, scramble, truefalse

        for module in (hangman, millionaire, scramble, truefalse):
            cls = next(
                obj
                for obj in vars(module).values()
                if inspect.isclass(obj) and hasattr(obj, "sets_for")
            )
            assert cls().sets_for(Language.EN), f"{module.__name__} has no English sets"
