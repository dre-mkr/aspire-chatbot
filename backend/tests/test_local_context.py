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
from app.prompting.personas.names import (
    BAND_NAMES,
    NAMES,
    PLACEHOLDER,
    all_labels,
    display_name,
)
from app.safety import vocab

#: The six band cards: `(persona, band)`, and the file each must live in.
BAND_CARDS: dict[tuple[str, str], str] = {
    ("stella", "5-8"): "stella.5-8.md",
    ("kaleb", "9-12"): "kaleb.9-12.md",
    ("orion", "13-15"): "orion.13-15.md",
    ("orion", "16-18"): "orion.16-18.md",
    ("aurora", "adult"): "aurora.adult.md",
    ("nova", "adult"): "nova.adult.md",
}

#: Every card on disk, band-specific and undifferentiated alike.
ALL_CARDS: list[Path] = sorted(_DIR.glob("*.md"))


def _persona_of(path: Path) -> str:
    """The persona a card belongs to: the stem before any band suffix."""
    return path.name.split(".")[0]

#: The curriculum is scanned on the same terms as the cards.
CURRICULUM: list[Path] = sorted(Path("app/curriculum/content").rglob("*.y*ml"))

#: Labels the personas have carried before, which no card may still spell out.
#:
#: A rename that leaves a card saying the old name is silent: the loader
#: substitutes `{name}` wherever it appears and simply does not notice the
#: literal beside it. Add to this list whenever `NAMES` changes.
#:
#: `Sky` is here now. It was the label `stella` carried until the six-card
#: rewrite, which renamed it to `Skye` and gave the 9-12 band its own name --
#: and a one-letter rename is exactly the kind that survives silently. The
#: checks below are whole-word, so `Sky` does not fire on `Skye`.
RETIRED_NAMES: tuple[str, ...] = (
    "Stella", "Orion", "Aurora", "Nova",
    "Skai", "Dion", "Prosper", "Destiny", "Star", "Sky",
)

#: Where a card stops speaking in its own voice and starts listing its contents.
#:
#: The ladder is checked above this heading only. Below it a card is a
#: specification -- the topics it may cover, the lines it may not cross, the
#: script it reads at an escalation -- and a specification has to name the thing
#: it is scoping. Without the split every prohibition reads as a violation of
#: itself, which is how the first version of this test failed.
VOICE_ENDS_AT = "DELIVERABLES"

#: Where a card starts naming what it refuses. Every card must have one.
BAN_HEADING = "RED LINES"

#: How a card marks a word it is naming in order to forbid it.
#:
#: `never` rather than a heading, because the six-card rewrite moved the
#: prohibitions out of one block at the foot and spread them through the card:
#: the tone section bans a vocabulary, the red lines ban a behaviour, and the
#: care block bans a claim. A scan that reads those as the card's own speech
#: fails the build on `NEVER: mall, dime` -- the line whose whole job is to keep
#: `mall` out.
_FORBIDS = re.compile(r"\bnever\b", re.IGNORECASE)

#: Where one bullet or numbered rule ends and the next begins.
#:
#: Items, not lines, because a prohibition wraps: `NEVER: mall, dime, cookie,`
#: ends a line and `"vacation", US dollars, "grade 2"` begins the next one, and
#: a line-by-line scan sees the second half with no `never` anywhere near it.
_ITEM_START = re.compile(r"^\s*(?:-\s|\d+\.\s)")


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


def _items(text: str) -> list[str]:
    """A card split into the units a rule is written in, continuations attached."""
    items: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if current and (_ITEM_START.match(line) or not line.strip()):
            items.append("\n".join(current))
            current = []
        current.append(line)
    if current:
        items.append("\n".join(current))
    return items


def what_the_card_says(text: str) -> str:
    """A card with the rules that name a word in order to forbid it removed.

    Everything the card asserts, and nothing it refuses. `NEVER: mall, dime` is
    the card working; a scan that cannot tell it from `meet me at the mall` is a
    gate that fails on its own protection, which is a gate people delete.
    """
    return "\n".join(item for item in _items(text) if not _FORBIDS.search(item))


def foreign_words_in(text: str) -> list[str]:
    """Every American-English word in `text`, in the order they appear."""
    scannable = _scannable(what_the_card_says(text))
    found = [
        word
        for word in FOREIGN_WORDS
        if re.search(rf"\b{re.escape(word)}\b", scannable, re.IGNORECASE)
    ]
    if _GRADE.search(scannable):
        found.append("grade N")
    return found


def the_cards_own_voice(text: str) -> str:
    """The part of a card that speaks, rather than the part that specifies."""
    return what_the_card_says(text.split(VOICE_ENDS_AT, 1)[0])


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
        """Checked where the card is speaking, not where it is specifying."""
        spoken = the_cards_own_voice(_read(_DIR / BAND_CARDS[(persona, band)]))
        assert vocab.check(spoken, band) == []

    def test_the_5_8_card_puts_no_number_on_anything(self):
        """Skye may say what interest IS. It may never say what it is worth.

        The step this rung makes is not a word. It is that the youngest reader
        gets the picture and nobody gets to hand them a figure they cannot
        check -- no rate, no percentage, no balance, and no date for when the
        money can be touched, because "when you are eighteen" is a promise.
        """
        card = _read(_DIR / BAND_CARDS[("stella", "5-8")])
        assert "as pictures, never as numbers" in card
        assert "NEVER state a rate, a percentage, a balance or a projected amount" in card
        assert "NEVER give a date, an age, or a number of years" in card

    def test_the_9_12_card_shows_the_split_and_a_sourced_worked_example(self):
        """Kaleb is the first rung that gets arithmetic, and only at a sourced rate."""
        card = _read(_DIR / BAND_CARDS[("kaleb", "9-12")])
        assert "EC$500 savings / EC$500 investment" in card
        # "credited twice a year", not "compounded twice a year". `compound` is
        # banned at this band, so the old wording instructed the model to produce
        # a word the gate then stripped -- delivering the sentence with a hole
        # where the arithmetic was. The rate is now named outright rather than
        # gestured at as "a SOURCED rate", which is what the spine asks for.
        assert "credited\n    twice a year" in card
        assert "2%" in card
        assert "carrying its source" in card
        assert "NEVER give a projected value using a rate you cannot point at" in card

    @pytest.mark.parametrize("band", ["13-15", "16-18"])
    def test_the_teen_cards_require_a_source_url_for_every_figure(self, band):
        """Zion's step up is provenance: this reader opens the other tab."""
        card = _read(_DIR / BAND_CARDS[("orion", band)])
        assert "source_url" in card
        assert "with the workings shown" in card

    def test_the_step_up_is_a_step_at_every_rung(self):
        """No figures, then a sourced worked example, then a checkable source.

        The finding this whole split exists for is a twelve-year-old answered
        six years below themselves, so what matters is that consecutive rungs
        differ -- and that the difference runs one way.
        """
        card = {
            band: _read(_DIR / BAND_CARDS[(persona, band)])
            for persona, band in BAND_CARDS
        }
        assert "never as numbers" in card["5-8"]
        assert "never as numbers" not in card["9-12"]
        # The step up at this rung is a NAMED published rate, where 5-8 gets no
        # figure at all. It used to read "a SOURCED rate", which described the
        # requirement without meeting it.
        assert "2%" in card["9-12"]
        assert "source_url" not in card["9-12"]
        assert "source_url" in card["13-15"]

    def test_the_withdrawal_answer_does_not_move_between_bands(self):
        """One sourced rule, one answer, every band. Said on the card, not hoped for."""
        for persona, band in (("kaleb", "9-12"), ("orion", "13-15"), ("orion", "16-18")):
            card = _read(_DIR / BAND_CARDS[(persona, band)])
            assert "NEVER answer the withdrawal question differently" in card

    def test_a_card_may_name_the_word_it_bans(self):
        """The split is load-bearing: without it every prohibition self-violates."""
        whole = _read(_DIR / BAND_CARDS[("stella", "5-8")])
        assert vocab.check(whole, "5-8"), "the red lines should name 'percentage'"
        assert vocab.check(the_cards_own_voice(whole), "5-8") == []

    @pytest.mark.parametrize("path", ALL_CARDS, ids=lambda path: path.name)
    def test_every_card_has_the_headings_the_split_depends_on(self, path):
        text = _read(path)
        assert VOICE_ENDS_AT in text
        assert BAN_HEADING in text


class TestTheCardsAskForMoreThanTheOutboundGateAllows:
    """A recorded disagreement, not a passing grade.

    The six-card rewrite raised what the two youngest bands may be taught: the
    5-8 card names interest as something it may explain "as pictures", and the
    9-12 card asks for a worked example "compounded twice a year". The outbound
    vocabulary gate in `app/safety/vocab.py` still bans both words at both
    bands, so an answer that does exactly what its card asks is rewritten by
    `safety_out` -- a wasted model call and a worse answer, though not an
    unsafe one, because the gate holds either way.

    Which side moves is a child-safety decision and a human's to make: lift the
    terms from `_BAN`, or take the two lines back out of the cards. This test
    pins the overlap so that decision is visible in the suite rather than
    discovered in a transcript, and it fails the moment either side changes --
    which is the point.

    ONE OF THE TWO IS NOW SETTLED. At 5-8 the card yielded: it teaches that
    money left alone gets bigger and does not name the thing, because a
    five-year-old does not need the noun and cannot check the number behind it.
    The gate was always right there and the card was asking for a reply the gate
    would then take apart.

    THE 9-12 ONE IS STILL OPEN, deliberately. `compound` is a harder call than
    `interest`: a twelve-year-old in Form 1 is taught this at school, the card
    is built around using real words correctly and defining them once in
    passing, and lifting the term is arguably the right answer rather than the
    lazy one. That is a decision for the ASPIRE team, not for whoever next
    reads this file.
    """

    def test_the_5_8_card_may_name_interest_but_never_price_it(self):
        """Settled the other way round: the GATE moved, and only by one word.

        `interest` was lifted from `_BAN["5-8"]` on 22 August 2026 -- a piggy
        bank is a picture a five-year-old already owns. What was NOT lifted is
        the figure, and that is the half this test exists for: a card allowed to
        name a thing will drift toward pricing it unless something says no.
        """
        card = _read(_DIR / BAND_CARDS[("stella", "5-8")])

        # The word is teachable now, and the card uses it.
        assert "interest" in card.lower()
        assert not vocab.check("that little bit is called interest", "5-8")

        # The idea it always taught is still there, in front of the noun.
        assert "money left alone gets bigger" in card

        # And the price is still refused, in every locale the product answers in.
        for text in (
            "The bank adds two percent every year.",
            "El banco añade un porcentaje cada año.",
            "La banque ajoute un pourcentage chaque année.",
        ):
            assert [v.term for v in vocab.check(text, "5-8")] == ["percent"], (
                "the figure ban is what makes naming interest safe at this band"
            )

        # Nothing else on the 5-8 rung moved with it.
        for word in ("compound", "investment", "dividend", "loan", "portfolio"):
            assert vocab.check(f"this is about {word}", "5-8"), (
                f"{word} should still be banned at 5-8 -- only `interest` moved"
            )

    def test_the_9_12_card_no_longer_names_the_word_its_gate_strips(self):
        """Settled the same way 5-8 was: the card yielded, the gate did not.

        This card used to ask for a worked example "compounded twice a year"
        while `compound` was banned at 9-12 -- so the instruction and the gate
        were pulling against each other, and the gate wins every time. The
        reader got a sentence with the word cut out of it.

        The card now says "credited twice a year", which is both the published
        wording and outside the ban. THE UNDERLYING QUESTION IS STILL OPEN: a
        Form 1 reader is taught compounding at school, and lifting the term at
        this band may well be the right answer. That remains a decision for the
        ASPIRE team. What is no longer true is that the product ships a card
        arguing with its own safety layer while they decide.
        """
        card = _read(_DIR / BAND_CARDS[("kaleb", "9-12")])
        assert "compounded twice a" not in card
        assert "credited" in card
        # The gate is untouched, which is what made the card wrong rather than weak.
        assert [v.term for v in vocab.check("compounded twice a year", "9-12")] == [
            "compound"
        ]


class TestTheNameIsOneLine:
    @pytest.mark.parametrize("path", ALL_CARDS, ids=lambda path: path.name)
    def test_no_card_hardcodes_a_persona_name(self, path):
        """A client picking a nicer name must not be a fifty-file migration.

        Every card, including the default one. `everyone` used to be exempt
        from carrying the placeholder because it had no label to fill in; it
        introduces itself as Guest now, so the exemption is gone and the rule is
        the same for all seven.
        """
        text = _read(path)
        assert PLACEHOLDER in text
        # `all_labels`, not `NAMES.values()`: a per-band label like Kaleb is a
        # label like any other, and a check that only knew the whole-persona
        # ones would let a card spell it out.
        #
        # Whole words. `Star` is a substring of `Starting`, and `Sky` is a
        # substring of `Skye` -- a retired label that fails the build on the
        # current one is a gate people delete.
        for label in (*all_labels(), *RETIRED_NAMES):
            assert not re.search(rf"\b{re.escape(label)}\b", text)

    @pytest.mark.parametrize("path", CURRICULUM, ids=lambda path: path.name)
    def test_no_curriculum_file_spells_a_retired_name(self, path):
        """The curriculum names the guide directly, so a rename strands it.

        A card writes `{name}` and is rewritten on every read. A check question
        cannot: "Can you tell Sky what saving means" is addressed to a child and
        there is no substitution step on that path, so the label is typed out.
        That is fine until the label changes -- and then it is silent, which is
        how `Skai` outlived the rename that retired it. The current name is
        allowed here precisely because it has to be.

        Whole words here too, since `Sky` was retired in favour of `Skye`: a
        substring check cannot tell a one-letter rename from the name that
        replaced it, and would fail the build on the label the file is now
        supposed to be carrying.
        """
        text = _read(path)
        for label in RETIRED_NAMES:
            assert not re.search(rf"\b{re.escape(label)}\b", text), (
                f"{path.name} still says {label!r}; the personas are now "
                f"{', '.join(sorted(all_labels()))}"
            )

    def test_the_label_is_filled_in_when_the_card_is_read(self):
        assert NAMES["stella"] in persona_card("stella", "5-8")
        assert PLACEHOLDER not in persona_card("stella", "5-8")

    def test_each_child_card_carries_its_own_name(self):
        """Two keys, two cards, two names, and neither leaks into the other.

        Skye is a gentle helper for a child who cannot yet read a rate; Kaleb is
        a dry older cousin who names the EC$500 split and shows the workings.
        Handing the older card the younger name was the mismatch readers noticed
        first, and it survived the card split because the NAME still came from
        `stella`. Kaleb having a key of his own is what finally ends it: the
        label now travels with the card because they are the same persona.
        """
        skye, kaleb = NAMES["stella"], NAMES["kaleb"]
        younger = persona_card("stella", "5-8")
        older = persona_card("kaleb", "9-12")
        assert skye in younger and kaleb not in younger
        assert kaleb in older and skye not in older

    def test_a_rename_touches_one_line_and_no_card(self, monkeypatch):
        from app.prompting.personas import _card_text

        before = NAMES["stella"]
        monkeypatch.setitem(NAMES, "stella", "Cora")
        _card_text.cache_clear()
        card = persona_card("stella", "5-8")
        assert "Cora" in card and before not in card

    def test_a_band_rename_touches_one_line_and_no_card(self, monkeypatch):
        """A per-band label is one line in the same file, on the same terms.

        `BY_BAND` is empty since Kaleb took a key of his own, so this adds the
        entry it tests. The mechanism is still the right one for a persona that
        genuinely carries two voices, and a mechanism with no rows is exactly
        the kind that rots unnoticed -- so it stays under test with a synthetic
        row rather than being deleted along with its last real user.
        """
        from app.prompting.personas import _card_text

        monkeypatch.setitem(BAND_NAMES, ("kaleb", "9-12"), "Renard")
        _card_text.cache_clear()
        card = persona_card("kaleb", "9-12")
        assert "Renard" in card and NAMES["kaleb"] not in card

    def test_a_band_with_no_label_of_its_own_falls_back_to_the_persona(self):
        """Only the pairs that differ are listed; every other pair falls through."""
        assert display_name("stella", "5-8") == NAMES["stella"]
        assert display_name("orion", "16-18") == NAMES["orion"]
        assert display_name("stella", "99-100") == NAMES["stella"]
        assert display_name("stella") == NAMES["stella"]

    def test_every_known_persona_has_a_label(self):
        """`everyone` has one now, and it is a `NAMES` row like the other four.

        It used to be the exception: a persona everywhere else in the codebase
        -- `domain.py`, `access.py`, `state.py` -- but the absence of an
        audience rather than a character, so there was no name for a reader to
        be greeted by. The default card introduces itself as Guest and answers
        before it knows who is reading, which is a voice like the other five.
        Asserting equality keeps the rename guarantee intact: a label with no
        card, or a card with no label, still fails here.
        """
        assert set(NAMES) == set(KNOWN)
        assert display_name("guest") == NAMES["guest"]

    def test_the_key_is_not_the_label(self):
        """`stella` is a database id that happens to be a word."""
        assert all(key != label for key, label in NAMES.items())


class TestTheLoaderPicksTheMostSpecificCard:
    @pytest.mark.parametrize(
        ("persona", "band"), sorted(BAND_CARDS), ids=lambda value: str(value)
    )
    def test_each_pair_gets_its_own_card(self, persona, band):
        """The label is in the TASK paragraph, which is where a card opens."""
        assert (_DIR / BAND_CARDS[(persona, band)]).is_file()
        opening = chr(10).join(persona_card(persona, band).splitlines()[:4])
        assert display_name(persona, band) in opening

    def test_the_six_cards_all_differ(self):
        cards = {persona_card(persona, band) for persona, band in BAND_CARDS}
        assert len(cards) == len(BAND_CARDS)

    def test_an_unknown_band_falls_back_rather_than_raising(self):
        assert persona_card("orion", "99-100").strip()

    def test_an_unknown_band_stays_inside_the_persona(self):
        """A reader must not change persona because somebody added a band."""
        assert NAMES["orion"] in persona_card("orion", "99-100")

    def test_the_undifferentiated_cards_are_gone_and_nothing_needs_them(self):
        """`{persona}.md` was the safety net while the band split landed.

        The six-card rewrite replaced every band card, and the four
        undifferentiated ones had no counterpart in it -- so they would have
        stayed on disk contradicting the cards that replaced them, reachable by
        any reader whose band the loader did not recognise. The step below them
        keeps the property they were there for: an unknown band gets the
        youngest card of the SAME persona, never another persona's.
        """
        assert not list(_DIR.glob("stella.md"))
        for persona in ("stella", "orion", "aurora", "nova"):
            assert not (_DIR / f"{persona}.md").is_file()
            assert persona_card(persona, "99-100").strip()

    def test_an_unknown_persona_gets_the_most_restrictive_card(self):
        assert persona_card("nobody", "9-12") == persona_card(FALLBACK, "9-12")

    def test_no_band_at_all_gets_the_youngest_card(self):
        """Not knowing who is reading has to mean the careful card."""
        assert persona_card("stella") == persona_card("stella", "5-8")

    def test_a_twelve_year_old_is_not_answered_as_a_six_year_old(self):
        """The finding this whole change exists for."""
        assert persona_card("kaleb", "9-12") != persona_card("stella", "5-8")
