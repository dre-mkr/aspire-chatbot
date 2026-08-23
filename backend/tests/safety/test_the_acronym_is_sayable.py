"""ASPIRE can say its own name to a five-year-old.

It could not, and that is the point of this file.

    "Achieving Success through Personal INVESTMENT, Resources and Education"

`investment` was banned at 5-8, so the safety layer stripped it and the
expansion arrived with a hole where the word should be. The workaround was a
5-8 answer that described the name without reciting it, and a separate 9-12 row
carrying the real thing -- which meant the youngest readers in the programme
could not be told what the programme is called.

The programme-scope decision closed it. A guide answering from ASPIRE's own
sourced facts may use the programme's own vocabulary, and the name is the most
obviously programme-owned string there is.

WHAT DID NOT CHANGE, and this is why the fix is narrow rather than a hole:
`investment` is still banned at 5-8 in ordinary prose. A guide wandering into
investment advice for a five-year-old is stopped exactly as before. Only the
programme talking about itself is let through.
"""

from __future__ import annotations

import csv
import pathlib

import pytest

from app.safety import vocab

ACRONYM = "Achieving Success through Personal Investment, Resources and Education"
_CORPUS = pathlib.Path(__file__).resolve().parents[2] / "data/knowledge_base.csv"


def _row(kb_id: str) -> dict[str, str]:
    with _CORPUS.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["id"] == kb_id:
                return row
    raise AssertionError(f"{kb_id} is not in the corpus")


class TestTheNameSurvivesTheGate:
    @pytest.mark.parametrize("band", ["5-8", "9-12", "13-15", "16-18", "adult"])
    def test_it_can_be_said_at_every_band(self, band):
        assert not vocab.check(ACRONYM, band, programme_scope=True), (
            f"ASPIRE cannot spell its own name at {band}"
        )

    def test_the_youngest_row_now_carries_it(self):
        """Skye's answer recites the name instead of talking around it."""
        row = _row("ASP-340")
        assert row["audience"] == "child"
        assert "Achieving Success through Personal Investment" in row["answer"]
        assert not vocab.check(row["answer"], "5-8", programme_scope=True)

    def test_it_still_fits_her_ceiling(self):
        """35 words on an ordinary reply, enforced by cutting. A source row
        longer than the cap is a source row that arrives truncated."""
        assert len(_row("ASP-340")["answer"].split()) <= 35


class TestTheLiftIsStillNarrow:
    def test_investment_remains_banned_in_ordinary_prose(self):
        """The fix is scoped to the programme talking about itself. General
        investment talk at a five-year-old is stopped exactly as before."""
        assert "investment" in vocab._BAN["5-8"]
        assert vocab.check("You should make an investment.", "5-8")
        assert vocab.check(ACRONYM, "5-8")  # ungrounded: still stripped

    def test_the_figure_is_still_refused(self):
        """Naming the programme is not pricing it. `percent` holds the line."""
        assert [
            v.term
            for v in vocab.check("It pays two percent.", "5-8", programme_scope=True)
        ] == ["percent"]
