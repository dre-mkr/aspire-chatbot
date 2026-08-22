"""The request route only fires if `wants_video` lets it through first.

`ASPIRE_videos_and_persona_cards.patch` fixed the half everybody looks at:
`requested()` resolves a named subject to a film and an unnamed one to the
shelf, and it is not filtered by persona. Its tests exercise `requested()`
directly and all pass.

But `_open_video` calls `wants_video(message)` BEFORE it ever calls
`requested()`. So the gate decides, and the gate's regex required the media
noun to follow the article immediately:

    (?:watch|play|show|see) (me |us )?(the |that |this |a |an )?(video|story|...)

Which means "watch the scarcity video" -- the exact phrasing the patch's own
suite asserts on through the other door -- did not match, returned None, and
fell through to a model that cannot open a player. Naming what you wanted was
the one phrasing that failed.

Asking whether a video exists failed too. `_is_a_command` is a length check and
not a question test -- its docstring says so -- so "do you have a video" was
never blocked on being a question. The verb was simply missing from the list.

These tests run the two halves TOGETHER, because each half passing alone is
what let this through.
"""

from __future__ import annotations

import pytest

from app.graph.nodes.intents import wants_video
from app.videos import requested


def _reaches_a_player(message: str) -> bool:
    """Both gates, in the order `_open_video` applies them."""
    return bool(wants_video(message)) and bool(requested(message))


class TestNamingWhatYouWantReachesIt:
    """The regression: the subject sat between the article and the noun."""

    @pytest.mark.parametrize(
        "message",
        [
            "watch the scarcity video",
            "watch the saving story",
            "show me the scarcity film",
        ],
    )
    def test_a_subject_before_the_noun_still_reaches_a_player(self, message: str) -> None:
        assert _reaches_a_player(message), (
            "`requested()` resolves this correctly; if it fails here the gate in "
            "`wants_video` rejected it before `requested()` was ever called"
        )

    def test_a_subject_after_the_noun_was_always_fine(self) -> None:
        assert _reaches_a_player("show me the video about saving")


class TestAskingWhetherOneExistsIsAskingForIt:
    @pytest.mark.parametrize(
        "message",
        ["do you have a video", "are there any videos", "is there a story"],
    )
    def test_the_question_forms_reach_a_player(self, message: str) -> None:
        assert _reaches_a_player(message)


class TestAMentionIsStillNotARequest:
    """The gate has to keep saying no to these, or every transcript opens a player."""

    @pytest.mark.parametrize(
        "message",
        [
            "my teacher showed us a video yesterday",
            "i watched a video at school last week",
            "the video was about a boy",
            "teach me about saving",
            "i want to play a game",
        ],
    )
    def test_it_does_not_fire(self, message: str) -> None:
        assert not wants_video(message)
