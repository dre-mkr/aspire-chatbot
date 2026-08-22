"""A non-English reader was never offered a video at all.

WHAT WAS WRONG
    `relevant_to` opened with `if language is not Language.EN: return None`. That
    was the right call while nothing was captioned -- an English soundtrack is
    not an answer for a French reader. Its cost was the failure mode: the feature
    did not degrade for them, it DISAPPEARED. No offer, no explanation, nothing
    for anyone to notice, in the one part of the product the client asks about
    most.

WHAT IT DOES NOW
    The gate is tied to the ASSET, not to the locale. A video is offered in
    Spanish or French when a caption track for that locale is ON DISK. Declaring
    one in the catalog is a commission; `has_subtitle` checks the file. So the
    offer stays shut today and opens by itself the day the tracks land, with no
    second code change and no one having to remember.
"""

from __future__ import annotations

import pytest

from app.domain import Language, Persona
from app.graph.nodes.intents import wants_video
from app.videos import catalog
from app.videos.catalog import (
    _VIDEOS,
    chip_for,
    has_subtitle,
    offer_line,
    relevant_to,
    subtitle_filename,
)

SCARCITY = "What does scarcity mean?"


@pytest.fixture
def _no_track_cache():
    """`_track_on_disk` is cached, and these tests move files under it."""
    catalog._track_on_disk.cache_clear()
    yield
    catalog._track_on_disk.cache_clear()


class TestEnglishIsUnchanged:
    def test_the_english_offer_still_works(self):
        video = relevant_to(SCARCITY, persona=Persona.STELLA, language=Language.EN)
        assert video is not None and video.id == "captain-careful-scarcity"

    def test_english_needs_no_track_because_it_is_the_soundtrack(self):
        assert has_subtitle(_VIDEOS[0], Language.EN) is True


class TestTheGateIsTiedToTheAssetNotTheLocale:
    @pytest.mark.parametrize("language", [Language.ES, Language.FR])
    def test_no_track_on_disk_means_no_offer(self, language, _no_track_cache):
        """Today's state, and it must stay honest rather than optimistic."""
        assert relevant_to(SCARCITY, persona=Persona.STELLA, language=language) is None

    @pytest.mark.parametrize("language", [Language.ES, Language.FR])
    def test_the_offer_opens_when_the_track_lands(
        self, language, tmp_path, monkeypatch, _no_track_cache
    ):
        """The whole point: no second code change on the day the file arrives."""
        video = _VIDEOS[0]
        monkeypatch.setattr(catalog, "_ASSET_ROOT", tmp_path)
        (tmp_path / subtitle_filename(video, language)).write_text(
            "WEBVTT\n\n00:00.000 --> 00:02.000\n...\n", encoding="utf-8"
        )
        catalog._track_on_disk.cache_clear()

        found = relevant_to(SCARCITY, persona=Persona.STELLA, language=language)
        assert found is not None and found.id == video.id

    def test_a_declared_track_is_a_commission_not_a_delivery(self, _no_track_cache):
        """Every video declares ES and FR. None of them has the file yet."""
        declared = [
            (v.id, lang.value) for v in _VIDEOS for lang in v.subtitles
        ]
        assert declared, "the catalog no longer declares any caption track"
        assert not any(has_subtitle(v, lang) for v in _VIDEOS for lang in v.subtitles), (
            "a track is on disk now -- good. Delete this assertion and let "
            "test_the_offer_opens_when_the_track_lands carry the behaviour."
        )


class TestTheChipItSendsIsAChipItAccepts:
    """The chip's text is also what gets SENT when it is tapped."""

    @pytest.mark.parametrize("language", list(Language))
    @pytest.mark.parametrize("video", _VIDEOS, ids=lambda v: v.id)
    def test_every_chip_is_recognised_by_wants_video(self, video, language):
        chip = chip_for(video, language)
        assert wants_video(chip), (
            f"{language.value}: the chip {chip!r} would be offered and then open "
            f"nothing when tapped, because `intents._WATCH` does not match it."
        )

    @pytest.mark.parametrize("language", [Language.ES, Language.FR])
    def test_the_chip_is_not_left_in_english(self, language):
        for video in _VIDEOS:
            assert chip_for(video, language) != chip_for(video, Language.EN)

    @pytest.mark.parametrize("language", [Language.ES, Language.FR])
    def test_the_long_offer_line_is_translated_too(self, language):
        for video in _VIDEOS:
            assert offer_line(video, language) != video.offer


class TestTheFilenameConventionIsDerivedNotTyped:
    def test_one_convention_for_every_track(self):
        video = _VIDEOS[0]
        assert subtitle_filename(video, Language.FR) == (
            "captain-careful-and-the-quest-for-scarcity.fr.vtt"
        )

    def test_the_stem_follows_the_film(self):
        """Rename a film and its tracks follow, because nothing is hand-typed."""
        for video in _VIDEOS:
            stem = video.filename.rsplit(".", 1)[0]
            for language in video.subtitles:
                assert subtitle_filename(video, language).startswith(stem + ".")
