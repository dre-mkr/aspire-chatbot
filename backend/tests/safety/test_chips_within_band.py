"""The vocabulary ladder, applied to the chips as well as the prose.

Found by asking production a question, not by reading code. On 22 August, Kaleb
-- `persona=kaleb&band=9-12` -- was asked how the interest on EC$500 works and
answered with a lesson whose tappable options were:

    I think savings · I think a loan · I think a bill · I think change

`loan` is on the enforced 9-12 ban list. The gate had run over the answer and
never over the options beneath it, because `quick_replies_ok` measures how many
chips there are and how long each one is, and nothing else.

That is the exact failure the ladder exists to prevent, arriving by the one
route nothing was watching -- and silently: the chip is well-formed, the count
is right, the suite is green.
"""

from __future__ import annotations

import pytest

from app.graph.nodes.safety_out import chips_within_band, quick_replies_ok
from app.safety import vocab


class TestTheChipThatWasActuallyServed:
    """The observed set, kept verbatim so the regression has a name."""

    OBSERVED = ["I think savings", "I think a loan", "I think a bill", "I think change"]

    def test_the_offending_chip_is_recognised_as_banned(self):
        assert [v.term for v in vocab.check("I think a loan", "9-12")] == ["loan"]

    def test_it_is_dropped_at_9_12(self):
        kept, dropped = chips_within_band(self.OBSERVED, "9-12")
        assert dropped == ["I think a loan"]
        assert "I think a loan" not in kept

    def test_the_other_three_survive(self):
        kept, _ = chips_within_band(self.OBSERVED, "9-12")
        assert kept == ["I think savings", "I think a bill", "I think change"]

    def test_the_same_set_is_untouched_for_a_band_that_may_hear_it(self):
        """`loan` opens at 13-15. The chip is fine there and must not be dropped."""
        kept, dropped = chips_within_band(self.OBSERVED, "13-15")
        assert dropped == []
        assert kept == self.OBSERVED


class TestDroppingRatherThanStripping:
    def test_a_banned_chip_is_removed_whole(self):
        """A three-word chip with a word blanked out is not an option anybody
        can tap. Prose survives a hole; a chip does not."""
        kept, dropped = chips_within_band(["I think a loan"], "9-12")
        assert kept == []
        assert dropped == ["I think a loan"]

    def test_dropping_below_the_minimum_fails_the_existing_gate(self):
        """Which is the point: `quick_replies_ok` then rejects the set and the
        fallback already written for unusable chips runs."""
        kept, _ = chips_within_band(["I think a loan", "I think a portfolio"], "9-12")
        assert kept == []
        assert not quick_replies_ok(kept)


class TestEveryBand:
    @pytest.mark.parametrize(
        ("band", "term"),
        [
            ("5-8", "dividend"),  # `interest` was lifted at 5-8 on 22 Aug 2026
            ("5-8", "credit"),
            ("9-12", "loan"),
            ("9-12", "compound"),
            ("13-15", "leverage"),
        ],
    )
    def test_a_banned_term_never_reaches_a_chip(self, band, term):
        kept, dropped = chips_within_band([f"I think {term}", "I think savings"], band)
        assert dropped == [f"I think {term}"]
        assert kept == ["I think savings"]

    @pytest.mark.parametrize("band", ["16-18", "adult"])
    def test_the_older_bands_keep_everything(self, band):
        chips = ["I think a loan", "I think compound interest", "I think a portfolio"]
        kept, dropped = chips_within_band(chips, band)
        assert dropped == []
        assert kept == chips

    def test_an_empty_set_is_not_an_error(self):
        assert chips_within_band([], "5-8") == ([], [])
