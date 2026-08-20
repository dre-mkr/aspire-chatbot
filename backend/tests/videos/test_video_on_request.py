"""Asking for a video, which until now was a thing nobody could do.

Every test in this file is written from one transcript. A reader asked for a
video six times and got one once, and the time it worked they had typed the word
"scarcity" -- so it was matched on the TOPIC by the volunteering path, not on the
request by anything, because nothing was looking for the request.

The four replies in between are what makes it worth a file of its own. Two were
hint rungs on a question about a coin, spent on messages that were not attempts
at it. One was the end-of-session wrap. One was a generic assistant musing that
"Monique's Saving Adventure" sounded like a fun story title -- while that video
sat in the catalog, two functions away, with that exact title.
"""

from __future__ import annotations

import pytest

from app.graph.nodes.cards import _open_video
from app.graph.nodes.intents import asks_for_a_video, wants_story, wants_video
from app.videos.catalog import all_videos, relevant_to, requested


def _state(**overrides):
    base = {
        "persona": "stella",
        "locale": "en",
        "safety_flags": {},
        "offered_video": None,
        "active_agent": "learn_agent",
    }
    return {**base, **overrides}


def _played(card) -> str | None:
    """The video id this card opens, or None if it opened no player."""
    if not card:
        return None
    for directive in card.get("ui_directives") or ():
        if directive.get("t") == "video":
            return str(directive["video_id"])
    return None


#: The reader's six messages, in the order they were sent.
TRANSCRIPT = (
    "Watch the ASPIRE video about saving and goals",
    "Watch the ASPIRE video about saving and goals",
    "Do you have videos?",
    "I want to watch a video",
    "Video",
    "Watch the ASPIRE video about scarcity",
)


class TestTheTranscript:
    @pytest.mark.parametrize("message", TRANSCRIPT)
    def test_every_one_of_the_six_is_recognised_as_a_request(self, message):
        assert asks_for_a_video(message), message

    @pytest.mark.parametrize("message", TRANSCRIPT)
    def test_every_one_of_the_six_is_answered_here(self, message):
        """A card, so the turn stops before `classify` and before the tutor.

        This is the assertion that closes all three faults at once. `_after_cards`
        sends a card straight to `safety_out`, so the turn never reaches
        `apply_stickiness` and the tutor is never asked to grade "Video" as an
        answer to a question about a coin.
        """
        card = _open_video(_state(), message)
        assert card is not None, message
        assert card["safety_flags"]["card"] in ("video", "video_menu"), message

    def test_the_first_message_plays_the_video_it_names(self):
        """It named the topic in so many words. Twice."""
        assert (
            _played(_open_video(_state(), TRANSCRIPT[0])) == "monique-saving-adventure"
        )

    def test_the_last_message_still_works(self):
        """The one that used to be the only one that worked. Regression guard."""
        assert (
            _played(_open_video(_state(), TRANSCRIPT[5])) == "captain-careful-scarcity"
        )

    @pytest.mark.parametrize("message", ("Do you have videos?", "Video"))
    def test_a_request_that_names_no_topic_gets_the_menu_not_silence(self, message):
        """Nothing to match on is not nothing to say.

        `relevant_to` returns None here and is right to: it is deciding whether
        to interrupt an answer about something else. Once the reader has asked,
        None is the wrong shape of answer entirely.
        """
        assert relevant_to(message) is None, "premise of this test has changed"

        card = _open_video(_state(), message)
        assert card["safety_flags"]["card"] == "video_menu"
        assert len(card["quick_replies"]) == len(all_videos())

    def test_the_menu_chips_come_back_and_resolve(self):
        """A chip is also what gets SENT. It has to survive the round trip.

        This is the seam the offer feature nearly died in once already -- a chip
        phrased as a lovely full question arrives as an eleven-word message,
        fails the command-length gate, and opens nothing.
        """
        menu = _open_video(_state(), "Do you have videos?")
        for chip in menu["quick_replies"]:
            assert asks_for_a_video(chip), chip
            assert _played(_open_video(_state(), chip)) is not None, chip


class TestAskingVersusAccepting:
    def test_accepting_an_offer_still_plays_the_offered_one(self):
        state = _state(offered_video="captain-careful-scarcity")
        card = _open_video(state, "Watch the ASPIRE video about scarcity")
        assert _played(card) == "captain-careful-scarcity"
        assert card["offered_video"] is None

    def test_naming_a_different_video_beats_the_one_on_the_table(self):
        """"Show me the saving video" accepts an offer by the letter of
        `wants_video`. Playing the scarcity film because that is what was
        offered is the same not-listening this node exists to stop.
        """
        state = _state(offered_video="captain-careful-scarcity")
        card = _open_video(state, "Watch the ASPIRE video about saving and goals")
        assert _played(card) == "monique-saving-adventure"

    def test_a_dead_offer_does_not_swallow_a_live_request(self):
        """A stale id must expire the offer without eating the ask with it."""
        state = _state(offered_video="a-video-that-was-removed")
        card = _open_video(state, "I want to watch a video")
        assert card["safety_flags"]["card"] == "video_menu"

    def test_changing_the_subject_still_expires_the_offer(self):
        state = _state(offered_video="captain-careful-scarcity")
        card = _open_video(state, "who do I contact about my application")
        assert card == {"offered_video": None}

    def test_an_ordinary_question_is_not_a_video_request(self):
        assert _open_video(_state(), "what does scarcity mean") is None


class TestWhatMustNotChange:
    @pytest.mark.parametrize(
        "message",
        (
            "tell me a story",
            "can you tell me a story",
            "story time",
            "give me a story",
        ),
    )
    def test_a_story_request_is_still_a_story(self, message):
        """The story flow writes prose, which is what was asked for.

        `_open_video` runs before `_story_turn` in the gate, so a video matcher
        that claimed the word "story" would quietly delete the story feature.
        """
        assert wants_story(message), message
        assert not asks_for_a_video(message), message
        assert _open_video(_state(), message) is None, message

    @pytest.mark.parametrize(
        "message",
        (
            "can you save this chat for me",
            "I want to share my screen",
            "how do I record my answers",
            "what is a need",
            "do you have any games",
        ),
    )
    def test_ordinary_messages_do_not_open_a_player(self, message):
        assert not asks_for_a_video(message), message

    def test_wants_video_is_left_alone(self):
        """The acceptance matcher stays narrow. Different job, worse failure.

        A false positive in `wants_video` opens a player on top of whatever the
        reader was agreeing to. A false positive in `asks_for_a_video` shows a
        menu of two videos to somebody who did not want one. Those are not the
        same cost and they should not share a threshold.
        """
        assert not wants_video("yes")
        assert not wants_video("ok")
        assert wants_video("Watch the ASPIRE video about scarcity")


class TestTheTwoBarsAreDifferentOnPurpose:
    def test_volunteering_needs_two_hits_and_asking_needs_one(self):
        """One ordinary word is not evidence you want a film about pocket money.

        It is perfectly good evidence of WHICH film, once you have said you want
        one. Same word, two questions, two answers -- and the whole fix is
        noticing they were being asked the same question.
        """
        assert relevant_to("can you save this") is None
        assert requested("the saving one")[0].id == "monique-saving-adventure"

    def test_a_tie_is_a_choice_rather_than_a_refusal(self):
        """One word each. `relevant_to` gives up; asking gets both on screen."""
        assert len(requested("show me a video about sharing a goal")) == 2
        assert relevant_to("share a goal") is None

    @pytest.mark.parametrize(
        "message",
        ("I want to watch a video", "Do you have videos?", "show me a film"),
    )
    def test_the_words_of_the_request_are_not_read_as_its_subject(self, message):
        """The trap this function walks into, pinned so it stays shut.

        "I want to watch a video" contains `want`, a supporting term for the
        scarcity film. A reader who named no subject at all was being handed a
        story about needs and wants -- matched on the grammar of their request
        rather than on anything they said. Found by a test, not in review.
        """
        assert requested(message) == ()

    def test_but_a_named_subject_survives_the_stripping(self):
        """`want` is scaffolding in "want to" and a topic in "needs and wants"."""
        assert requested("the needs and wants video")[0].id == "captain-careful-scarcity"

    def test_an_explicit_request_is_not_filtered_by_persona(self):
        """A teacher asking for the Captain Careful film is the client's own
        best demonstration of this product, and the offer filter refuses it.

        `for_persona` gates what a reader may be OFFERED, on the correct
        reasoning that a guardian asking about eligibility is not the audience
        for an animated story. Somebody who typed "show me the video" is not
        being offered anything. They are browsing, and browsing has never been
        filtered.
        """
        from app.domain import Persona

        teacher = Persona("nova") if "nova" in Persona._value2member_map_ else None
        if teacher is not None:
            assert relevant_to("scarcity", persona=teacher) is None
        assert requested("scarcity")[0].id == "captain-careful-scarcity"
