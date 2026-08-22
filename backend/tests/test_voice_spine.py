"""The client's voice spine, against the code that has to enforce it.

`app/prompting/spine/aspire_personas.yaml` is the ASPIRE Voice Kit's source of
truth for the structural facts. The same numbers are declared independently in
`app/safety/vocab.py` and `app/graph/nodes/safety_out.py`, and this file is the
only thing that makes the two agree.

The duplication is deliberate. Wiring the YAML up as the runtime source would
remove exactly the disagreement these tests exist to find -- a cap edited in
code without the spine moving, or a spine revision landing without the code
following it. Both are silent: the suite stays green and the product quietly
stops matching the document the client signed off.

Reconciled by hand on 22 August 2026 and found to agree on every value. These
tests are what stop that from being a one-off.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.graph.nodes.safety_out import (
    LESSON_WORD_CAPS,
    QA_WORD_CAPS,
    STORY_WORD_CAPS,
    WORD_CAPS,
)
from app.safety import vocab

SPINE_FILE = Path(__file__).resolve().parents[1] / (
    "app/prompting/spine/aspire_personas.yaml"
)


@pytest.fixture(scope="module")
def spine() -> dict:
    return yaml.safe_load(SPINE_FILE.read_text(encoding="utf-8"))


class TestTheEnforcedWordCaps:
    """Over the cap a reply is CUT, not shortened, so these are the numbers a
    reader actually feels. A card written past its cap arrives mid-sentence.

    Four tables, not one. The spine's own note on why the story table exists is
    worth keeping in view: a five-year-old's ordinary cap of 35 words truncates
    a story mid-sentence, and `truncate_at_sentence` does it silently -- the
    build passes, the tests pass, and the reader gets half a story.
    """

    TABLES = {
        "ordinary": WORD_CAPS,
        "lesson": LESSON_WORD_CAPS,
        "qa": QA_WORD_CAPS,
        "story": STORY_WORD_CAPS,
    }

    @pytest.mark.parametrize("kind", ["ordinary", "lesson", "qa", "story"])
    def test_every_band_in_every_table_matches_the_spine(self, spine, kind):
        want = spine["word_caps_enforced"][kind]
        got = self.TABLES[kind]
        for band, value in want.items():
            assert got[band] == value, (
                f"{kind}/{band}: spine says {value}, code enforces {got[band]}"
            )

    def test_the_adult_band_has_no_cap_rather_than_a_large_one(self, spine):
        """`null` and a big number are different behaviours, not the same one."""
        assert spine["word_caps_enforced"]["ordinary"]["adult"] is None
        assert WORD_CAPS["adult"] is None

    def test_a_story_gets_more_room_than_an_ordinary_reply_at_every_band(
        self, spine
    ):
        """The reason the story table exists at all."""
        ordinary = spine["word_caps_enforced"]["ordinary"]
        story = spine["word_caps_enforced"]["story"]
        for band, cap in ordinary.items():
            if cap is None:
                continue
            assert story[band] > cap, band


class TestTheVocabularyLadder:
    """Enforced twice -- at load time when a concept is read, and at reply time
    in `safety_out`. A term missing here is a term that reaches a child."""

    @pytest.mark.parametrize("band", ["5-8", "9-12", "13-15", "16-18", "adult"])
    def test_the_allow_list_matches(self, spine, band):
        want = set(spine["vocabulary_ladder"]["allow"][band] or [])
        assert set(vocab._ALLOW.get(band, ())) == want

    @pytest.mark.parametrize("band", ["5-8", "9-12", "13-15", "16-18", "adult"])
    def test_the_ban_list_matches(self, spine, band):
        want = set(spine["vocabulary_ladder"]["ban"][band] or [])
        assert set(vocab._BAN.get(band, {})) == want

    def test_the_general_ban_matches(self, spine):
        want = set(spine["vocabulary_ladder"]["general_ban"])
        assert set(vocab._GENERAL_BAN) == want

    def test_the_youngest_band_still_bans_the_word_its_card_teaches_around(
        self, spine
    ):
        """The 5-8 card teaches what interest IS without naming it, and that
        only works while the gate behind it holds."""
        assert "interest" in spine["vocabulary_ladder"]["ban"]["5-8"]
        assert [v.term for v in vocab.check("what interest is", "5-8")] == ["interest"]


class TestTheCardsTheSpineNames:
    def test_every_card_file_the_spine_names_exists(self, spine):
        base = SPINE_FILE.parent.parent / "personas"
        missing = [
            voice["card_file"]
            for voice in spine["voices"]
            if not (base / voice["card_file"]).exists()
        ]
        assert not missing, f"the spine names cards that are not here: {missing}"

    def test_kaleb_is_its_own_key_and_its_own_card(self, spine):
        """Option B. A label on `stella` resolved by band is the thing this is
        not, and the distinction is the whole of the split."""
        assert spine["kaleb_split"]["decision"].startswith("Option B")
        kaleb = next(v for v in spine["voices"] if v["key"] == "kaleb")
        assert kaleb["card_file"] == "kaleb.9-12.md"
        assert kaleb["band"] == "9-12"


class TestTheCareBlockInvariant:
    """The spine's own words: identical in all seven cards, Ministry route
    included. It is the highest-consequence text in the product.

    Recorded here because the 22 August kit's `body_expanded` for four cards
    appends a per-card note to the CARE text, which would have produced four
    variants of a safeguarding instruction. `tests/test_voices.py` catches it;
    this is the reason it must keep catching it.
    """

    def test_the_spine_requires_one_care_block(self, spine):
        care = spine["invariants"]["care_block"]
        assert "Identical in all seven cards" in care

    def test_no_card_appends_to_its_care_block(self, spine):
        base = SPINE_FILE.parent.parent / "personas"
        offenders = [
            voice["card_file"]
            for voice in spine["voices"]
            if (base / voice["card_file"]).exists()
            and "THIS CARD ALSO" in (base / voice["card_file"]).read_text(
                encoding="utf-8"
            )
        ]
        assert not offenders, (
            "per-card CARE notes belong beside the block, not inside it: "
            f"{offenders}"
        )
