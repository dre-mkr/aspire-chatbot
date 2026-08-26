"""One ordered answer to "does this message outrank what is running?"

Every activity in this graph used to keep its own idea of what counted as
leaving it -- the lesson had a question escape, the story knew three replies,
registration wanted a question mark -- and each was right about its own case
and blind to the others. These are the turns that proved it, from a live run.
"""

from __future__ import annotations

import pytest

from app.graph.nodes.intents import top_level_intent, wants_a_plan


class TestWhatOutranksAnActivity:
    @pytest.mark.parametrize(
        "message,expected",
        [
            # The plea that was graded as a wrong answer, in three languages.
            ("make it simpler", "simplify"),
            ("no entiendo", "simplify"),
            ("je ne comprends pas", "simplify"),
            # The game request that landed in the tutor.
            ("play a different game", "game"),
            ("juguemos", "game"),
            # A story asked for mid-anything.
            ("tell me a story", "story"),
            ("cuéntame un cuento", "story"),
            # The closing that came back with a phone number.
            ("thanks, that helps", "thanks"),
            ("gracias, eso ayuda", "thanks"),
            # The question that escaped once and was swallowed once.
            ("actually what is a sinking fund", "question"),
            ("wait how does compound interest work", "question"),
            ("¿cómo funciona el interés compuesto?", "question"),
        ],
    )
    def test_these_outrank_whatever_is_running(self, message, expected):
        assert top_level_intent(message) == expected

    @pytest.mark.parametrize(
        "message",
        [
            # A quiz answer.
            "Saving",
            "true",
            "I think a loan",
            # A tapped story choice.
            "Buy the rope (EC$30)",
            "Comprar el candado (EC$25)",
            # A slot answer.
            "I am 17",
            "Mother",
            "14/03/1985",
            "Basseterre",
            # Steering the story that is running -- an instruction, not a new intent.
            "make the character a fisherman from Sandy Point",
            "set it in Nevis instead",
        ],
    )
    def test_these_belong_to_whatever_is_running(self, message):
        """None is the safe default: it changes nothing."""
        assert top_level_intent(message) is None

    def test_order_is_the_design(self):
        """"I don't understand" is a question in form and a plea in substance."""
        assert top_level_intent("i don't understand") == "simplify"
        # And a story request is a question in form and a request in substance.
        assert top_level_intent("can I watch a story?") == "story"


class TestTheClosingIsNotAQuestion:
    @pytest.mark.parametrize(
        "message",
        ["thanks, that helps", "thanks that helps", "ok thanks",
         "thank you very much", "thanks. this is really helpful",
         "gracias, eso ayuda", "merci, ça aide"],
    )
    def test_a_closing_is_answered_conversationally(self, message):
        from app.agents.qa.nodes import _SMALL_TALK_RE
        from app.casual import casual_fold

        folded = casual_fold(message) or message
        assert any(pattern.match(folded) for _kind, pattern in _SMALL_TALK_RE), message

    def test_a_thank_you_with_a_question_after_it_is_still_a_question(self):
        """The anchoring is right and is not loosened -- only widened by a
        closed set of appreciations."""
        from app.agents.qa.nodes import _SMALL_TALK_RE
        from app.casual import casual_fold

        message = "thanks, but what about my brother?"
        folded = casual_fold(message) or message
        assert not any(pattern.match(folded) for _kind, pattern in _SMALL_TALK_RE)


class TestAStoryIsSteeredRatherThanDropped:
    def test_an_instruction_keeps_the_arc_and_carries_the_direction(self):
        from app.graph.nodes import cards

        state = {
            "story_arc": {"topic": "saving", "beat": 2, "wallet": 100},
            "locale": "en",
        }
        update = cards._story_turn(state, "make the character a fisherman from Sandy Point")
        assert update is not None
        arc = update.get("story_arc")
        assert arc is not None, "the story was dropped instead of steered"
        assert arc["beat"] == 3
        assert "fisherman" in arc["direction"]

    def test_a_new_intent_still_leaves_the_story(self):
        from app.graph.nodes import cards

        state = {"story_arc": {"topic": "saving", "beat": 2}, "locale": "en"}
        update = cards._story_turn(state, "actually what is compound interest")
        assert update == {"story_arc": None}

    def test_the_direction_reaches_the_model(self):
        from app.agents.qa.nodes import _story_instruction

        instruction = _story_instruction(
            {
                "story_topic": "saving",
                "persona": "orion",
                "story_arc": {"beat": 3, "topic": "saving", "direction": "a fisherman from Sandy Point"},
            }
        )
        assert "asked for the story to change" in instruction
        assert "fisherman from Sandy Point" in instruction

    def test_a_story_with_no_direction_is_unchanged(self):
        from app.agents.qa.nodes import _story_instruction

        instruction = _story_instruction(
            {"story_topic": "saving", "persona": "orion", "story_arc": {"beat": 2, "topic": "saving"}}
        )
        assert "asked for the story to change" not in instruction


class TestTheLessonYieldsToAPleaForPlainerWords:
    @staticmethod
    def _entry_with_concepts(monkeypatch, learning: dict, message: str) -> str:
        """`_entry` with a non-empty concept store.

        The store is empty under test and `_entry` short-circuits on that --
        which is correct behaviour and would have made these two assertions
        vacuous. One concept is enough: the claim under test reads the message
        and the lesson, never the store's contents.
        """
        from langchain_core.messages import HumanMessage

        from app.agents.learn import graph as learn_graph
        from app.learning import concepts

        class _OneConcept:
            def __len__(self) -> int:
                return 1

        # `_entry` imports `get_store` inside the function, so the module that
        # DEFINES it is the one to patch.
        monkeypatch.setattr(concepts, "get_store", lambda: _OneConcept())
        return learn_graph._entry(
            {
                "learning": learning,
                "messages": [HumanMessage(content=message)],
                "safety_flags": {},
            }
        )

    @pytest.mark.parametrize(
        "message", ["make it simpler", "no entiendo", "i don't understand"]
    )
    def test_the_entry_router_sends_confusion_to_reteach(self, monkeypatch, message):
        """The fix that could not work: `sounds_confused` is consulted inside
        the tutor node, and a reader mid-lesson never reaches the tutor. The
        matcher knew the words; the turn never reached the matcher."""
        assert (
            self._entry_with_concepts(
                monkeypatch, {"phase": "teaching", "lesson_id": "l01"}, message
            )
            == "reteach"
        )

    def test_without_a_lesson_open_it_is_not_a_reteach(self, monkeypatch):
        """"I don't understand" with nothing being taught is a question for the
        router, not a re-explanation of nothing."""
        assert (
            self._entry_with_concepts(monkeypatch, {"phase": "placing"}, "make it simpler")
            != "reteach"
        )

    def test_a_real_answer_still_goes_to_the_lesson(self, monkeypatch):
        """The precedence claim must not swallow the turns the lesson owns."""
        assert (
            self._entry_with_concepts(
                monkeypatch, {"phase": "teaching", "lesson_id": "l01"}, "Saving"
            )
            != "reteach"
        )


class TestAPlanIsNotAQuestion:
    """"How do I save up for a bike" asks for arithmetic, not for a corpus row."""

    @pytest.mark.parametrize(
        "message",
        [
            "how do i save up for a bike",
            "How can I save for a laptop?",
            "how do i afford a laptop",
            "how long will it take me to save for a bike",
            "i want to save up for a phone",
            "help me save for school shoes",
            "make me a savings plan",
            "como puedo ahorrar para una bicicleta",
        ],
    )
    def test_a_goal_of_their_own_reads_as_a_plan(self, message):
        assert top_level_intent(message) == "plan"

    @pytest.mark.parametrize(
        "message",
        [
            "how does saving work",
            "what is saving",
            "why should i save money",
            "what is compound interest",
            "how do i join ASPIRE",
            "how do i renew a fishing licence",
        ],
    )
    def test_a_question_about_saving_still_belongs_to_the_corpus(self, message):
        """The corpus answers these well. Only a goal the reader OWNS is a plan."""
        assert top_level_intent(message) != "plan"

    def test_the_goal_comes_back_so_the_plan_can_be_about_it(self):
        assert wants_a_plan("how do i save up for a bike") == "a bike"

    def test_a_plan_with_no_goal_named_is_still_a_plan(self):
        """An empty string and None are different answers: asked, but not said."""
        assert wants_a_plan("make me a savings plan") == ""
        assert wants_a_plan("what is compound interest") is None
