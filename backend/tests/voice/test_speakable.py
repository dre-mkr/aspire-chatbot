"""speakable() is the highest-leverage piece of the voice layer, so it carries the most tests."""

import pytest

from app.voice.registry import Language
from app.voice.speakable import has_many_numbers, speakable

EN, ES, FR = Language.EN, Language.ES, Language.FR


# --- markdown ------------------------------------------------------------


def test_strips_headings_and_bullets():
    out = speakable("## Eligibility\n\n- Aged five\n- Attending school", EN)
    assert "#" not in out
    assert "-" not in out
    assert "Eligibility" in out and "Aged five" in out


def test_strips_emphasis_but_keeps_words():
    out = speakable("ASPIRE is **free** and _open_ to all.", EN)
    assert "*" not in out and "_" not in out
    assert "free" in out and "open" in out


def test_strips_code_fences_and_inline_code():
    out = speakable("Before\n```python\nprint('x')\n```\nAfter `inline` end.", EN)
    assert "print" not in out and "```" not in out and "`" not in out
    assert "Before" in out and "After" in out


def test_strips_tables():
    out = speakable("Fees:\n\n| Item | Cost |\n|------|------|\n| Fee | $500 |\n\nDone.", EN)
    assert "|" not in out
    assert "Fees" in out and "Done" in out


def test_strips_blockquote_and_horizontal_rule():
    out = speakable("> quoted line\n\n---\n\nnormal line", EN)
    assert ">" not in out and "---" not in out
    assert "quoted line" in out and "normal line" in out


# --- citations, sources, links -------------------------------------------


@pytest.mark.parametrize("marker", ["[ASP-001]", "[kb-012]", "[web-about-1]", "[3]", "[^2]"])
def test_removes_citation_markers(marker):
    out = speakable(f"Joining is free. {marker} That is confirmed.", EN)
    assert "[" not in out and "]" not in out
    assert "ASP" not in out and "kb-" not in out


def test_removes_urls_emails_and_bare_domains():
    out = speakable(
        "See https://aspire.gov.kn/apply or portal.aspire.gov.kn/register, "
        "or write to info@aspire.gov.kn.",
        EN,
    )
    for fragment in ("http", "aspire.gov.kn", "@", "portal."):
        assert fragment not in out


def test_url_removal_leaves_no_dangling_connector():
    out = speakable("Apply online at https://portal.aspire.gov.kn/register.", EN)
    assert not out.rstrip(".").endswith(("at", "on", "via"))
    assert "Apply online" in out


def test_markdown_link_keeps_its_label():
    out = speakable("Read the [eligibility rules](https://aspire.gov.kn/rules).", EN)
    assert "eligibility rules" in out
    assert "http" not in out and "(" not in out


# --- numbers: the trap Flash cannot solve for us -------------------------


@pytest.mark.parametrize(
    ("language", "expected"),
    [(EN, "five hundred dollars"), (ES, "quinientos dólares"), (FR, "cinq cents dollars")],
)
def test_currency_in_each_language(language, expected):
    assert expected in speakable("It costs $500.", language)


def test_ec_currency_is_named_in_full():
    assert "Eastern Caribbean dollars" in speakable("EC$500 per child.", EN)
    assert "Caribe Oriental" in speakable("EC$500 per child.", ES)
    assert "Caraïbes orientales" in speakable("EC$500 per child.", FR)


def test_currency_with_cents():
    out = speakable("EC$1,000.50 is contributed.", EN)
    assert "one thousand" in out
    assert "fifty cents" in out
    assert not any(character.isdigit() for character in out)


@pytest.mark.parametrize(
    ("language", "expected"),
    [(EN, "five to eighteen"), (ES, "cinco a dieciocho"), (FR, "cinq à dix-huit")],
)
def test_age_range_in_each_language(language, expected):
    assert expected in speakable("Open to children aged 5-18.", language)


def test_en_dash_range_is_handled():
    assert "five to eighteen" in speakable("Ages 5–18 qualify.", EN)


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        (EN, "thirteen December"),
        (ES, "trece de diciembre"),
        (FR, "treize décembre"),
    ],
)
def test_worded_date_in_each_language(language, expected):
    assert expected in speakable("Announced on 13 December 2023.", language)


def test_iso_date_is_not_read_as_a_range():
    out = speakable("Last checked 2024-09-13.", EN)
    assert "September" in out
    # "2024-09" must not become "two thousand and twenty-four to nine"
    assert " to " not in out


def test_month_first_date():
    assert "December" in speakable("Announced on December 13, 2023.", EN)


def test_french_first_of_month_uses_premier():
    assert "premier" in speakable("Le 1 décembre 2023.", FR)


@pytest.mark.parametrize(
    ("language", "expected"),
    [(EN, "five percent"), (ES, "cinco por ciento"), (FR, "cinq pour cent")],
)
def test_percentage_in_each_language(language, expected):
    assert expected in speakable("About 5% remain.", language)


def test_thousands_separator_and_decimal():
    out = speakable("The figure is 1,000.5 exactly.", EN)
    assert "one thousand" in out and "point" in out
    assert "1,000" not in out


def test_no_bare_digits_survive_the_brief_case():
    """A dollar amount, an age range and a date, in all three languages."""
    text = "EC$500 for ages 5-18, announced 13 December 2023."
    for language in (EN, ES, FR):
        out = speakable(text, language)
        assert not any(character.isdigit() for character in out), (language, out)


# --- shaping -------------------------------------------------------------


def test_collapses_whitespace():
    assert "  " not in speakable("Too     much\n\n\nspace   here.", EN)


def test_truncates_at_a_sentence_boundary():
    text = " ".join(f"Sentence number {n} is here." for n in range(1, 60))
    out = speakable(text, EN, max_chars=200)
    assert len(out) <= 200
    assert out.endswith(".")


def test_truncation_never_splits_a_word():
    out = speakable("supercalifragilistic " * 40, EN, max_chars=100)
    assert len(out) <= 101
    assert "supercalifragilisti." not in out


def test_empty_input_returns_empty():
    assert speakable("", EN) == ""
    assert speakable("   \n  ", EN) == ""


def test_accepts_language_as_string():
    assert speakable("It costs $500.", "es") == speakable("It costs $500.", ES)


def test_has_many_numbers():
    assert has_many_numbers("EC$500 for ages 5-18")
    assert not has_many_numbers("No figures here at all")
