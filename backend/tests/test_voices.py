"""The six voices, asserted rather than reviewed.

The register spec is written numerically -- "sentences under twelve words"
instead of "sound like a child" -- for one reason: the first is testable and the
second is an opinion that drifts every time somebody edits a card.

WHAT THIS FILE CHECKS
    The rules that quietly stop being true six edits later, not whether a card is
    well written. A person has to read for that.

THE ONE THAT MATTERS MOST
    `TestTheGateAgrees`. Five different readers ask the same question -- when can
    I get my money -- and the client caught this product answering it two
    different ways on two different days. The rule is published:

        "Participants must remain in the programme for a minimum of 5 years or
         until they turn 18, whichever is later."   -- aspire.gov.kn

    Every card that mentions it has to say the same thing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.prompting.personas import KNOWN, persona_card
from app.prompting.personas.names import (
    BY_BAND,
    NAMES,
    PLACEHOLDER,
    display_name,
    every_label,
)

CARDS = Path(__file__).resolve().parents[1] / "app" / "prompting" / "personas"
FILES = sorted(CARDS.glob("*.md"))

CARE_MARKER = "CARE OVERRIDES EVERYTHING ABOVE"

#: Everything a refusal must be able to hand off to.
#:
#: The PLACEHOLDERS, not the values. ASPIRE's own address and number come from
#: settings and are substituted into the card by `prompting.builder._fill_card`,
#: so a card carrying the literals would be a second place saying the phone
#: number — and `test_prompt_layers` fails a card that does. The Ministry below
#: is different: it is another organisation's number, not a deployment setting,
#: and it is written out.
CONTACT = ("{email}", "{phone}")

#: The official route for an adult, when CARE fires. Real, published, and not
#: something we made up: the Ministry with responsibility for child protection.
SAFEGUARDING = ("Ministry of Social Development", "(869) 467-1275")

#: The voices that must never carry a number a reader cannot check.
NO_FIGURES = (("stella", "5-8"), ("guest", "13-15"))

#: Every band above the youngest. An exclamation mark on a fact reads to these
#: readers as either a sales pitch or a small child.
NO_EXCLAMATION = (
    ("kaleb", "9-12"), ("orion", "13-15"), ("orion", "16-18"),
    ("aurora", "adult"), ("nova", "adult"), ("guest", "13-15"),
)


def care_block(text: str) -> str:
    _, marker, tail = text.partition(CARE_MARKER)
    return (marker + tail).strip() if marker else ""


#: Where a card stops saying what it MAY say and starts saying what it may not.
#: Two spellings, because the cards were restructured after this file was first
#: written and the section is now called RED LINES. Both are matched rather than
#: one renamed, so a card on either shape is still checked.
PROHIBITIONS = ("WHAT YOU NEVER SAY", "RED LINES")


def permitted_part(card: str) -> str:
    """The card minus its prohibitions.

    A card that bans a word has to name it, so the ladder is checked against the
    part telling the assistant what it MAY say. Without this split every
    prohibition reads as a violation of itself.
    """
    for heading in PROHIBITIONS:
        if heading in card:
            return card.split(heading)[0]
    return card


class TestCareIsEverywhereAndIsTheSame:
    """The override that outranks the persona. It cannot vary by card.

    A child saying something hard to a chatbot is a thing that will happen. If
    one card handles it and another stays in a cheerful savings register, that is
    not a style inconsistency -- it is which reader got looked after.
    """

    @pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
    def test_every_card_has_a_care_block(self, path):
        assert CARE_MARKER in path.read_text(encoding="utf-8"), (
            f"{path.name} has no CARE block. Distress does not check which "
            "persona it arrived at."
        )

    def test_every_care_block_is_identical(self):
        blocks = {p.name: care_block(p.read_text(encoding="utf-8")) for p in FILES}
        first_name, first = next(iter(blocks.items()))
        for name, block in blocks.items():
            assert block == first, (
                f"{name} has a CARE block that differs from {first_name}. Six "
                "variants of a safeguarding instruction is six behaviours."
            )

    @pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
    def test_care_takes_no_details(self, path):
        block = care_block(path.read_text(encoding="utf-8")).lower()
        assert "no follow-up questions" in block
        assert "take no details" in block, (
            "the failure mode is a bot trying to help and collecting what it "
            "must never hold. It has to be explicit."
        )

    @pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
    def test_care_says_in_any_language(self, path):
        """A reader in distress may be writing in Spanish or French.

        `detect_language` runs before the card is assembled, so the locale is
        known -- but an instruction written in English is not automatically
        applied to a message written in Spanish. The card has to say so.
        """
        assert "in any language" in care_block(path.read_text(encoding="utf-8")).lower()

    @pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
    def test_care_names_a_real_route(self, path):
        block = care_block(path.read_text(encoding="utf-8"))
        for item in SAFEGUARDING:
            assert item in block, (
                f"{path.name}: CARE must name an official route an adult can "
                f"actually call. Missing {item!r}."
            )


class TestTheGateAgrees:
    """The withdrawal rule is published. No card may state a different one."""

    #: Durations that are not the published rule. `5 years` and `18` are correct;
    #: anything else in the same breath is a card inventing a number.
    A_WRONG_DURATION = re.compile(
        r"\b(?:three|four|six|seven|eight|nine|ten|twenty|twenty-one|21|3|4|6|7|8|9|10)\s+years?\b"
        r"|\bage(?:d)?\s+(?:16|17|19|20|21)\b",
        re.IGNORECASE,
    )

    @pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
    def test_no_card_invents_a_different_duration(self, path):
        text = path.read_text(encoding="utf-8")
        hit = self.A_WRONG_DURATION.search(text)
        assert not hit, (
            f"{path.name} contains {hit.group(0)!r}. The published rule is five "
            "years or eighteen, whichever is later. A card carrying a different "
            "number is how one question gets two answers on two days."
        )

    @pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
    def test_a_card_that_states_the_rule_states_all_of_it(self, path):
        text = path.read_text(encoding="utf-8").lower()
        if "five years" not in text and "minimum of 5 years" not in text:
            return
        assert "eighteen" in text or " 18" in text, (
            f"{path.name} gives the five-year half of the rule without the age "
            "half. Half the rule is how a sixteen-year-old is told the wrong year."
        )
        assert "later" in text, (
            f"{path.name} states both halves without saying WHICHEVER IS LATER. "
            "That is the part readers get wrong: joining at sixteen means "
            "twenty-one, not eighteen."
        )

    @pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
    def test_every_card_can_hand_off_to_a_human(self, path):
        text = path.read_text(encoding="utf-8")
        for item in CONTACT:
            assert item in text, (
                f"{path.name} is missing {item!r}. Every refusal here ends with "
                "a named human, or it is just a refusal."
            )


class TestTheVoicesWithoutFigures:
    """Skye and Guest withhold numbers on purpose, not by accident."""

    A_FIGURE = re.compile(
        r"\d+\s?(?:%|per cent|percent)|\brates?\b|\bpercentages?\b", re.IGNORECASE
    )

    @pytest.mark.parametrize("persona, band", NO_FIGURES, ids=lambda v: str(v))
    def test_no_rate_or_percentage_in_what_it_may_say(self, persona, band):
        hit = self.A_FIGURE.search(permitted_part(persona_card(persona, band)))
        assert not hit, (
            f"{persona} at {band} may say {hit.group(0)!r}. This reader cannot "
            "check a figure and does not need one."
        )

    def test_the_refusal_names_itself_as_a_choice(self):
        """A refusal that sounds like a gap is scored as a gap.

        The youngest band declines to give a number. A judge scoring accuracy
        will ask it for one, and cannot tell a decision from an absence unless
        the card makes it say which.
        """
        assert "rather than something you do not know" in persona_card("stella", "5-8"), (
            "Skye refuses a number without saying why. To a judge that is "
            "indistinguishable from not having the answer."
        )


class TestTheTwoChildVoicesAreTwoPeople:
    def test_the_youngest_band_is_skye(self):
        card = persona_card("stella", "5-8")
        assert "Skye" in card and "Kaleb" not in card

    def test_the_older_child_band_is_kaleb(self):
        card = persona_card("kaleb", "9-12")
        assert "Kaleb" in card, (
            "a twelve-year-old is being introduced to the five-year-old's voice. "
            "That is the one-way door: they do not complain, they leave."
        )
        assert "Skye" not in card

    def test_the_older_child_band_starts_at_the_older_end(self):
        assert "older end" in persona_card("kaleb", "9-12").lower(), (
            "without this instruction the 9-12 card reads as a softened 5-8 "
            "card, and the top of that band is a secondary-school reader."
        )

    def test_by_band_only_covers_the_split_that_is_documented(self):
        """A reminder to delete this map when the key is split properly.

        Only the pair that DIFFERS is listed. Pinning `("stella", "5-8")` here
        too would be tidier to read and would break the guarantee `names.py`
        exists for — `test_a_rename_touches_one_line_and_no_card` fails the
        moment both bands are pinned, because renaming `NAMES["stella"]` then
        changes no card at all.
        """
        # EMPTY NOW, AND THAT IS THE ASSERTION. Kaleb was the only entry, and
        # being a band label rather than a key was exactly what this split
        # fixed: `BY_BAND` cannot reach access, the games, the token or the
        # anonymous default, so a reader who chose Kaleb was a `stella` reader
        # everywhere except the greeting. The mechanism stays for a future
        # genuine two-voice persona; nothing uses it today.
        assert set(BY_BAND) == set()
        assert display_name("stella", "5-8") == NAMES["stella"]


class TestTheDefaultVoice:
    """Guest is what a judge meets before saying who they are."""

    def test_guest_is_known_and_introduces_itself_by_name(self):
        """Guest names the absence of an AUDIENCE. It is still a voice.

        This asserted `display_name("guest") == ""` when it was written, on the
        reasoning that Guest is not a character. The card shipped in the same
        change disagrees with that in its second line -- `guest.md` opens "You
        are {name}" and then "Your name is {name}." -- so an empty label puts
        "You are  —" and "Your name is ." into the system prompt of the one
        persona a judge meets first. The label is what the picker already calls
        it, and `KNOWN` still carries `guest` explicitly so a genuinely nameless
        persona stays one line away.
        """
        assert "guest" in KNOWN
        assert display_name("guest") == "Guest"
        assert PLACEHOLDER not in persona_card("guest", "13-15")

    def test_guest_never_guesses_an_age(self):
        card = persona_card("guest", "13-15").lower()
        assert "do not guess" in card
        assert "both directions" in card, (
            "Guest must be told why: a wrong guess fails as a child shown adult "
            "content AND as an adult addressed as a five-year-old."
        )


class TestNoExclamationOnFacts:
    @pytest.mark.parametrize("persona, band", NO_EXCLAMATION, ids=lambda v: str(v))
    def test_the_card_carries_none(self, persona, band):
        assert "!" not in persona_card(persona, band), (
            f"{persona} at {band} contains an exclamation mark."
        )


class TestTheNames:
    def test_the_labels_are_distinct(self):
        labels = every_label()
        assert len(labels) == len(set(labels))

    def test_one_name_over_both_teen_rungs(self):
        assert display_name("orion", "13-15") == display_name("orion", "16-18") == "Zion"

    def test_the_band_only_matters_where_it_is_declared(self):
        assert display_name("stella") == NAMES["stella"]
        assert display_name("stella", "5-8") == "Skye"
        assert display_name("kaleb", "9-12") == "Kaleb"

    def test_an_unknown_key_does_not_raise_at_a_reader(self):
        assert display_name("nobody") == ""


# ── the citation a reader can actually check ─────────────────────────────────


class TestACitationCarriesItsSource:
    """Sybil Welsh, 18 August at 57:23, looking at the sources panel:

        "That is just showing me the link, but it is not taking me to the source."

    Every row in the corpus already carries a `source_url`. It was simply never
    carried out to the panel, so a reader saw a row id and a snippet and had no
    way to check anything.
    """

    def test_the_citation_model_has_somewhere_to_put_it(self):
        from app.graph.state import Citation

        cited = Citation(kb_id="ASP-001", source_url="https://aspire.gov.kn/")
        assert cited.source_url == "https://aspire.gov.kn/"

    def test_it_survives_the_trip_to_the_wire(self):
        from app.schemas.directives import CitationRef

        ref = CitationRef(kb_id="ASP-001", source_url="https://aspire.gov.kn/")
        assert ref.model_dump()["source_url"] == "https://aspire.gov.kn/"

    def test_a_row_without_one_is_empty_rather_than_absent(self):
        """A claim a reader cannot check should LOOK different from one they can.

        Empty rather than missing, so the front end can render the difference
        instead of having to guess at it.
        """
        from app.schemas.directives import CitationRef

        assert CitationRef(kb_id="FIN-001").source_url == ""

    def test_every_row_in_the_corpus_has_one_to_carry(self):
        import csv
        from pathlib import Path

        kb = Path(__file__).resolve().parents[1] / "data" / "knowledge_base.csv"
        rows = list(csv.DictReader(kb.open(encoding="utf-8-sig")))
        missing = [r["id"] for r in rows if not (r.get("source_url") or "").strip()]
        assert not missing, (
            f"{len(missing)} rows have no source_url, starting {missing[:5]}. "
            "Every claim this product makes has to be traceable to a page."
        )
