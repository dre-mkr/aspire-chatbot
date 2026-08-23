"""The language selector, from the body down to the locale the turn runs in.

This shipped exactly like "Explain it simply" did, and for the same reason: the
frontend carried the value correctly the whole way and the last join was never
made. `hydrate` set `locale` from the signed token and read only
`auto_language` from the body, so a reader pressing Espanol sent

    {"language": "es", "auto_language": false}

of which the first field was consumed by nothing. The result was not "the
control does nothing" -- it was worse. `auto_language: false` switches
`detect_language` OFF, so pressing Espanol stopped the conversation following
the reader WITHOUT putting it into Spanish. Doing nothing at all was strictly
better than using the control.

The greeting changed anyway, because the hook table is client-side. That is why
the two looked inconsistent to the person reporting it: one half of the feature
was real.

Each test below pins one link in that chain.
"""

from __future__ import annotations

import pytest

from app.graph.identity import mint_session_token
from app.graph.nodes.hydrate import make_hydrate


def _token(locale: str = "en") -> str:
    return mint_session_token(
        session_id="s-language-pin",
        user_id=None,
        device_id="d-1",
        persona="orion",
        age_band="13-15",
        account_status="prospect",
        locale=locale,
    )


class TestAPinnedLanguageReachesTheTurn:
    def test_pinning_spanish_sets_the_locale(self):
        update = make_hydrate(
            _token("en"), {"message": "hola", "language": "es", "auto_language": False}
        )({})
        assert update["locale"] == "es"

    def test_pinning_french_sets_the_locale(self):
        update = make_hydrate(
            _token("en"), {"message": "salut", "language": "fr", "auto_language": False}
        )({})
        assert update["locale"] == "fr"

    def test_pinning_back_to_english_also_works(self):
        """The way OUT of a language matters as much as the way in."""
        update = make_hydrate(
            _token("es"), {"message": "hi", "language": "en", "auto_language": False}
        )({})
        assert update["locale"] == "en"


class TestAutomaticSessionsAreUntouched:
    """Every client that predates the selector, and every reader who has not
    touched it, must behave exactly as before."""

    def test_without_the_flag_the_token_still_decides(self):
        update = make_hydrate(_token("es"), {"message": "hola"})({})
        assert update["locale"] == "es"
        assert update["auto_language"] is True

    def test_a_language_field_is_ignored_while_automatic(self):
        """Automatic means the detector decides, not a stale client value."""
        update = make_hydrate(
            _token("en"), {"message": "hola", "language": "es", "auto_language": True}
        )({})
        assert update["locale"] == "en"


class TestTheGuardHolds:
    @pytest.mark.parametrize("bogus", ["de", "EN", "", "es-MX", "zh", "  fr"])
    def test_a_locale_with_no_copy_is_refused(self, bogus):
        """`Locale` is a three-value Literal and the body is reader-controlled.

        Accepting anything else would put the turn into a language the product
        has no cards, no chips and no refusal text for.
        """
        update = make_hydrate(
            _token("en"),
            {"message": "hi", "language": bogus, "auto_language": False},
        )({})
        assert update["locale"] == "en"

    def test_pinning_without_naming_a_language_keeps_the_token_locale(self):
        update = make_hydrate(_token("fr"), {"message": "hi", "auto_language": False})(
            {}
        )
        assert update["locale"] == "fr"
