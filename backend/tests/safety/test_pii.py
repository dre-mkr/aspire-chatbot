"""What the redactor catches, and -- as importantly -- what it leaves alone."""

from __future__ import annotations

import pytest

from app.safety import pii


class TestDetection:
    @pytest.mark.parametrize(
        ("text", "kind"),
        [
            ("Write to rachel.smith@example.com today", "email"),
            ("Call 869-555-0123", "phone"),
            ("Call +1 869 465 2521 now", "phone"),
            ("(869) 465-2521 is the office", "phone"),
            ("My national ID is A12345678", "national_id"),
            ("id number: 5512340987", "national_id"),
            ("Her SSN is 123-45-6789", "national_id"),
            ("account number 1234 5678 9012", "account_number"),
            ("She was born 14/03/2015", "date_of_birth"),
            ("born on March 14, 2015", "date_of_birth"),
            ("born 14 March 2015", "date_of_birth"),
            ("2015-03-14 is the date", "date_of_birth"),
            ("I live at 12 Cayon Street", "street_address"),
            ("at 5 Victoria Road, Basseterre", "street_address"),
        ],
    )
    def test_it_finds(self, text, kind):
        assert kind in pii.kinds_in(text), f"{kind!r} not found in {text!r}"

    @pytest.mark.parametrize(
        "text",
        [
            # A year alone is age information, not a date of birth.
            "I was born in 2015 and I am 10 now.",
            # Money, in every form the curriculum uses.
            "Save EC$5 a week and you will have EC$260 in a year.",
            "That costs 42 dollars.",
            "You saved 1250 cents.",
            # Knowledge-base row ids ride on every cited answer.
            "ASP-042 explains who can apply.",
            # A percentage is a number, not an identifier.
            "The rate is 5% a year.",
            # Ordinary prose with digits in it.
            "There are 30 days in September and 12 months in a year.",
            "Lesson 3, question 2 of 4.",
            "",
        ],
    )
    def test_it_leaves_alone(self, text):
        assert pii.kinds_in(text) == [], f"false positive in {text!r}"

    def test_overlaps_are_reported_once(self):
        """"my national id is 869 555 0123" is one fact, not two."""
        spans = pii.detect("my national id is 8695550123")
        assert len(spans) == 1
        assert spans[0].kind == "national_id"


class TestRedaction:
    def test_redact_leaves_a_readable_sentence(self):
        out = pii.redact("Email rachel@example.com or call 869-555-0123.")
        assert "rachel@example.com" not in out
        assert "869-555-0123" not in out
        assert out == "Email [an email address] or call [a phone number]."

    def test_redact_for_summary_names_the_field_and_nothing_else(self):
        out = pii.redact_for_summary("Her DOB is 14/03/2015 and ID is A12345678.")
        assert "14/03/2015" not in out
        assert "A12345678" not in out
        assert "[collected: date_of_birth]" in out
        assert "[collected: national_id]" in out

    def test_multiple_spans_do_not_corrupt_each_others_offsets(self):
        """Replacement runs back-to-front; this is the test that proves it."""
        text = (
            "a@b.com then 869-555-0123 then 14/03/2015 then "
            "c@d.com then 12 Main Street"
        )
        out = pii.redact(text)
        for leaked in ("a@b.com", "869-555-0123", "14/03/2015", "c@d.com", "12 Main Street"):
            assert leaked not in out

    def test_clean_text_is_returned_unchanged_and_identical(self):
        text = "Saving means keeping money for later."
        assert pii.redact(text) is text
        assert pii.redact_for_summary(text) is text

    def test_redact_all_maps_the_summary_form(self):
        assert pii.redact_all(["a@b.com", "clean"]) == [
            "[collected: email]",
            "clean",
        ]


class TestAPublishedDateIsNotSomebodysBirthday:
    """The programme's own history was leaving here as "[a date of birth]"."""

    HISTORY = [
        "The ASPIRE Bill, 2024 passed in the National Assembly on 28 November 2024.",
        "ASPIRE was announced at the Independence 41 rally on 13 September 2024.",
        "The scheme opened on 2025-05-08 and closed on 14 May 2025.",
        "Independence was gained on 19 September 1983.",
    ]

    BIRTHDAYS = [
        "The child was born on 14 March 2015.",
        "My date of birth is 14/03/2015.",
        "DOB: 2015-03-14",
        "Her birthday is March 14, 2015.",
        "born 2015-03-14",
    ]

    @pytest.mark.parametrize("text", HISTORY)
    def test_outbound_keeps_a_date_with_no_owner(self, text):
        assert pii.redact(text, outbound=True) == text
        assert "date_of_birth" not in pii.kinds_in(text, outbound=True)

    @pytest.mark.parametrize("text", BIRTHDAYS)
    def test_outbound_still_removes_a_real_one(self, text):
        out = pii.redact(text, outbound=True)
        assert "[a date of birth]" in out
        assert "2015" not in out
        assert "date_of_birth" in pii.kinds_in(text, outbound=True)

    @pytest.mark.parametrize("text", HISTORY + BIRTHDAYS)
    def test_a_summary_still_redacts_every_date(self, text):
        """Into a record that outlives the chat, over-redaction is the cheap error."""
        assert "date_of_birth" in pii.kinds_in(text)

    def test_the_cue_survives_so_the_sentence_still_reads(self):
        out = pii.redact("The child was born on 14 March 2015.", outbound=True)
        assert out == "The child was born on [a date of birth]."

    def test_the_corpus_no_longer_loses_its_dates(self):
        """Measured against the real knowledge base, not a sample."""
        import csv
        from pathlib import Path

        rows = list(
            csv.DictReader(
                (Path(__file__).parents[2] / "data" / "knowledge_base.csv").open(
                    encoding="utf-8"
                )
            )
        )
        assert rows, "the corpus must be readable for this test to mean anything"

        eaten = [
            (row.get("id", "?"), blob)
            for row in rows
            for blob in (" ".join(str(value) for value in row.values()),)
            if "date_of_birth" in pii.kinds_in(blob, outbound=True)
        ]
        assert not eaten, (
            f"{len(eaten)} corpus rows still lose a date outbound, e.g. "
            f"{eaten[0][0]}. A published date is not personal data."
        )
