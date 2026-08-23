"""Anyone asking about ASPIRE gets an answer, whichever persona they are on.

THE CLIENT'S RULE, set on 23 August 2026 and overriding everything below it:

    Anyone asking about ASPIRE irregardless of PERSONA must get an answer.
    For Skye, Kaleb and Zion the definitive golden-record response must be
    given first, then an age-friendly explanation after.

Observed on production the same day. A five-year-old on Skye asked "What is the
ASPIRE programme?" and was answered:

    "That is something a grown-up should tell you. What I can say is that the
     money is yours, it is safe, and it is growing."

Six of the seven persona/band pairs answered it correctly. Skye alone refused,
because 5-8 is the only band with a figure rule and the lift that should have
applied never fired: `programme_scope` was decided from RETRIEVAL, and retrieval
had not found a programme row. A cold index, an unembedded row or a query that
misses were all enough to take the most important question in the product down
to a deflection.

The scope is now decided from the QUESTION as well. A reader who types "aspire"
has told us the scope, and that does not depend on a vector store being warm.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app.graph.nodes.safety_out import (
    about_the_programme,
    grounded_in_the_programme,
    has_figure,
)

CORPUS = Path(__file__).resolve().parent.parent / "data" / "knowledge_base.csv"


def _asked(text: str) -> dict:
    message = type("M", (), {"type": "human", "content": text})()
    return {"messages": [message]}


class TestTheScopeIsReadOffTheQuestion:
    @pytest.mark.parametrize(
        "question",
        [
            "What is the ASPIRE programme?",
            "what is aspire",
            "Tell me about ASPIRE",
            "How much money do I get?",
            "How much will my child get?",
            "Who runs it?",
            "Who funds ASPIRE?",
            "what is this",
            "Can I see my savings account?",
        ],
    )
    def test_a_programme_question_is_in_scope(self, question: str):
        assert about_the_programme(_asked(question)), (
            f"{question!r} would fall to the blanket figure rule"
        )

    @pytest.mark.parametrize(
        "question",
        [
            "How much will my money be worth in ten years?",
            "What is compound interest?",
            "Tell me a story",
            "What is a budget?",
        ],
    )
    def test_an_ordinary_question_is_not(self, question: str):
        """The lift must not become the default. A projection is still refused."""
        assert not about_the_programme(_asked(question))

    def test_it_does_not_need_retrieval_to_have_worked(self):
        """The whole point: grounding says no, the question still says yes."""
        state = _asked("What is the ASPIRE programme?")
        assert grounded_in_the_programme(state) is False
        assert about_the_programme(state) is True

    def test_an_empty_turn_is_not_a_scope(self):
        assert not about_the_programme({})
        assert not about_the_programme(_asked(""))


class TestTheAnswerSurvivesTheGate:
    GOLDEN = (
        "ASPIRE is a programme from the Government of Saint Kitts and Nevis. Every "
        "child who can join gets EC$1,000. EC$500 is saved for you in a bank. "
        "EC$500 is invested for you."
    )

    def test_the_golden_record_passes_at_five_to_eight(self):
        assert has_figure(self.GOLDEN) is True, "still blocked without the lift"
        assert has_figure(self.GOLDEN, programme_scope=True) is False

    @pytest.mark.parametrize(
        "text,what",
        [
            ("The bank pays 2 percent a year.", "a rate"),
            ("After one year you would have EC$510.05.", "a projection"),
            ("Your balance is EC$1,247.30.", "a balance"),
        ],
    )
    def test_and_the_rules_that_matter_still_hold(self, text: str, what: str):
        assert has_figure(text, programme_scope=True) is True, f"{what} got through"

    def test_the_vocabulary_lift_is_scoped_to_programme_terms(self):
        """Widening the TRIGGER must not widen WHAT is allowed.

        The lift covers `vocab.PROGRAMME_TERMS` and nothing else, so reaching it
        from the question rather than from retrieval changes who gets an answer,
        never what may be in one.
        """
        from app.safety import vocab

        assert not vocab.check(self.GOLDEN, "5-8", programme_scope=True)
        assert vocab.PROGRAMME_TERMS, "an empty term set would lift everything"

    @pytest.mark.parametrize(
        "text",
        [
            "You could put it in crypto.",
            "This is a guaranteed return.",
            "It is risk-free.",
            "That is how you get rich.",
        ],
    )
    def test_the_general_ban_is_never_lifted(self, text: str):
        """`_GENERAL_BAN` is absolute at every band, in scope or out of it.

        This is the floor the lift must never reach. A programme question is a
        reason to name EC$500; it is not a reason to say `risk-free` to anybody.
        """
        from app.safety import vocab

        assert vocab.check(text, "5-8", programme_scope=True), f"{text!r} got through"
        assert vocab.check(text, "adult", programme_scope=True), f"{text!r} at adult"


class TestTheChildRowsLeadWithTheDefinitiveAnswer:
    """Golden record first, age-friendly gloss after — not the other way round."""

    @staticmethod
    def _rows() -> list[dict]:
        with CORPUS.open(newline="", encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle))

    @pytest.mark.parametrize(
        "row_id", ["ASP-339", "ASP-426", "ASP-427", "ASP-428", "ASP-429"]
    )
    def test_the_amounts_are_present(self, row_id: str):
        row = next(r for r in self._rows() if r["id"] == row_id)
        assert "EC$1,000" in row["answer"] or "EC$500" in row["answer"], (
            f"{row_id} describes ASPIRE to a child without saying what they get"
        )

    @pytest.mark.parametrize(
        "row_id", ["ASP-339", "ASP-426", "ASP-427", "ASP-428", "ASP-429"]
    )
    def test_they_clear_the_gate_they_are_written_for(self, row_id: str):
        from app.safety import vocab

        row = next(r for r in self._rows() if r["id"] == row_id)
        assert not vocab.check(row["answer"], "5-8", programme_scope=True)
        assert has_figure(row["answer"], programme_scope=True) is False
        assert len(row["answer"].split()) <= 120, "over the 5-8 Q&A cap"

    def test_no_child_row_sends_them_to_a_grown_up_about_the_programme(self):
        """The deflection is correct for a projection and wrong for this."""
        for row in self._rows():
            if row["audience"] != "child":
                continue
            if "grown-up should tell you" not in row["answer"]:
                continue
            asks_what_it_is = about_the_programme(_asked(row["question"]))
            assert not asks_what_it_is, (
                f"{row['id']} deflects a programme question: {row['question']!r}"
            )


class TestTheScopeReachesEverySurface:
    """The lift existed in one place and three surfaces did not have it.

    A turn is one thing to a reader. When the prose may say `investment` under
    the programme lift and the chip beneath it may not, the widget beside it may
    not, and the lesson about it will not load, the ladder is contradicting
    itself inside a single screen.
    """

    def test_chips_get_the_same_scope_as_the_prose(self):
        from app.graph.nodes.safety_out import chips_within_band

        chips = ["What is ASPIRE?", "Where is my investment?", "How much do I get?"]
        kept, dropped = chips_within_band(chips, "5-8")
        assert "Where is my investment?" in dropped, "the blanket rule should still bite"

        kept, dropped = chips_within_band(chips, "5-8", programme_scope=True)
        assert not dropped, f"a programme chip was deleted: {dropped}"
        assert len(kept) == 3

    def test_a_widget_may_label_the_half_the_sentence_just_named(self):
        from app.widgets.validate import GateContext
        from app.safety import vocab

        blanket = GateContext(age_band="5-8")
        scoped = GateContext(age_band="5-8", programme_scope=True)
        assert blanket.programme_scope is False
        assert scoped.programme_scope is True
        assert vocab.check("EC$500 invested", "5-8")
        assert not vocab.check("EC$500 invested", "5-8", programme_scope=True)

    @pytest.mark.parametrize(
        "band,word",
        [("5-8", "investment"), ("5-8", "interest"), ("9-12", "compound"), ("9-12", "dividend")],
    )
    def test_a_lesson_may_be_authored_about_what_it_teaches(self, band: str, word: str):
        """This one failed at LOAD, not at reply time — the module refused to exist."""
        from app.safety import vocab

        assert not vocab.check(word, band, programme_scope=True), (
            f"a concept teaching {word!r} at {band} would not load"
        )

    @pytest.mark.parametrize(
        "band,word", [("5-8", "inflation"), ("5-8", "loan"), ("9-12", "loan")]
    )
    def test_but_only_the_terms_the_programme_uses_about_itself(self, band, word):
        from app.safety import vocab

        assert vocab.check(word, band, programme_scope=True), (
            f"{word!r} is not a programme term and should still be refused at {band}"
        )

    def test_the_authored_curriculum_still_loads(self):
        """The change must not have turned the validator off."""
        from app.curriculum.schema import load_all

        curriculum = load_all()
        assert curriculum.modules and curriculum.lessons and curriculum.concepts

    def test_a_module_naming_a_general_ban_term_is_still_rejected(self):
        from app.curriculum.schema import Concept

        with pytest.raises(ValueError):
            Concept(
                id="bad_concept",
                name="Bad",
                band_min="5-8",
                band_max="adult",
                module_id="module_01_saving",
                vocabulary=["crypto"],
            )


class TestConversationalFlow:
    """Things that stop a conversation being one, found by having conversations.

    Every case here was observed against aspire.eccugenai.app on 23 August 2026.
    """

    def test_a_reader_can_say_stop(self):
        """"cancel" alone was answered with advice about unused subscriptions.

        The reader asked the assistant to stop and it changed the subject to
        direct debits, which is the one moment not-listening is unmistakable.
        A closed class, so it belongs in front of the router with the greeting.
        """
        from app.agents.qa.nodes import small_talk_answer, small_talk_kind

        for text in ("cancel", "stop", "never mind", "forget it", "start over"):
            assert small_talk_kind(text) == "stop", f"{text!r} is not recognised"
            reply = small_talk_answer(
                text, locale="en", persona="aurora", age_band="adult"
            )
            assert reply and "subscription" not in reply.lower()

    @pytest.mark.parametrize("locale", ["en", "es", "fr"])
    def test_and_be_answered_in_their_own_language(self, locale: str):
        from app.agents.qa.nodes import small_talk_answer

        assert small_talk_answer(
            "cancel", locale=locale, persona="aurora", age_band="adult"
        ).strip()

    def test_a_real_question_about_cancelling_still_reaches_the_corpus(self):
        """The guard must not swallow a genuine question."""
        from app.agents.qa.nodes import small_talk_kind

        assert small_talk_kind("should I cancel my subscriptions?") is None
        assert small_talk_kind("cancel my ASPIRE application") is None

    def test_the_rewriter_resolves_a_fragment_against_context(self):
        """The instruction that was suspected and cleared.

        "she is 15" was answered "I do not have an answer for that" on
        production while `and the 15 year old?` worked on identical context,
        which pointed at the rewriter: its prompt ends "if the message already
        stands alone, repeat it unchanged", and "she is 15" is a grammatically
        complete sentence.

        Tested against the real rewriter on production's own model, with real
        conversation context, and IT RESOLVES CORRECTLY -- "Can my 15-year-old
        daughter join ASPIRE?". So the rewriter is not the cause and the prompt
        was left as it shipped. The failure is downstream of the rewrite, in
        retrieval or the 0.55 relevance floor, and settling that needs the
        corpus rather than a model.

        This asserts the instruction is intact, so a later reader does not
        re-suspect it.
        """
        from app.agents.qa.nodes import REWRITE_SYSTEM, REWRITE_WINDOW

        assert "Resolve pronouns and anything left out" in REWRITE_SYSTEM
        assert "using the conversation for context" in REWRITE_SYSTEM
        assert REWRITE_WINDOW >= 4, "too little context to resolve a pronoun"

    def test_aurora_does_not_answer_yes_to_a_question_that_asked_neither(self):
        """"What is ASPIRE?" was answered "Yes." and "When can she access it?"
        was answered "No." — a refusal-shaped opening on a question about when.

        The card said "Yes or no in the FIRST line" unconditionally.
        """
        from pathlib import Path

        card = (
            Path(__file__).resolve().parent.parent
            / "app/prompting/personas/aurora.adult.md"
        ).read_text(encoding="utf-8")
        assert "ONLY when she asked a yes-or-no" in card
        assert "The ANSWER in the FIRST line" in card


class TestTeachingScope:
    """`loan` in a tutorial, on the client's ruling of 23 August 2026."""

    @pytest.mark.parametrize("band", ["5-8", "9-12", "13-15", "16-18", "adult"])
    def test_a_lesson_may_say_loan_at_every_band(self, band: str):
        from app.safety import vocab

        assert not vocab.check("loan", band, teaching_scope=True)

    @pytest.mark.parametrize("band", ["5-8", "9-12"])
    def test_but_ordinary_talk_still_may_not(self, band: str):
        """A guide wandering into lending at a nine-year-old has changed the
        subject to something nobody asked about."""
        from app.safety import vocab

        assert vocab.check("loan", band)
        assert vocab.check("loan", band, programme_scope=True), (
            "ASPIRE lends nobody anything; `loan` is not a programme term"
        )

    def test_teaching_scope_contains_programme_scope(self):
        from app.safety import vocab

        assert vocab.PROGRAMME_TERMS < vocab.TEACHING_TERMS
        assert vocab.TEACHING_TERMS - vocab.PROGRAMME_TERMS == {"loan"}

    @pytest.mark.parametrize("text", ["crypto", "risk-free", "guaranteed return"])
    def test_and_neither_scope_reaches_the_general_ban(self, text: str):
        from app.safety import vocab

        assert vocab.check(text, "adult", teaching_scope=True)

    def test_a_teaching_turn_is_recognised_by_its_agent(self):
        from app.graph.nodes.safety_out import is_a_lesson

        for agent in ("learn_agent", "learning_sample", "learning_preview"):
            assert is_a_lesson({"active_agent": agent})
        for agent in ("qa_agent_public", "register_agent_step1", None):
            assert not is_a_lesson({"active_agent": agent})
