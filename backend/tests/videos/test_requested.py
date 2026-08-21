"""A reader who ASKS for a video gets one, whoever they are.

The defect these pin is measured, not theoretical: a reader asked for a video
six times across one conversation and got it once -- on the single turn where
an offer happened to be standing. `_WATCH` matched every one of those six
messages. `_open_video` returned None for five of them because
`state["offered_video"]` was empty, and the request fell through to a model,
which cannot open a player.

The second half is who it fails hardest. Imani and Azuri are excluded from
`video.personas`, so they are never OFFERED one -- which, combined with the
above, meant they could not reach a video in conversation at all. They could
only find the Videos panel unaided. The reader that costs most is the parent
who reads with difficulty: the videos are the one thing here that is not text,
and she is the least likely of anyone to go hunting a panel for them.
"""

from __future__ import annotations

import pytest

from app.domain import Language, Persona
from app.videos import for_persona, relevant_to, requested


class TestAnExplicitRequestIsNotFilteredByPersona:
    """`for_persona` governs what is PUSHED. It says nothing about a request."""

    @pytest.mark.parametrize("persona", list(Persona))
    def test_every_persona_can_ask_for_a_video(self, persona: Persona) -> None:
        assert requested("show me a video")

    @pytest.mark.parametrize("persona", [Persona.AURORA, Persona.NOVA])
    def test_the_adults_are_still_never_offered_one_unprompted(
        self, persona: Persona
    ) -> None:
        """The gate that matters stays exactly where it was."""
        assert for_persona(persona) == ()

    def test_a_parents_eligibility_question_does_not_summon_a_cartoon(self) -> None:
        """Why the adults are not simply added to `video.personas`.

        `relevant_to` runs from `safety_out` on every turn. Opening the gate
        there would append a children's animated story to an answer about
        opening an account -- which is the "reads as not listening" failure the
        catalog's own comment warns about.
        """
        question = "Can my son open a savings account and how does he save money?"
        assert relevant_to(question, persona=Persona.STELLA) is not None
        assert relevant_to(question, persona=Persona.AURORA) is None


class TestWhatARequestResolvesTo:
    def test_a_named_subject_returns_exactly_that_video(self) -> None:
        assert [v.id for v in requested("show me the video about saving")] == [
            "monique-saving-adventure"
        ]
        assert [v.id for v in requested("watch the scarcity video")] == [
            "captain-careful-scarcity"
        ]

    def test_a_request_with_no_subject_returns_the_whole_shelf(self) -> None:
        """"Show me a video" is a request for the library, not for one of them.

        The caller offers the choice. Picking one here would be a guess wearing
        an answer's clothes.
        """
        assert len(requested("show me a video")) == 2

    def test_request_grammar_is_not_a_subject(self) -> None:
        """The bug this function was rewritten for.

        "I want to watch a video" scored the scarcity film on `want` alone --
        an ordinary English verb that is also a supporting term. A reader
        asking for ANYTHING was handed one particular thing.
        """
        assert len(requested("i want to watch a video")) == 2
        assert len(requested("can I see a video please")) == 2

    def test_nothing_is_offered_outside_english(self) -> None:
        """Both files are English. An English cartoon is not a Spanish answer."""
        assert requested("muestrame un video", language=Language.ES) == ()
        assert requested("montre moi une video", language=Language.FR) == ()
