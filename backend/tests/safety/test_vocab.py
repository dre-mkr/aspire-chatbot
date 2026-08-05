"""The band ladder, and the words that must not climb it early."""

from __future__ import annotations

import pytest

from app.safety import vocab


class TestTheLadder:
    def test_it_accumulates_upward(self):
        assert "save" in vocab.concepts_for("5-8")
        assert "save" in vocab.concepts_for("13-15")
        assert "interest" in vocab.concepts_for("9-12")
        assert "interest" not in vocab.concepts_for("5-8")
        assert "compound interest" in vocab.concepts_for("13-15")
        assert "compound interest" not in vocab.concepts_for("9-12")

    def test_an_unknown_band_has_an_empty_ladder(self):
        """Nothing is on an unknown band's ladder, so gate 3 refuses.

        The permissive alternative -- treating an unknown band as adult --
        would make a malformed token the widest permission in the system.
        """
        assert vocab.concepts_for("42") == frozenset()

    @pytest.mark.parametrize(
        ("concept", "band", "expected"),
        [
            ("compound_interest", "13-15", True),
            ("compound-interest", "13-15", True),
            ("Compound Interest", "13-15", True),
            ("compound_interest", "9-12", False),
            ("saving", "5-8", False),  # the ladder says "save", not "saving"
            ("save", "5-8", True),
        ],
    )
    def test_concept_ids_normalise(self, concept, band, expected):
        assert vocab.is_allowed_concept(concept, band) is expected


class TestBannedTerms:
    def test_compound_is_caught_for_a_nine_to_twelve(self):
        """The acceptance case from the specification, stated directly."""
        violations = vocab.check(
            "Compound interest means your interest earns interest.", "9-12"
        )
        assert [v.term for v in violations] == ["compound"]

    def test_the_same_sentence_passes_at_thirteen_to_fifteen(self):
        assert vocab.is_clean(
            "Compound interest means your interest earns interest.", "13-15"
        )

    @pytest.mark.parametrize(
        "term",
        [
            "interest",
            "compound",
            "investment",
            "inflation",
            "dividend",
            "credit",
            "loan",
            "percent",
            "portfolio",
        ],
    )
    def test_every_five_to_eight_ban_actually_fires(self, term):
        """A banned term that matches nothing is a rule that does not exist.

        This is the failure mode a banned list has: a typo, a stem that never
        occurs, or a `\\b` around a non-word character silently disabling the
        entry. Each one is checked against a sentence containing it.
        """
        assert vocab.check(f"Let us talk about {term} today.", "5-8"), term

    def test_percent_sign_is_caught_despite_being_punctuation(self):
        """`\\b%\\b` matches nothing at all. This is why `_compile` is careful."""
        assert vocab.check("You get 5% a year.", "5-8")

    @pytest.mark.parametrize("band", vocab.BANDS)
    def test_the_general_list_applies_at_every_band(self, band):
        """Including adult. These are not concepts that arrive later."""
        assert vocab.check("This is a guaranteed return, risk-free.", band)

    def test_interesting_is_not_interest(self):
        """The reason this module writes variants out instead of stemming.

        "That's interesting!" is a sentence a mascot says several times a
        lesson. Flagging it costs a model call and a second of latency, every
        time.
        """
        assert vocab.is_clean("That's interesting! Tell me more.", "5-8")

    def test_a_thirteen_to_fifteen_may_say_credit_but_not_derivative(self):
        assert vocab.is_clean("A debit card takes money you already have.", "13-15")
        assert vocab.check("Leverage amplifies a derivative position.", "13-15")

    def test_sixteen_to_eighteen_is_unrestricted_beyond_the_general_list(self):
        assert vocab.is_clean(
            "Compound interest, inflation and a diversified portfolio all matter.",
            "16-18",
        )

    def test_violations_are_ordered_by_position(self):
        """A re-prompt lists them in reading order, which is how they get fixed."""
        found = vocab.check("Inflation first, then compound, then dividend.", "9-12")
        assert [v.term for v in found] == ["inflation", "compound", "dividend"]


class TestTheReprompt:
    def test_it_names_the_terms_and_offers_the_ladder(self):
        violations = vocab.check("Compound interest grows.", "9-12")
        message = vocab.explain(violations, "9-12")
        assert "'compound'" in message
        assert "9-12" in message
        assert "interest" in message  # the ladder it may use instead
        assert "do not simply" in message.lower()

    def test_no_violations_means_no_instruction(self):
        assert vocab.explain([], "9-12") == ""
