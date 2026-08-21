"""The catalog, and the judgement about when a video is worth offering.

The interesting tests here are the ones that assert NOTHING is offered. An
offer that fires on "can you save this chat for me" is worse than no feature:
it is the assistant proving it was pattern-matching rather than listening, in
the one place the client asked for the opposite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.domain import Language, Persona
from app.videos.catalog import (
    PUBLIC_DIR,
    all_videos,
    by_id,
    for_persona,
    relevant_to,
)
from app.videos.schemas import to_out

#: Where the files actually live. `parents[3]` is the repository root:
#: backend/tests/videos/this -> videos -> tests -> backend -> root.
_PUBLIC = Path(__file__).resolve().parents[3] / "frontend" / "public" / "videos"


class TestTheCatalogIsWellFormed:
    def test_there_are_videos_to_serve(self):
        """A catalog that is silently empty is a feature that silently does nothing."""
        assert all_videos()

    def test_every_id_is_unique(self):
        ids = [video.id for video in all_videos()]
        assert len(ids) == len(set(ids))

    def test_every_video_is_findable_by_its_id(self):
        for video in all_videos():
            assert by_id(video.id) is video

    def test_an_unknown_id_is_none_rather_than_an_error(self):
        """The id arrives from outside; a typo must not be a 500."""
        assert by_id("no-such-video") is None
        assert by_id("") is None

    @pytest.mark.parametrize("video", all_videos(), ids=lambda v: v.id)
    def test_no_term_is_claimed_as_both_strong_and_supporting(self, video):
        assert not (set(video.strong) & set(video.supporting))

    @pytest.mark.parametrize("video", all_videos(), ids=lambda v: v.id)
    def test_the_offer_is_a_question(self, video):
        """It is an offer. A reader has to be able to say no to it."""
        assert video.offer.strip().endswith("?")

    @pytest.mark.parametrize("video", all_videos(), ids=lambda v: v.id)
    def test_the_source_is_a_path_on_our_own_origin(self, video):
        src = to_out(video).src
        assert src.startswith(f"{PUBLIC_DIR}/")
        assert "://" not in src


class TestTheFilesExist:
    """A catalog entry naming a file nobody shipped is a broken player.

    These read the real directory rather than a fixture: the failure being
    guarded against is somebody renaming an mp4, and a fixture would not see it.
    """

    @pytest.mark.parametrize("video", all_videos(), ids=lambda v: v.id)
    def test_the_file_named_is_the_file_present(self, video):
        assert (_PUBLIC / video.filename).is_file(), (
            f"{video.filename} is in the catalog but not in {_PUBLIC}. "
            "If this is a fresh clone, run `git lfs pull`."
        )

    @pytest.mark.parametrize("video", all_videos(), ids=lambda v: v.id)
    def test_the_file_is_video_and_not_an_lfs_pointer(self, video):
        """A clone without git-lfs leaves a 130-byte text file in its place."""
        path = _PUBLIC / video.filename
        head = path.read_bytes()[:64]
        assert not head.startswith(b"version https://git-lfs"), (
            f"{video.filename} is an LFS pointer, not video. Run `git lfs pull`."
        )
        # `ftyp` is the first box of every MP4.
        assert b"ftyp" in head, f"{video.filename} does not look like an MP4"


class TestWhoMayBeOfferedOne:
    def test_the_children_and_teen_personas_are_offered_both(self):
        for persona in (Persona.STELLA, Persona.ORION, Persona.GUEST):
            assert len(for_persona(persona)) == len(all_videos())

    def test_guardians_and_teachers_are_offered_none_unasked(self):
        """They browse the panel instead; an animated story is not their answer."""
        for persona in (Persona.AURORA, Persona.NOVA):
            assert for_persona(persona) == ()

    def test_no_persona_at_all_sees_everything(self):
        assert for_persona(None) == all_videos()

    def test_a_guardian_is_never_offered_a_video_however_relevant(self):
        assert relevant_to("what does scarcity mean?", persona=Persona.AURORA) is None


class TestWhenAVideoIsWorthOffering:
    @pytest.mark.parametrize(
        "question, expected",
        [
            # The client's own two examples.
            ("What does scarcity mean?", "captain-careful-scarcity"),
            ("How can I start saving money?", "monique-saving-adventure"),
            # One strong term settles it.
            ("how do we conserve water", "captain-careful-scarcity"),
            ("what is an allowance", "monique-saving-adventure"),
            # Two supporting terms settle it.
            (
                "what is the difference between a need and a want",
                "captain-careful-scarcity",
            ),
            ("how do I set a goal and earn the money", "monique-saving-adventure"),
        ],
    )
    def test_a_relevant_question_finds_its_video(self, question, expected):
        found = relevant_to(question, persona=Persona.STELLA)
        assert found is not None and found.id == expected

    @pytest.mark.parametrize(
        "question",
        [
            # One ordinary word, used in its ordinary sense. This is the whole
            # reason for the two-tier table.
            "can you save this chat for me?",
            "I want a coffee",
            "can you share that again",
            # On topic for ASPIRE, not for either story.
            "who do I contact about my application",
            "am I eligible for ASPIRE",
            "what is the Eastern Caribbean Central Bank",
            # Nothing at all.
            "",
            "hello",
        ],
    )
    def test_an_unrelated_question_is_offered_nothing(self, question):
        assert relevant_to(question, persona=Persona.STELLA) is None

    def test_a_question_matching_both_equally_is_offered_neither(self):
        """Two stories fitting equally means the reader asked about money in general.

        Two supporting terms each, so both clear the bar and neither wins.
        Picking one here would be a coin toss presented as a recommendation.
        """
        both = "what are needs and wants, and should I save or spend"
        assert relevant_to(both, persona=Persona.STELLA) is None

    def test_only_english_is_offered_while_only_english_exists(self):
        """Both files are English. Offering one in Spanish is offering a wall."""
        for language in (Language.ES, Language.FR):
            assert (
                relevant_to("what does scarcity mean?", persona=Persona.STELLA, language=language)
                is None
            )

    def test_case_and_punctuation_do_not_hide_a_match(self):
        for phrasing in ("SCARCITY, what is it?", "scarcity!", "  Scarcity  "):
            found = relevant_to(phrasing, persona=Persona.STELLA)
            assert found is not None and found.id == "captain-careful-scarcity", phrasing

    def test_a_term_inside_a_longer_word_is_not_a_match(self):
        """Whole words only. `scarcity` must not fire on `scarcities-adjacent`."""
        assert relevant_to("unsaveable wanton", persona=Persona.STELLA) is None

    def test_a_number_is_never_a_keyword(self):
        assert relevant_to("EC$100 500 2026", persona=Persona.STELLA) is None
