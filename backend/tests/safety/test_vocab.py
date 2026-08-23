"""The band ladder, and the words that must not climb it early."""

from __future__ import annotations

import pytest

from app.learning.concepts import ConceptStore, TeachingConcept, set_store
from app.safety import vocab


@pytest.fixture
def store_holding():
    """Load the process-wide concept store, and put it back afterwards."""

    def _load(*concepts: TeachingConcept) -> ConceptStore:
        store = ConceptStore()
        store.load(concepts)
        set_store(store)
        return store

    yield _load
    set_store(None)


def _seeded_concept(**overrides) -> TeachingConcept:
    """A concept spelt the way the seeder writes one: `CON-0064`, teachable at 13-15."""
    fields = {
        "id": "CON-0064",
        "slug": "compound_interest",
        "locale": "en",
        "title": "Compound interest",
        "domain": "saving",
        "band_min": "13-15",
        "band_max": "adult",
        "bodies": {"13-15": "Interest that earns interest."},
    }
    fields.update(overrides)
    return TeachingConcept(**fields)


class TestTheLadder:
    def test_it_accumulates_upward(self):
        assert "save" in vocab.concepts_for("5-8")
        assert "save" in vocab.concepts_for("13-15")
        # `interest` moved to the youngest rung on 22 August 2026, so it is on
        # both -- accumulation is exactly what carries it upward.
        assert "interest" in vocab.concepts_for("5-8")
        assert "interest" in vocab.concepts_for("9-12")
        assert "compound interest" in vocab.concepts_for("13-15")
        assert "compound interest" not in vocab.concepts_for("9-12")

    def test_an_unknown_band_has_an_empty_ladder(self):
        """Nothing is on an unknown band's ladder, so gate 3 refuses."""
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


class TestTheStoreLookup:
    """Concepts the ladder has never heard of, matched against the store instead."""

    @pytest.mark.parametrize(
        "written",
        ["con_0064", "CON-0064", "con-0064", "CON_0064", "  Con_0064  "],
        ids=["underscore", "as_seeded", "lowered", "upper_underscore", "padded"],
    )
    def test_a_seeded_id_matches_whichever_separator_was_written(
        self, store_holding, written
    ):
        """The composer emitted `con_0064` for `CON-0064`; a case fold alone left them
        unequal and gate 3 dropped a fully composed widget as off-ladder."""
        store_holding(_seeded_concept())
        assert vocab.is_allowed_concept(written, "13-15") is True

    def test_a_slug_matches_the_same_way(self, store_holding):
        store_holding(_seeded_concept(slug="credit_score_basics"))
        assert vocab.is_allowed_concept("credit-score-basics", "13-15") is True

    def test_flattening_does_not_admit_an_unteachable_band(self, store_holding):
        """Matching is spelling-blind; the gate is still `teachable_at`."""
        store_holding(_seeded_concept())
        assert vocab.is_allowed_concept("con_0064", "9-12") is False

    def test_an_unknown_id_is_still_refused(self, store_holding):
        store_holding(_seeded_concept())
        assert vocab.is_allowed_concept("con_9999", "13-15") is False


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
            # `interest` was here until 22 August 2026, when it was lifted at
            # this band -- a piggy bank is a picture a five-year-old owns.
            # `percent` below is what still holds the line, and it is the one
            # that matters: the idea is teachable at five, the arithmetic is not.
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
        """A banned term that matches nothing is a rule that does not exist."""
        assert vocab.check(f"Let us talk about {term} today.", "5-8"), term

    def test_percent_sign_is_caught_despite_being_punctuation(self):
        """`\\b%\\b` matches nothing at all. This is why `_compile` is careful."""
        assert vocab.check("You get 5% a year.", "5-8")

    @pytest.mark.parametrize("band", vocab.BANDS)
    def test_the_general_list_applies_at_every_band(self, band):
        """Including adult. These are not concepts that arrive later."""
        assert vocab.check("This is a guaranteed return, risk-free.", band)

    def test_interesting_is_not_interest(self):
        """The reason this module writes variants out instead of stemming."""
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


class TestAClaimIsNotATopic:
    """Two different kinds of thing used to live in one list."""

    BANDS = ("5-8", "9-12", "13-15", "16-18", "adult")

    @pytest.mark.parametrize(
        "word",
        ["risk-free", "risk free", "guaranteed return", "guaranteed returns",
         "guaranteed profit", "get rich", "sin riesgo", "rendement garanti",
         "hacerse rico", "sans risque"],
    )
    def test_a_false_claim_is_banned_at_every_band(self, word):
        """"Risk-free" is no safer to say to a guardian than to a nine-year-old.

        It is worse: an adult can act on it.
        """
        for band in self.BANDS:
            assert vocab.check(word, band), f"{word!r} leaked at {band}"

    @pytest.mark.parametrize("word", ["risk-free", "guaranteed return", "get rich"])
    def test_and_no_scope_can_lift_one(self, word):
        assert vocab.check(word, "adult", teaching_scope=True)
        assert vocab.check(word, "adult", programme_scope=True)

    @pytest.mark.parametrize(
        "word", ["crypto", "Bitcoin", "cryptocurrency", "day trading", "criptomoneda"]
    )
    def test_a_topic_is_barred_below_adult(self, word):
        for band in ("5-8", "9-12", "13-15", "16-18"):
            assert vocab.check(word, band), f"{word!r} reached a minor at {band}"

    @pytest.mark.parametrize("word", ["crypto", "Bitcoin", "cryptocurrency", "day trading"])
    def test_but_an_adult_may_have_it_named(self, word):
        """Banning the word stopped the assistant naming what it was declining.

        Measured live: a guardian asking about Bitcoin was answered "some kinds
        of online money can lose or gain value very quickly" -- circumlocution,
        in a child's register, to an adult. A teacher asking what to tell a
        pupil got the same evasion, when the word is what she needs in class.
        """
        assert not vocab.check(word, "adult")

    def test_a_lesson_to_a_child_still_cannot_say_one(self):
        """The teaching lift must not reach a topic."""
        assert vocab.check("crypto", "9-12", teaching_scope=True)
        assert vocab.check("day trading", "13-15", teaching_scope=True)

    def test_the_union_still_covers_both(self):
        assert set(vocab._GENERAL_BAN) == set(vocab._NEVER_CLAIM) | set(vocab._NOT_FOR_MINORS)
        assert not (set(vocab._NEVER_CLAIM) & set(vocab._NOT_FOR_MINORS))
