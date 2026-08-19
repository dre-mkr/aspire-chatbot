"""One rung per age band, and nothing that strays outside St Kitts and Nevis.

Two things are enforced here, and both used to be intentions.

The ladder. The curriculum was already age-tiered -- every concept carries
`band_min` and `band_max`, every body has a per-band version -- and then the
voice that delivered it covered ages 5 to 12 in one card, so a twelve-year-old
was answered six years below themselves. Each step between bands is now an
assertion rather than a paragraph somebody hoped would be followed.

The place. The models behind this were trained mostly on American English and
reach for a mall and a soccer field without being asked. A note in a document
does not survive that; a failing build does.

What this cannot catch: content that is regionally neutral but culturally wrong
-- an example about a suburban back garden, say. A person still has to read for
that. This catches the vocabulary, which is where it leaks first and most often.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.prompting.personas import (
    FALLBACK,
    KNOWN,
    _DIR,
    persona_card,
)
from app.prompting.personas.names import NAMES, PLACEHOLDER
from app.safety import vocab

#: The six band cards: `(persona, band)`, and the file each must live in.
BAND_CARDS: dict[tuple[str, str], str] = {
    ("stella", "5-8"): "stella.5-8.md",
    ("stella", "9-12"): "stella.9-12.md",
    ("orion", "13-15"): "orion.13-15.md",
    ("orion", "16-18"): "orion.16-18.md",
    ("aurora", "adult"): "aurora.adult.md",
    ("nova", "adult"): "nova.adult.md",
}

#: Every card on disk, band-specific and undifferentiated alike.
ALL_CARDS: list[Path] = sorted(_DIR.glob("*.md"))

#: The curriculum is scanned on the same terms as the cards.
CURRICULUM: list[Path] = sorted(Path("app/curriculum/content").rglob("*.y*ml"))

#: Labels the personas have carried before, which no card may still spell out.
#:
#: A rename that leaves a card saying the old name is silent: the loader
#: substitutes `{name}` wherever it appears and simply does not notice the
#: literal beside it. Add to this list whenever `NAMES` changes.
RETIRED_NAMES: tuple[str, ...] = (
    "Stella", "Orion", "Aurora", "Nova",
    "Sky", "Prosper", "Destiny", "Star",
)

#: Where a card stops describing itself and starts naming what it refuses.
#:
#: A card that BANS a word has to name it, so the ladder is checked against the
#: half above this heading only. Without the split every prohibition reads as a
#: violation of itself -- which is how the first version of this test failed.
BAN_HEADING = "WHAT YOU NEVER SAY"


# ── the place ────────────────────────────────────────────────────────────────

#: Vocabulary that says somewhere other than here.
FOREIGN_WORDS: tuple[str, ...] = (
    "candy", "cookies", "soccer", "sidewalk", "gas station", "mall", "store",
    "high school", "freshman", "dime", "nickel", "quarter", "mom", "vacation",
    "fall", "thanksgiving", "snow", "winter",
)

#: `grade 3`, `grade 8` -- the American school year, which is not a form here.
_GRADE = re.compile(r"\bgrade\s+\d", re.IGNORECASE)

#: A snow cone is local. A northern winter is not, and the word is the same.
#:
#: The general ban list is scanned AFTER this is removed, for the same reason the
#: ladder is scanned above the ban heading: the honest local example and the
#: foreign import share a word, and the naive scan flags the thing it exists to
#: protect.
_LOCAL_HOMOGRAPHS = re.compile(r"\bsnow\s+cones?\b", re.IGNORECASE)

#: Any currency that is not the one this programme pays in.
#:
#: `(?<!EC)` keeps `EC$5` -- a bare `$` before a digit is what makes a reader
#: guess which dollar, and `EC$` never does.
FOREIGN_CURRENCY = re.compile(
    r"US\$|\bUSD\b|\bGBP\b|\beuros?\b|£|€|(?<!EC)\$\d", re.IGNORECASE
)

#: Every card must name at least one of these.
LOCAL_ANCHORS: tuple[str, ...] = (
    "st kitts", "nevis", "basseterre", "charlestown", "carnival", "culturama",
    "patty", "patties", "snow cone", "the ferry", "cxc", "cfbc", "eccb",
    "christmas",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _scannable(text: str) -> str:
    """The text a foreign-vocabulary scan sees, with local homographs removed."""
    return _LOCAL_HOMOGRAPHS.sub(" ", text)


def foreign_words_in(text: str) -> list[str]:
    """Every American-English word in `text`, in the order they appear."""
    scannable = _scannable(text)
    found = [
        word
        for word in FOREIGN_WORDS
        if re.search(rf"\b{re.escape(word)}\b", scannable, re.IGNORECASE)
    ]
    if _GRADE.search(scannable):
        found.append("grade N")
    return found


def before_the_ban_list(text: str) -> str:
    """The half of a card that speaks, rather than the half that refuses."""
    return text.split(BAN_HEADING, 1)[0]


class TestNothingStraysOutsideStKittsAndNevis:
    @pytest.mark.parametrize("path", ALL_CARDS, ids=lambda path: path.name)
    def test_no_card_uses_foreign_vocabulary(self, path):
        assert foreign_words_in(_read(path)) == []

    @pytest.mark.parametrize("path", ALL_CARDS, ids=lambda path: path.name)
    def test_no_card_names_a_foreign_currency(self, path):
        assert FOREIGN_CURRENCY.findall(_read(path)) == []

    @pytest.mark.parametrize("path", CURRICULUM, ids=lambda path: path.name)
    def test_the_curriculum_is_scanned_on_the_same_terms(self, path):
        assert foreign_words_in(_read(path)) == []
        assert FOREIGN_CURRENCY.findall(_read(path)) == []

    def test_there_is_a_curriculum_to_scan(self):
        """A glob that silently matches nothing is a test that always passes."""
        assert CURRICULUM

    def test_a_planted_americanism_fails(self):
        assert foreign_words_in("She bought candy at the mall") == ["candy", "mall"]

    def test_a_planted_school_year_fails(self):
        assert foreign_words_in("He is in grade 3 this year") == ["grade N"]

    def test_a_snow_cone_is_local_and_not_a_northern_winter(self):
        assert foreign_words_in("a snow cone at Carnival") == []
        assert foreign_words_in("snow on the ground") == ["snow"]

    def test_a_bare_dollar_before_a_digit_fails(self):
        assert FOREIGN_CURRENCY.findall("it costs $50")

    def test_ec_dollars_are_not_a_bare_dollar(self):
        assert FOREIGN_CURRENCY.findall("it costs EC$50") == []

    @pytest.mark.parametrize("named", ["US$20", "20 USD", "£20", "€20", "20 euros"])
    def test_every_other_currency_fails(self, named):
        assert FOREIGN_CURRENCY.findall(named)


class TestEveryBandCardNamesSomewhereLocal:
    """The undifferentiated four are exempt: they are the fallback, and they go.

    Anchoring is asserted on the cards this change introduces. Scoping it wider
    would fail the build on `orion.md`, `aurora.md` and `nova.md` -- which are
    kept only until the band split has landed and are then deleted -- and a gate
    that cannot go green teaches people to delete the gate.
    """

    @pytest.mark.parametrize(
        ("persona", "band"), sorted(BAND_CARDS), ids=lambda value: str(value)
    )
    def test_it_names_something_here(self, persona, band):
        text = _read(_DIR / BAND_CARDS[(persona, band)]).lower()
        assert [anchor for anchor in LOCAL_ANCHORS if anchor in text]


class TestTheVocabularyLadder:
    @pytest.mark.parametrize(
        ("persona", "band"), sorted(BAND_CARDS), ids=lambda value: str(value)
    )
    def test_a_card_stays_on_its_own_bands_ladder(self, persona, band):
        """Checked above the ban heading, where the card is speaking in its own voice."""
        spoken = before_the_ban_list(_read(_DIR / BAND_CARDS[(persona, band)]))
        assert vocab.check(spoken, band) == []

    def test_the_5_8_card_never_uses_the_word_interest(self):
        """"the money makes a little more money", and leave it there."""
        spoken = before_the_ban_list(_read(_DIR / BAND_CARDS[("stella", "5-8")]))
        assert "interest" not in spoken.lower()

    def test_the_9_12_card_uses_interest_and_does_not_compound_it(self):
        spoken = before_the_ban_list(_read(_DIR / BAND_CARDS[("stella", "9-12")])).lower()
        assert "interest" in spoken
        assert "compound" not in spoken

    def test_the_13_15_card_says_compound_interest(self):
        spoken = before_the_ban_list(_read(_DIR / BAND_CARDS[("orion", "13-15")])).lower()
        assert "compound interest" in spoken

    def test_the_step_up_is_a_step_at_every_rung(self):
        """5-8 withholds it, 9-12 names it, 13-15 compounds it. In that order."""
        spoken = {
            band: before_the_ban_list(_read(_DIR / BAND_CARDS[(persona, band)])).lower()
            for persona, band in BAND_CARDS
        }
        assert "interest" not in spoken["5-8"]
        assert "interest" in spoken["9-12"] and "compound" not in spoken["9-12"]
        assert "compound interest" in spoken["13-15"]

    def test_a_card_may_name_the_word_it_bans(self):
        """The split is load-bearing: without it every prohibition self-violates."""
        whole = _read(_DIR / BAND_CARDS[("stella", "5-8")])
        assert vocab.check(whole, "5-8"), "the ban list should name 'interest'"
        assert vocab.check(before_the_ban_list(whole), "5-8") == []

    @pytest.mark.parametrize("path", ALL_CARDS, ids=lambda path: path.name)
    def test_every_card_has_the_heading_the_split_depends_on(self, path):
        assert BAN_HEADING in _read(path)


class TestTheNameIsOneLine:
    @pytest.mark.parametrize("path", ALL_CARDS, ids=lambda path: path.name)
    def test_no_card_hardcodes_a_persona_name(self, path):
        """A client picking a nicer name must not be a fifty-file migration.

        Every card, not only the six band ones. The undifferentiated four are
        still reachable as the fallback, and they were written before the split
        with their names spelled out -- so a reader on an unrecognised band was
        greeted by the old name for as long as they stayed there.
        """
        text = _read(path)
        assert PLACEHOLDER in text
        # Whole words. `Star` is a substring of `Starting`, and a retired label
        # that fails the build on ordinary prose is a gate people delete.
        for label in (*NAMES.values(), *RETIRED_NAMES):
            assert not re.search(rf"\b{re.escape(label)}\b", text)

    def test_the_label_is_filled_in_when_the_card_is_read(self):
        assert NAMES["stella"] in persona_card("stella", "5-8")
        assert PLACEHOLDER not in persona_card("stella", "5-8")

    def test_a_rename_touches_one_line_and_no_card(self, monkeypatch):
        from app.prompting.personas import _card_text

        before = NAMES["stella"]
        monkeypatch.setitem(NAMES, "stella", "Cora")
        _card_text.cache_clear()
        card = persona_card("stella", "9-12")
        assert "Cora" in card and before not in card

    def test_every_known_persona_has_a_label(self):
        assert set(NAMES) == set(KNOWN)

    def test_the_key_is_not_the_label(self):
        """`stella` is a database id that happens to be a word."""
        assert all(key != label for key, label in NAMES.items())


class TestTheLoaderPicksTheMostSpecificCard:
    @pytest.mark.parametrize(
        ("persona", "band"), sorted(BAND_CARDS), ids=lambda value: str(value)
    )
    def test_each_pair_gets_its_own_card(self, persona, band):
        assert (_DIR / BAND_CARDS[(persona, band)]).is_file()
        opening = persona_card(persona, band).splitlines()[0]
        assert NAMES[persona] in opening

    def test_the_six_cards_all_differ(self):
        cards = {persona_card(persona, band) for persona, band in BAND_CARDS}
        assert len(cards) == len(BAND_CARDS)

    def test_an_unknown_band_falls_back_rather_than_raising(self):
        assert persona_card("orion", "99-100").strip()

    def test_an_unknown_band_stays_inside_the_persona(self):
        """A reader must not change persona because somebody added a band."""
        assert NAMES["orion"] in persona_card("orion", "99-100")

    def test_an_unknown_persona_gets_the_most_restrictive_card(self):
        assert persona_card("nobody", "9-12") == persona_card(FALLBACK, "9-12")

    def test_no_band_at_all_gets_the_youngest_card(self):
        """Not knowing who is reading has to mean the careful card."""
        assert persona_card("stella") == persona_card("stella", "5-8")

    def test_a_twelve_year_old_is_not_answered_as_a_six_year_old(self):
        """The finding this whole change exists for."""
        assert persona_card("stella", "9-12") != persona_card("stella", "5-8")
