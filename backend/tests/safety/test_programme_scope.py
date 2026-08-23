"""ASPIRE may say what ASPIRE is, at every band.

THE DECISION, 22 August 2026
    A child in this programme owns EC$500 of investment. Telling them what that
    is is not financial education -- it is telling them what they have. The band
    ladder was refusing it, so Skye could not say what half of a five-year-old's
    own money does, and could not spell the programme's name out either, because
    "Achieving Success through Personal INVESTMENT..." trips the same gate.

    So the band vocabulary ban lifts for an answer grounded in the Golden
    Record: ASPIRE's own sourced facts. Nothing else moves.

THREE LAYERS, AND ONLY THE MIDDLE ONE MOVES
    1. `_GENERAL_BAN` -- guaranteed return, get rich, risk-free, crypto, day
       trading, guaranteed profit. NEVER lifts. Not an age gate: a position the
       programme takes, at every band including adult, in every context. A scam
       sentence does not become safe because it is about ASPIRE. It becomes
       worse, because it now carries the programme's name.
    2. The band ladder -- interest, investment, credit, compound, dividend,
       portfolio. Lifts for the Golden Record. Holds everywhere else.
    3. The cards' figure rules. NOT in this file and not in the ladder. Skye may
       now say her money is invested and still may not say 2%, because "never a
       rate, a percentage, a balance or a projection, not even a sourced one"
       lives in her card. The WORDS and the NUMBERS were always separate rules.
"""

from __future__ import annotations

import pytest

from app.graph.nodes.safety_out import grounded_in_the_programme
from app.safety import vocab


class _Chunk:
    def __init__(self, kb_id="", **metadata):
        self.kb_id = kb_id
        self.metadata = metadata


class TestTheBandLadderLiftsForTheGoldenRecord:
    @pytest.mark.parametrize(
        "text",
        [
            "Half of your money is invested for you.",
            "The bank pays you interest, credited twice a year.",
            "Achieving Success through Personal Investment, Resources and Education",
            "EC$500 is invested in shares of government-owned entities.",
        ],
    )
    def test_a_programme_fact_reaches_the_youngest_reader(self, text):
        assert not vocab.check(text, "5-8", programme_scope=True)

    @pytest.mark.parametrize(
        ("text", "term"),
        [
            ("Compound interest means your interest earns interest.", "compound"),
            ("You could take a loan to buy it.", "loan"),
            ("Watch out for inflation.", "inflation"),
        ],
    )
    def test_ungrounded_education_still_meets_the_full_ladder(self, text, term):
        """The ladder was written for exactly this. A five-year-old does not
        need compound interest explained; they do need to know the money is
        theirs."""
        assert term in {v.term for v in vocab.check(text, "5-8")}

    def test_loan_never_lifts_even_in_scope(self):
        """`loan` is not in PROGRAMME_TERMS. ASPIRE does not lend to children,
        so no programme fact needs the word."""
        assert "loan" not in vocab.PROGRAMME_TERMS
        assert vocab.check("It is like a loan.", "5-8", programme_scope=True)


class TestTheScamBanNeverLifts:
    """The half that must survive every future widening of the other half."""

    @pytest.mark.parametrize(
        ("text", "term"),
        [
            ("ASPIRE offers a guaranteed return.", "guaranteed return"),
            ("You can get rich with this.", "get rich"),
            ("It is a risk-free investment.", "risk-free"),
            ("This is a guaranteed profit.", "guaranteed profit"),
        ],
    )
    @pytest.mark.parametrize("band", ["5-8", "9-12", "13-15", "16-18", "adult"])
    def test_it_fires_at_every_band_in_programme_scope(self, text, term, band):
        found = {v.term for v in vocab.check(text, band, programme_scope=True)}
        assert term in found, (
            f"{text!r} passed at {band} in programme scope. A scam sentence "
            f"does not become safe because it is about ASPIRE."
        )

    def test_no_general_ban_term_is_ever_liftable(self):
        """Structural, not case-by-case: adding a scam phrase to the general
        list must never make it eligible for the lift."""
        assert not (set(vocab._GENERAL_BAN) & vocab.PROGRAMME_TERMS)


class TestWhatCountsAsGrounded:
    """Decided by what the answer was BUILT FROM, not what it mentions."""

    def test_an_asp_row_grounds_it(self):
        assert grounded_in_the_programme({"retrieved": [_Chunk(kb_id="ASP-339")]})

    def test_a_programme_category_grounds_it(self):
        assert grounded_in_the_programme(
            {"retrieved": [_Chunk(kb_id="FIN-001", category="Eligibility")]}
        )

    def test_generic_financial_education_does_not(self):
        assert not grounded_in_the_programme(
            {"retrieved": [_Chunk(kb_id="FIN-123", category="Money Basics")]}
        )

    def test_no_retrieval_means_no_lift(self):
        """The safe direction to fail in: a reply that reached for `investment`
        while grounded in nothing is what the ladder exists to stop."""
        assert not grounded_in_the_programme({"retrieved": []})
        assert not grounded_in_the_programme({})
