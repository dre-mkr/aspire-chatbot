"""A story that goes on until the reader says enough."""

from __future__ import annotations

import pytest

from app.agents.qa.nodes import _STORY_ENDED, _STORY_FOLLOW_UPS, _story_instruction, follow_up_chips
from app.graph.nodes import cards
from app.graph.nodes.cards import STORY_BEATS, story_continues, story_ends, story_reflects
from app.graph.nodes.intents import wants_story

LOCALES = ("en", "es", "fr")


def _state(**over):
    base = {"locale": "en", "persona": "kaleb", "age_band": "9-12"}
    base.update(over)
    return base


class TestTheArcOpensAndAdvances:
    def test_a_told_story_opens_the_arc_at_beat_one(self):
        state = _state(awaiting_story_topic=True)
        update = cards._story_turn(state, "saving for a bike")
        assert update["story_arc"] == {
            "topic": "saving for a bike",
            "beat": 1,
            # The adventure state, seeded at the door: the reader plays the
            # story with EC$100 of story-money and an empty satchel.
            "wallet": 100,
            "inventory": [],
        }
        assert update["story_topic"] == "saving for a bike"

    def test_what_happens_next_advances_the_beat(self):
        state = _state(story_arc={"topic": "a bike", "beat": 1})
        update = cards._story_turn(state, "What happens next?")
        assert update["story_arc"]["beat"] == 2
        # `hydrate` clears `story_topic` every turn, so it is put back here or
        # the next beat is written with no subject.
        assert update["story_topic"] == "a bike"

    def test_the_beat_keeps_climbing(self):
        beat = 1
        for _ in range(3):
            update = cards._story_turn(
                _state(story_arc={"topic": "a bike", "beat": beat}), "keep going"
            )
            beat = update["story_arc"]["beat"]
        assert beat == 4

    def test_advancing_is_not_a_card_so_an_agent_writes_it(self):
        """No `card` flag: `_after_cards` sends this to the router, not to output."""
        update = cards._story_turn(_state(story_arc={"topic": "a bike", "beat": 2}), "more")
        assert "card" not in (update.get("safety_flags") or {})
        assert "messages" not in update


class TestTheWordsOfThreeLanguages:
    """The regexes carry three languages, and two words were traps.

    Spanish `para` is the everyday preposition "for"; French `pas encore` is
    "not yet". Both used to match as commands -- one ended the story a child
    was in the middle of playing, the other turned the page they had just
    said they were not ready for.
    """

    def test_the_spanish_preposition_para_does_not_end_a_story(self):
        assert not story_ends("quiero ahorrar para la bici")
        assert not story_ends("es para mi hermana")

    @pytest.mark.parametrize("phrase", ["para ya", "ya basta", "basta", "detente", "no más"])
    def test_spanish_stopping_phrases_still_stop(self, phrase):
        assert story_ends(phrase)

    def test_pas_encore_is_not_a_request_for_more(self):
        assert not story_continues("pas encore")
        assert not story_continues("non, pas encore fini")

    def test_encore_alone_still_turns_the_page(self):
        assert story_continues("encore !")
        assert story_continues("la suite")

    def test_a_spanish_preference_with_mas_is_not_a_page_turn(self):
        assert not story_continues("me gusta más la bicicleta roja")

    @pytest.mark.parametrize("phrase", ["más", "más!", "cuéntame más", "quiero más", "qué pasa después"])
    def test_asking_for_more_in_spanish_still_works(self, phrase):
        assert story_continues(phrase)


class TestTheReaderEndsIt:
    @pytest.mark.parametrize("locale", LOCALES)
    def test_enough_closes_the_arc(self, locale):
        state = _state(locale=locale, story_arc={"topic": "a bike", "beat": 3})
        enough = _STORY_FOLLOW_UPS[locale][2]
        update = cards._story_turn(state, enough)
        assert update["story_arc"] is None
        assert update["safety_flags"]["card"] == "story_closed"

    def test_no_more_ends_rather_than_continues(self):
        """"no more" contains "more" and means the opposite of it."""
        assert story_ends("no more")
        assert not story_continues("no more")

    def test_a_change_of_subject_drops_the_arc_quietly(self):
        update = cards._story_turn(
            _state(story_arc={"topic": "a bike", "beat": 2}), "what is compound interest"
        )
        assert update == {"story_arc": None}

    def test_thinking_about_it_is_not_leaving_it(self):
        update = cards._story_turn(
            _state(story_arc={"topic": "a bike", "beat": 2}), "What would you do?"
        )
        assert update == {}, "the arc must survive a reflection, unchanged"


class TestItHasToLand:
    def test_the_middle_carries_the_same_story_on(self):
        text = _story_instruction(
            _state(story_topic="a bike", story_arc={"topic": "a bike", "beat": 3})
        )
        assert "part 3" in text
        assert "same character" in text

    def test_the_last_beat_is_told_to_finish(self):
        text = _story_instruction(
            _state(story_topic="a bike", story_arc={"topic": "a bike", "beat": STORY_BEATS})
        )
        assert "LAST part" in text
        assert "Do not leave it open" in text

    def test_the_opening_beat_gets_no_continuation_line(self):
        text = _story_instruction(
            _state(story_topic="a bike", story_arc={"topic": "a bike", "beat": 1})
        )
        assert "part" not in text.lower().split("participant")[0].replace("apart", "")

    @pytest.mark.parametrize("locale", LOCALES)
    def test_the_last_beat_stops_offering_what_happens_next(self, locale):
        chips = follow_up_chips(
            _state(locale=locale, story_topic="a bike", story_arc={"beat": STORY_BEATS}),
            [],
            set(),
        )
        assert chips == _STORY_ENDED[locale]
        assert not any(story_continues(chip) for chip in chips)


class TestEveryChipRoutesSomewhere:
    """A chip that reads well and routes nowhere is worse than no chip."""

    @pytest.mark.parametrize("locale", LOCALES)
    def test_the_mid_arc_chips(self, locale):
        nxt, reflect, enough = _STORY_FOLLOW_UPS[locale]
        assert story_continues(nxt)
        assert story_reflects(reflect)
        assert story_ends(enough)

    @pytest.mark.parametrize("locale", LOCALES)
    def test_the_closing_chips(self, locale):
        another, reflect = _STORY_ENDED[locale]
        assert wants_story(another), "the chip must actually start a new story"
        assert story_reflects(reflect)


class TestTheArcSurvivesTheTurn:
    def test_hydrate_does_not_clear_it(self):
        """`story_topic` is cleared every turn; the arc is what outlives that."""
        import inspect

        from app.graph.nodes import hydrate

        source = inspect.getsource(hydrate)
        assert 'update["story_topic"] = None' in source
        assert 'update["story_arc"] = None' not in source, (
            "clearing the arc in hydrate removes the second page of every story"
        )


class TestAStoryMayNameWhatItTeaches:
    """Storytelling is teaching, and the vocabulary ladder has to know it."""

    STORY = {"active_agent": "qa_agent", "story_topic": "borrowing", "age_band": "9-12"}

    def test_a_story_counts_as_teaching(self):
        from app.graph.nodes.safety_out import is_a_lesson, teaches

        assert teaches(self.STORY)
        assert not is_a_lesson(self.STORY), (
            "still not a lesson AGENT -- `teaches` is the wider question"
        )

    def test_a_plain_answer_still_does_not(self):
        from app.graph.nodes.safety_out import teaches

        assert not teaches({"active_agent": "qa_agent", "age_band": "9-12"})

    def test_loan_is_barred_below_thirteen_without_the_lift(self):
        from app.safety import vocab

        assert vocab.check("loan", "9-12")

    def test_and_allowed_inside_one(self):
        """A story about borrowing may say the word it is about."""
        from app.safety import vocab

        assert not vocab.check("loan", "9-12", teaching_scope=True)

    def test_the_absolute_ban_is_not_lifted_by_a_story(self):
        """`_GENERAL_BAN` holds whatever the turn is. The lift is not a licence."""
        from app.safety import vocab

        for term in sorted(vocab._GENERAL_BAN)[:6]:
            assert vocab.check(term, "9-12", teaching_scope=True), (
                f"{term!r} is banned outright and a story must not unlock it"
            )


class TestTheLiftCoversEveryWayThisProductTeaches:
    """Storytelling, learning, games, activities, ASPIRE and videos."""

    import pytest as _pytest

    TEACHING = {
        "a lesson": {"active_agent": "learn_agent"},
        "a story": {"active_agent": "qa_agent", "story_topic": "borrowing"},
        "a story still running": {"active_agent": "qa_agent", "story_arc": {"beat": 2}},
        "a game": {"active_agent": "qa_agent", "safety_flags": {"card": "game"}},
        "a video": {"active_agent": "qa_agent", "safety_flags": {"card": "video"}},
        "the video menu": {"active_agent": "qa_agent", "safety_flags": {"card": "video_menu"}},
        "a video offered": {"active_agent": "qa_agent", "offered_video": "monique"},
    }

    NOT_TEACHING = {
        "a plain answer": {"active_agent": "qa_agent"},
        "the signup card": {"active_agent": "qa_agent", "safety_flags": {"card": "signup"}},
        "the eligibility card": {
            "active_agent": "qa_agent",
            "safety_flags": {"card": "eligibility"},
        },
    }

    @_pytest.mark.parametrize("name", sorted(TEACHING))
    def test_these_teach(self, name):
        from app.graph.nodes.safety_out import teaches

        assert teaches(self.TEACHING[name]), f"{name} is teaching and must lift the ladder"

    @_pytest.mark.parametrize("name", sorted(NOT_TEACHING))
    def test_these_do_not(self, name):
        from app.graph.nodes.safety_out import teaches

        assert not teaches(self.NOT_TEACHING[name])

    def test_a_programme_question_lifts_it_too(self):
        """ASPIRE is made of interest and credit; a question about it may say so."""
        from app.graph.nodes.safety_out import about_the_programme

        assert about_the_programme(
            {"messages": [type("M", (), {"type": "human", "content": "what is aspire"})()]}
        )

    def test_the_lifted_set_is_teaching_terms_not_everything(self):
        from app.safety import vocab

        assert "loan" in vocab.TEACHING_TERMS
        assert vocab.PROGRAMME_TERMS < vocab.TEACHING_TERMS
        # And the absolute ban is outside it entirely.
        assert not (vocab.TEACHING_TERMS & set(vocab._GENERAL_BAN))
