"""A card must not refuse what the corpus can source.

THE FAILURE THIS EXISTS TO CATCH
    Kaleb's first red line read, until 22 August:

        "NEVER invent an investment allocation. What the EC$500 investment half
         is held in is not published. Say that plainly and name the ASPIRE team."

    It IS published. Four rows in `knowledge_base.csv` answer it, sourced to
    `aspire.gov.kn/#faqs`, which is the programme's own FAQ. So the product was
    holding two contradictory positions at once, and which one a reader met
    depended on whether retrieval fired.

    Both outcomes are bad, and in opposite directions. Refuse, and a guide looks
    less informed than it is while pointing at a team who will read the answer
    off the public page. Answer, and it has just broken the red line its own
    card sets -- and Zion's "I am not going to guess", which is the single most
    trust-building line in the product, becomes untrue in the other direction.
    Either way `facts_do_not_move` is broken: two voices, one question, two
    answers.

    Nothing failed. No test knew the cards and the corpus were separate claims
    about the same world.

WHAT THE RULE ACTUALLY IS
    Never INVENT. Not "never discuss". The corpus decides which applies: a row
    with a `source_url` is published and may be given; a question with no row is
    a refusal, named plainly, with the ASPIRE team as the route.

    So this file checks the two halves against each other. If the programme ever
    withdraws the published answer, the first test fails and tells you to put
    the refusal back -- which is the same guard, pointing the other way.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

_CARDS = Path(__file__).resolve().parents[1] / "app/prompting/personas"
_CORPUS = Path(__file__).resolve().parents[1] / "data/knowledge_base.csv"

#: Phrasings a card uses to declare something off-limits as UNPUBLISHED.
#: Deliberately narrow: the general "say what is not published" instruction is
#: correct and must keep passing. What is caught is a card naming a SUBJECT and
#: asserting the programme has not published it.
_DECLARES_UNPUBLISHED = re.compile(
    r"(?:is|are)\s+not\s+published|not\s+published\s+anywhere", re.IGNORECASE
)

#: How far back to look for the subject of that claim.
#:
#: CARDS ARE HARD-WRAPPED at about ninety characters, which is why this reads a
#: NORMALISED card rather than its lines. The first version of this test scanned
#: line by line and passed against the exact defect it was written for: the
#: offending sentence broke as
#:
#:     "...What the EC$500 investment half is held in is"
#:     "not published. Say that plainly..."
#:
#: so no single line contained "is not published" and nothing matched. A test
#: that cannot fail on its own regression is worse than no test, because it is
#: also a claim that the thing is covered.
_SUBJECT_WINDOW = 160


def _normalised(text: str) -> str:
    """The card as one line, so a wrapped sentence reads as a sentence."""
    return re.sub(r"\s+", " ", text)


def _rows() -> list[dict[str, str]]:
    with _CORPUS.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _cards() -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8") for path in _CARDS.glob("*.md")}


class TestTheInvestmentHalfIsPublished:
    """The specific case, kept by name so the regression has one."""

    def test_the_corpus_answers_what_the_ec500_buys(self):
        answering = [
            row
            for row in _rows()
            if re.search(r"invest", row["question"], re.I)
            and re.search(r"share|entit|enterprise|allocat", row["answer"], re.I)
        ]
        assert answering, (
            "no row answers what the EC$500 investment half buys. If the "
            "programme has withdrawn that from its FAQ, the cards' refusal has "
            "to go back -- see this module's docstring."
        )

    def test_every_such_row_carries_a_source(self):
        """Published means checkable. A row without a source is not an answer
        any voice may give at any band."""
        for row in _rows():
            assert row["source_url"].strip(), f"unsourced row: {row['id']}"

    def test_no_card_declares_the_investment_half_unpublished(self):
        offenders = []
        for name, text in _cards().items():
            flat = _normalised(text)
            for hit in _DECLARES_UNPUBLISHED.finditer(flat):
                # Only claims ABOUT this subject; the general instruction to say
                # what is unpublished is correct and stays.
                # The subject must be in the SAME SENTENCE as the claim. A flat
                # character window catches Imani's enrolment-document line,
                # which sits a hundred characters after an unrelated mention of
                # the EC$500 split and is entirely correct.
                sentence_start = max(
                    flat.rfind(". ", 0, hit.start()) + 1,
                    hit.start() - _SUBJECT_WINDOW,
                )
                before = flat[sentence_start : hit.start()]
                if re.search(r"invest|EC\$ ?500", before, re.I):
                    context = flat[
                        max(0, hit.start() - 90) : hit.end() + 20
                    ].strip()
                    offenders.append(f"{name}: ...{context}...")
        assert not offenders, (
            "a card still refuses what aspire.gov.kn publishes and the corpus "
            "sources:\n  " + "\n  ".join(offenders)
        )


class TestTheGeneralHonestyRuleSurvives:
    """Lifting one refusal must not lift the principle behind it."""

    @pytest.mark.parametrize(
        "card", ["orion.13-15.md", "orion.16-18.md", "aurora.adult.md"]
    )
    def test_the_card_still_promises_to_name_what_is_missing(self, card):
        text = _cards()[card]
        assert re.search(r"not\s+published", text, re.IGNORECASE), (
            f"{card} no longer promises to name an unpublished gap. That "
            f"instruction is the reason a refusal reads as honesty rather than "
            f"as a hole, and it is not what the 22 Aug revision removed."
        )

    def test_no_card_invites_invention(self):
        """The half of the rule that never changes."""
        for name, text in _cards().items():
            if "invent" in text.lower():
                assert re.search(r"never\s+invent", text, re.IGNORECASE), (
                    f"{name} mentions inventing without forbidding it"
                )
