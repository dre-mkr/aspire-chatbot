"""Three post-merge defects in the video path, pinned.

All three are seams: two features that were each correct on their own branch
and wrong where they met on main.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault(
    "SESSION_SECRET", "test-only-secret-not-for-production-at-least-32-bytes"
)

from app.domain import Language, Persona  # noqa: E402
from app.graph.nodes import cards  # noqa: E402
from app.videos.catalog import all_videos, for_persona, has_subtitle, requested  # noqa: E402


# ── the split took the videos away from 9-12 ─────────────────────────────────


class TestKalebMayStillBeOfferedAVideo:
    """A 9-12 reader used to be `stella`, and `stella` is in every offer list.

    Giving Kaleb a key of his own moved that band onto a persona no video had
    ever heard of, so the whole 9-12 band silently stopped being offered one.
    Nothing failed: `for_persona` returning an empty tuple is a valid answer,
    and it is the answer for an adult mid-way through an eligibility question.
    """

    def test_every_video_offers_itself_to_kaleb(self):
        missing = [v.id for v in all_videos() if Persona.KALEB not in v.personas]
        assert not missing, (
            f"{missing} are not offered to `kaleb`, so no 9-12 reader is ever "
            f"shown one -- they were, as `stella`, before the split"
        )

    def test_the_band_that_lost_them_has_them_back(self):
        assert for_persona("kaleb"), "the 9-12 band is offered no video at all"

    @pytest.mark.parametrize("persona", ["stella", "kaleb", "orion", "guest"])
    def test_the_child_facing_personas_all_have_something_to_offer(self, persona):
        assert for_persona(persona)


# ── the request path never saw the caption gate ──────────────────────────────


class TestARequestIsGatedOnTheTrackNotTheLocale:
    """`requested` took a `language` that no caller passed.

    Every other video path moved onto `has_subtitle` when the multilingual work
    landed. This one kept an English-only test that no longer ran, so a French
    reader typing "montre-moi une vidéo" was handed a menu of two films with no
    track they could follow.
    """

    def test_english_still_resolves_a_named_subject(self):
        assert len(requested("show me the video about saving")) == 1

    @pytest.mark.parametrize("language", [Language.ES, Language.FR])
    def test_nothing_is_returned_while_no_track_exists(self, language):
        assert requested("show me the video about saving", language=language) == ()
        assert requested("show me a video", language=language) == ()

    @pytest.mark.parametrize("language", [Language.ES, Language.FR])
    def test_the_gate_is_the_asset_so_it_opens_by_itself(self, language):
        """The day the .vtt files land this stops being a skip and starts working."""
        if not any(has_subtitle(v, language) for v in all_videos()):
            pytest.skip(f"no {language.value} caption track on disk yet")
        assert requested("show me a video", language=language)


class TestTheTurnDoesNotOfferAShelfNobodyCanWatch:
    @staticmethod
    def _turn(locale: str, message: str):
        state = {"locale": locale, "active_agent": "learn_agent", "offered_video": None}
        return cards._open_video(state, message)

    def test_english_asking_for_any_video_gets_the_menu(self):
        out = self._turn("en", "show me a video")
        assert out and out["safety_flags"]["card"] == "video_menu"

    def test_english_naming_a_subject_opens_the_player(self):
        out = self._turn("en", "I want to watch a video about saving")
        assert out and out["safety_flags"]["card"] == "video"

    @pytest.mark.parametrize(
        "locale, message",
        [
            ("es", "quiero ver un video"),
            ("fr", "montre-moi une vidéo"),
            ("fr", "je veux voir une vidéo sur l'épargne"),
        ],
    )
    def test_a_reader_without_a_track_is_answered_normally(self, locale, message):
        """Not an apology, not a menu -- the turn simply carries on as a question."""
        if any(has_subtitle(v, Language(locale)) for v in all_videos()):
            pytest.skip(f"a {locale} caption track exists now; the menu is correct")
        assert self._turn(locale, message) is None

    def test_a_bad_locale_falls_back_to_english_rather_than_raising(self):
        state = {"locale": "zz", "active_agent": "learn_agent", "offered_video": None}
        out = cards._open_video(state, "show me a video")
        assert out and out["safety_flags"]["card"] == "video_menu"
