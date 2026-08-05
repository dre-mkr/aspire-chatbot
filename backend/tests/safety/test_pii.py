"""What the redactor catches, and -- as importantly -- what it leaves alone.

A redactor is judged on both. Every false positive here is a lesson with a hole
in it: "[a phone number]" where the answer said "EC$5 a week" teaches nothing
and looks broken.
"""

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
            # A year alone is age information, not a date of birth. The product
            # already holds an age band and the learning agent reasons about it.
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
        """"my national id is 869 555 0123" is one fact, not two.

        Without the overlap sweep this reports both a national ID and a phone
        number, which would put two different `[collected: ...]` markers in the
        summary for one collected field.
        """
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
        """Replacement runs back-to-front; this is the test that proves it.

        Front-to-back replacement shifts every subsequent offset by the
        difference in length, so the second redaction lands in the wrong place
        and leaves half a value behind.
        """
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
