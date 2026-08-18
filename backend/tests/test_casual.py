"""Reading a message the way it was meant.

The model has never had trouble with a typo. The deterministic gates in front of
it did: `_small_talk_reply` matches an anchored closed list, so "hello" was
answered conversationally while "helo", "hiiiiii" and "yo" fell through into
retrieval, where a greeting matches nothing and comes back as a decline.

The two properties that matter are opposite in direction, and both are tested
here: casual spellings must REACH the closed list, and real questions must NOT
be captured by it just because they open with a greeting.
"""

from __future__ import annotations

import pytest

from app.casual import casual_fold, squeeze_runs, strip_filler


class TestSqueezingRepeatedLetters:
    @pytest.mark.parametrize(
        ("typed", "meant"),
        [
            ("hiiiiii", "hi"),
            ("heyyyy", "hey"),
            ("sooooo", "so"),
            ("helloooo", "hello"),
            ("yesss", "yes"),
            ("noooo", "no"),
        ],
    )
    def test_a_run_of_three_or_more_collapses(self, typed, meant):
        assert squeeze_runs(typed) == meant

    @pytest.mark.parametrize(
        "word",
        ["hello", "spell", "coffee", "little", "arriba", "appelle", "occurred", "aa"],
    )
    def test_ordinary_double_letters_are_left_alone(self, word):
        """A double letter is spelling. Only a triple is typing."""
        assert squeeze_runs(word) == word


class TestFiller:
    def test_trailing_laughter_is_dropped(self):
        assert strip_filler("what even is aspire lol") == "what even is aspire"

    def test_leading_filler_is_dropped(self):
        assert strip_filler("bruh what is aspire") == "what is aspire"

    def test_filler_inside_a_sentence_is_kept(self):
        """Mid-sentence it is content, and removing it would rewrite the message."""
        assert strip_filler("i said lol and she left") == "i said lol and she left"


class TestCasualFold:
    @pytest.mark.parametrize(
        ("typed", "meant"),
        [
            ("helo", "hello"),
            ("hiiiiii", "hi"),
            ("yo", "hi"),
            ("hiya", "hi"),
            ("sup", "hello"),
            ("thx", "thanks"),
            ("tysm", "thanks"),
            ("kk", "ok"),
            ("nah", "no"),
            ("cya", "bye"),
            ("siiign me up", "sign me up"),
        ],
    )
    def test_everyday_spellings_reach_their_canonical_word(self, typed, meant):
        assert casual_fold(typed) == meant

    @pytest.mark.parametrize("text", ["hola", "buenos días", "bonjour", "merci", "adiós"])
    def test_spanish_and_french_are_untouched(self, text):
        """Accents survive: stripping them here would be a language change."""
        assert casual_fold(text) == text

    def test_a_question_that_opens_with_slang_stays_a_question(self):
        """The whole point. "yo what is aspire" must not become a bare greeting."""
        assert casual_fold("yo what is aspire") == "hi what is aspire"

    def test_a_whole_token_is_required(self):
        """"yo" maps to a greeting; "yoghurt" is a word."""
        assert casual_fold("yoghurt") == "yoghurt"

    def test_empty_input_is_empty(self):
        assert casual_fold("") == ""
        assert casual_fold("   ") == ""


class TestTheSmallTalkGateReadsThem:
    """The join: `casual_fold` is only useful if the closed list sees its output."""

    def _reply(self, text: str) -> str | None:
        from langchain_core.messages import HumanMessage

        from app.agents.qa.nodes import _small_talk_reply

        command = _small_talk_reply(
            {"messages": [HumanMessage(content=text)], "locale": "en"}
        )
        if command is None:
            return None
        return str(command.update["messages"][0].content)

    @pytest.mark.parametrize(
        "greeting", ["hello", "helo", "hiiiiii", "yo", "hiya", "sup", "hey!"]
    )
    def test_a_casual_greeting_is_answered_conversationally(self, greeting):
        reply = self._reply(greeting)
        assert reply is not None, f"{greeting!r} fell through to retrieval"
        assert "ASPIRE" in reply

    @pytest.mark.parametrize("thanks", ["thanks", "thx", "tysm", "thank you"])
    def test_casual_thanks_too(self, thanks):
        assert self._reply(thanks) is not None

    @pytest.mark.parametrize(
        "question",
        [
            "yo what is aspire",
            "what even is aspire lol",
            "hey how do i join aspire",
            "what is the seeded amount",
        ],
    )
    def test_a_real_question_is_never_swallowed_as_small_talk(self, question):
        """A question that merely opens casually still has to reach the router."""
        assert self._reply(question) is None

    def test_the_reply_does_not_mirror_the_slang(self):
        """Understand "yo"; do not answer with it."""
        reply = self._reply("yo") or ""
        assert "yo" not in reply.lower().split()
        assert "lol" not in reply.lower()
