"""A parent can have six children, and a teacher can take three forms.

Ported from `ASPIRE_multi_child_1.patch`, which was written against an earlier
card format (`ARRIVAL STATES` bullets) and an earlier persona naming. The rules
it asserts are unchanged; only the anchors moved, because these cards state
their arrival states as `IF ... ->` lines and the labels now live in `names.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.prompting.personas.names import NAMES, display_name

CARDS = Path(__file__).resolve().parents[1] / "app" / "prompting" / "personas"

#: Where a card stops giving rules and starts overriding them. Cards end with
#: CARE, and CARE outranks everything written above it, so a new rule that
#: landed below this line would be unreachable in the case that matters most.
#:
#: Imported rather than repeated. The heading text has already changed once --
#: a second copy here is a second thing to update the next time it moves, and
#: the failure it produces looks like a card bug rather than a stale constant.
from tests.test_voices import CARE_MARKER  # noqa: E402


class TestAFamilyIsNotAlwaysOneChild:
    """A parent with six children, which the first version of these cards could not answer.

    The rule said "two children's ages", so a model reading it had no rule at
    all for three -- and `WORD_CAPS["adult"]` is None, so nothing would have
    truncated the result. The failure was never a cut-off reply. It was six
    blocks of text handed to somebody standing up in a kitchen, which fails the
    only constraint the guardian card actually has: four minutes, and it
    survives a screenshot.

    Large families are ordinary in St Kitts and Nevis, and Cassandra is one of
    the personas the client tests against. This is a question that gets asked,
    not an edge case.

    The answer falls out of the data rather than out of a cap. Only three
    guardian guide blocks are written -- 5-8, 9-12 and 13-15 -- and the band
    lookup falls back to the nearest YOUNGER band, so 16-18 resolves to 13-15.
    Six children therefore collapse to at most three blocks however they are
    aged.
    """

    GUARDIAN = CARDS / "aurora.adult.md"
    EDUCATOR = CARDS / "nova.adult.md"

    def test_the_rule_is_not_written_for_exactly_two(self):
        text = self.GUARDIAN.read_text(encoding="utf-8")
        assert "two children's ages are named" not in text, (
            "the arrival state is back to naming a count. A card that says TWO "
            "gives the model nothing to do with six."
        )
        assert "ANY NUMBER OF CHILDREN" in text

    def test_the_guardian_groups_by_band_rather_than_by_child(self):
        text = self.GUARDIAN.read_text(encoding="utf-8")
        assert "GROUP BY AGE BAND, NOT BY CHILD" in text
        assert "three" in text.lower(), (
            "the card must say how many blocks are possible. Three is a fact "
            "about the content, not a style preference: only 5-8, 9-12 and 13-15 "
            "are written, and 16-18 falls back to 13-15."
        )

    def test_the_guardian_settles_eligibility_before_curriculum(self):
        """Six children in St Kitts very likely include one under 5 and one over 18.

        Handing a parent six learning blocks, two of them for children who are
        not in the programme, is worse than saying less.
        """
        text = self.GUARDIAN.read_text(encoding="utf-8")
        assert "SAY WHO IS NOT ELIGIBLE FIRST" in text
        assert "fifth birthday" in text, "the under-5 route is rolling enrolment (ASP-041)"
        assert "5 to 18" in text, "the enrolment range has to be stated (ASP-043)"

    def test_the_thousand_is_never_multiplied_into_a_family_total(self):
        """The bot does not decide who is eligible, so it cannot total the family.

        Same reasoning as "never speculate about whether an application will
        succeed", applied to arithmetic.
        """
        text = self.GUARDIAN.read_text(encoding="utf-8")
        assert "PER ELIGIBLE CHILD" in text
        assert "Never multiply" in text

    def test_the_guardian_does_not_read_a_register_of_somebody_s_children(self):
        text = self.GUARDIAN.read_text(encoding="utf-8")
        assert "DO NOT LIST THEIR NAMES BACK" in text

    def test_the_educator_has_the_same_rule_in_its_own_costume(self):
        """"I take Forms 1, 2 and 3" is the identical shape of question.

        Two forms inside one band are one entry, and a teacher who is given the
        same material twice under two headings finds out, and stops trusting the
        rest of it.
        """
        text = self.EDUCATOR.read_text(encoding="utf-8")
        assert "SEVERAL FORMS OR CLASSES IN ONE MESSAGE" in text
        assert "BY AGE BAND" in text

    @pytest.mark.parametrize(
        ("card", "marker"),
        (
            (GUARDIAN, "ANY NUMBER OF CHILDREN"),
            (EDUCATOR, "SEVERAL FORMS OR CLASSES IN ONE MESSAGE"),
        ),
        ids=("aurora", "nova"),
    )
    def test_the_new_rules_sit_above_care(self, card, marker):
        """CARE is last in every card and overrides everything. Keep it there."""
        text = card.read_text(encoding="utf-8")
        assert text.index(marker) < text.index(CARE_MARKER)


class TestTheDirectoryIsNamedForKeys:
    """Why `aurora.adult.md` is not renamed when the label becomes a new name.

    Asked directly, and worth an assertion rather than a comment, because the
    answer is not obvious from the outside: the filename is a KEY, the key is on
    the session token, and the label is a client's choice that has already moved
    more than once.
    """

    def test_the_card_loader_builds_the_filename_from_the_key(self):
        """If this ever stops being true, renaming a card becomes safe -- and
        this test is the place that says so out loud."""
        for persona in ("aurora", "nova"):
            assert (CARDS / f"{persona}.adult.md").is_file(), (
                f"{persona}.adult.md is gone. The loader resolves "
                "f'{persona}.{band}.md' from the persona key on the session "
                "token, so renaming the file to a display name breaks every "
                "signed-in session, not just the build."
            )

    def test_one_key_carries_two_labels_so_files_cannot_follow_labels(self):
        """`stella` carries one label at 5-8 and another at 9-12. One key, two names.

        A directory named for labels would need two files for one access row.
        """
        assert display_name("stella", "5-8") != display_name("stella", "9-12")
        assert (CARDS / "stella.5-8.md").is_file()
        assert (CARDS / "stella.9-12.md").is_file()

    def test_the_note_lives_in_python_and_not_in_a_card(self):
        """Measured, not assumed. A README.md here fails the card assertions,
        because every *.md beside the loader IS a card."""
        import app.prompting.personas as pkg

        doc = pkg.__doc__ or ""
        assert "NEVER FOR THE NAME" in doc
        for label in NAMES.values():
            assert label not in doc, (
                f"the loader docstring now spells out {label!r}. names.py is the "
                "one place a label lives; a second copy is a second thing to "
                "forget when it changes."
            )
