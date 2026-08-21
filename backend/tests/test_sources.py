"""URL handling, source naming, and the registry that supplies the words.

The rules being defended here are the ones that make a citation trustworthy: a
URL is either validated or dropped, never repaired; a name comes from stored
data or from the URL itself, never from a model; and two spellings of one page
count as one source.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app import sources
from app.config import get_settings

CORPUS = Path(__file__).resolve().parent.parent / "data" / "knowledge_base.csv"


# ── what may become a link ───────────────────────────────────────────────────


class TestSafeUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://aspire.gov.kn/",
            "https://www.sknis.gov.kn/2024/11/28/a-story/",
            "http://gov.kn/page",
            "https://aspire.gov.kn/#faqs",
        ],
    )
    def test_a_real_public_page_is_linkable(self, url: str):
        assert sources.safe_url(url) is not None

    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "vbscript:msgbox(1)",
            "file:///etc/passwd",
            "internal:aspire-financial-education",
        ],
    )
    def test_a_scheme_that_is_not_the_web_is_refused(self, url: str):
        """The panel renders an `href`; only http and https may reach one."""
        assert sources.safe_url(url) is None

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:8000/admin",
            "https://valkey.internal/keys",
            "https://10.0.0.5/",
            "https://192.168.1.1/status",
            "https://db.local/",
            # The shortened forms of the same machine. A dotted-quad test
            # misses every one of these.
            "https://127.1/",
            "https://127.0.1/",
            "https://0.0.0.0/",
            "https://api.localhost/keys",
            "https://[::1]/",
            "https://[fe80::1]/x",
        ],
    )
    def test_an_internal_address_is_refused(self, url: str):
        """§27: an internal service must never be handed to a reader's browser."""
        assert sources.safe_url(url) is None

    def test_credentials_in_the_authority_are_refused(self):
        """`https://aspire.gov.kn@evil.example` reads as ASPIRE and is not."""
        assert sources.safe_url("https://aspire.gov.kn@evil.example/") is None

    def test_a_percent_encoded_at_sign_does_not_smuggle_one_past(self):
        """`hostname` returns the whole string, so the literal `@` test misses it."""
        assert sources.safe_url("https://aspire.gov.kn%40evil.example/") is None

    def test_a_lookalike_host_is_refused_rather_than_displayed_as_reassurance(self):
        """A Cyrillic `а` in `аspire.gov.kn` reads as the real host and is not it.

        The panel prints the domain precisely as the thing a cautious reader
        checks, so a homograph would be shown as the proof it is safe.
        """
        assert sources.safe_url("https://аspire.gov.kn/faqs") is None

    @pytest.mark.parametrize("url", ["https://.com/x", "https://-.-/x", "https://a..b/x"])
    def test_a_host_with_no_registrable_label_is_refused(self, url: str):
        """These pass a "contains a dot" test and resolve to nothing."""
        assert sources.safe_url(url) is None

    def test_a_hyphenated_host_is_still_fine(self):
        assert sources.safe_url("https://eccb-centralbank.org/") is not None

    @pytest.mark.parametrize(
        "url",
        [
            "knowledge_base.csv",
            "ASPIRE website",
            "https://",
            "https://nodot/",
            "",
            "   ",
        ],
    )
    def test_something_that_is_not_a_url_is_refused(self, url: str):
        assert sources.safe_url(url) is None

    @pytest.mark.parametrize("value", [None, 42, [], {}])
    def test_a_non_string_is_refused_rather_than_coerced(self, value):
        assert sources.safe_url(value) is None

    def test_an_absurdly_long_value_is_refused(self):
        assert sources.safe_url("https://a.example/" + "x" * 3000) is None

    def test_a_high_port_is_refused(self):
        """A public source does not live on 8443; an internal service does."""
        assert sources.safe_url("https://aspire.gov.kn:8443/x") is None

    def test_the_default_port_is_allowed(self):
        assert sources.safe_url("https://aspire.gov.kn:443/x") is not None

    def test_tracking_parameters_are_dropped_from_the_link(self):
        """Removing them cannot change what a server returns."""
        link = sources.safe_url("https://aspire.gov.kn/p?utm_source=x&id=7&fbclid=y")
        assert link == "https://aspire.gov.kn/p?id=7"

    def test_the_link_keeps_www_and_its_trailing_slash(self):
        """§10: the displayed source must still lead to the actual page."""
        given = "https://www.sknis.gov.kn/2024/11/28/a-story/"
        assert sources.safe_url(given) == given

    def test_a_kept_parameter_is_returned_byte_for_byte(self):
        """The rewrite is subtractive. It must not re-encode what it keeps."""
        given = "https://gov.kn/p?q=caf%C3%A9&r=a+b&s=x%2Fy"
        assert sources.safe_url(given) == given

    def test_the_link_never_comes_back_longer_than_it_went_in(self):
        """Decoding and re-encoding EXPANDS, and past the cap the URL is lost.

        A 374-character stored URL came back 2148 characters -- so `safe_url`
        would not accept its own output, and `describe`, which reads the domain
        off that output, lost the site and the page with it.
        """
        given = "https://sknird.com/vat?q=" + "é" * 340
        link = sources.safe_url(given)
        assert link is not None and len(link) <= len(given)

    def test_safe_url_accepts_its_own_output(self):
        for url in [
            "https://aspire.gov.kn/#faqs",
            "https://sknird.com/vat?q=" + "é" * 340,
            "https://www.gov.kn/a/b/?x=1&utm_source=y",
        ]:
            once = sources.safe_url(url)
            assert once is not None
            assert sources.safe_url(once) == once

    def test_a_content_selector_is_not_mistaken_for_tracking(self):
        """`ref` names an edition on a great many sites; dropping it moves the page."""
        a = "https://gov.kn/budget?ref=2025-estimates"
        b = "https://gov.kn/budget?ref=2019-estimates"
        assert sources.safe_url(a) == a
        assert sources.canonical(a) != sources.canonical(b)

    @pytest.mark.parametrize(
        "url",
        [
            "https://" + "a." * 500 + "com/",
            "https://" + "a" * 300 + ".com/",
        ],
    )
    def test_a_hostname_longer_than_dns_allows_is_refused(self, url: str):
        """Every label is valid LDH, and the "domain" is 1003 characters."""
        assert sources.safe_url(url) is None

    def test_a_label_at_the_limit_is_still_fine(self):
        assert sources.safe_url("https://" + "a" * 63 + ".com/") is not None


# ── what counts as the same page ─────────────────────────────────────────────


class TestCanonical:
    @pytest.mark.parametrize(
        "url",
        [
            "https://aspire.gov.kn/program",
            "https://aspire.gov.kn/program/",
            "https://www.aspire.gov.kn/program",
            "http://aspire.gov.kn/program",
            "https://ASPIRE.gov.kn/program",
            "https://aspire.gov.kn/program?utm_campaign=launch",
        ],
    )
    def test_every_spelling_of_one_page_collapses(self, url: str):
        """§9: five chunks off one page are one source."""
        assert sources.canonical(url) == "https://aspire.gov.kn/program"

    def test_a_fragment_is_kept_because_it_names_a_section(self):
        """The corpus cites the homepage AND its FAQ block; they are not one page."""
        assert sources.canonical("https://aspire.gov.kn/#faqs") != sources.canonical(
            "https://aspire.gov.kn/"
        )

    def test_the_root_keeps_its_slash(self):
        assert sources.canonical("https://aspire.gov.kn") == "https://aspire.gov.kn/"

    def test_a_meaningful_query_parameter_survives(self):
        assert sources.canonical("https://x.example/p?id=7") == "https://x.example/p?id=7"

    def test_an_unusable_url_has_no_canonical_form(self):
        assert sources.canonical("javascript:alert(1)") is None


# ── naming ───────────────────────────────────────────────────────────────────


class TestDescribe:
    def test_a_registered_page_gets_its_own_name(self):
        ref = sources.describe({}, stored_url="https://aspire.gov.kn/#faqs")
        assert ref is not None
        assert ref.site == "ASPIRE"
        assert ref.page == "Frequently asked questions"
        assert ref.domain == "aspire.gov.kn"
        assert ref.label == "ASPIRE — Frequently asked questions"

    def test_the_label_never_shows_a_bare_url(self):
        """§11: a reader gets a name, and the URL sits behind the link."""
        ref = sources.describe({}, stored_url="https://unknown.example/eligibility")
        assert ref is not None
        assert "://" not in ref.label
        assert ref.url == "https://unknown.example/eligibility"

    def test_an_unregistered_host_is_named_by_its_domain(self):
        ref = sources.describe({}, stored_url="https://unknown.example/eligibility")
        assert ref is not None
        assert ref.site == "unknown.example"
        assert ref.page == "Eligibility"

    def test_a_page_that_only_restates_its_site_is_not_said_twice(self):
        ref = sources.describe(
            {"source_title": "Jump$tart Coalition"}, stored_url="https://jumpstart.org/"
        )
        assert ref is not None
        assert ref.label == "Jump$tart Coalition"

    def test_a_row_may_override_the_registry_with_its_own_title(self):
        """The extension path: add a `source_title` column and it wins."""
        ref = sources.describe(
            {"source_title": "How to apply, step by step"},
            stored_url="https://aspire.gov.kn/#faqs",
        )
        assert ref is not None
        assert ref.page == "How to apply, step by step"

    def test_material_with_no_public_page_is_named_and_not_linked(self):
        """§6: show the source name without a link rather than inventing one."""
        ref = sources.describe({}, stored_url="internal:eccb-aspire-quiz")
        assert ref is not None
        assert ref.url == ""
        assert ref.domain == ""
        assert ref.label == "ECCB ASPIRE quiz"

    def test_an_unregistered_internal_document_is_still_named(self):
        ref = sources.describe({}, stored_url="internal:some-new-workbook")
        assert ref is not None
        assert ref.url == ""
        assert ref.label == "Some new workbook"

    def test_an_unusable_url_produces_no_source_at_all(self):
        """§6: never a fabricated URL, and never a domain guessed from junk."""
        assert sources.describe({}, stored_url="knowledge_base.csv") is None
        assert sources.describe({}, stored_url="javascript:alert(1)") is None

    def test_a_row_with_no_source_produces_none(self):
        assert sources.describe({}) is None
        assert sources.describe({"question": "What is ASPIRE?"}) is None

    def test_the_stored_column_beats_the_copy_in_the_metadata(self):
        """A corrected column must not be shadowed by the stale JSON beside it."""
        ref = sources.describe(
            {"source_url": "https://aspire.gov.kn/old"},
            stored_url="https://aspire.gov.kn/#faqs",
        )
        assert ref is not None
        assert ref.url == "https://aspire.gov.kn/#faqs"

    def test_the_as_of_date_is_carried(self):
        ref = sources.describe({"as_of": "2026-07-30"}, stored_url="https://aspire.gov.kn/")
        assert ref is not None
        assert ref.updated == "2026-07-30"

    def test_an_unusable_url_is_reported_once_for_developers(self, caplog):
        """§19: missing provenance is a data defect, and it must be visible."""
        sources._REPORTED.discard("a-defect-nobody-has-seen-before")
        with caplog.at_level("WARNING"):
            sources.describe({}, stored_url="a-defect-nobody-has-seen-before")
        assert any("unusable source_url" in record.message for record in caplog.records)


# ── deduplication ────────────────────────────────────────────────────────────


class TestTheKeyThatCollapsesThem:
    """The collapse happens in the renderer; the RULE for it lives here."""

    def test_five_spellings_of_one_page_share_a_key(self):
        keys = {
            sources.describe({}, stored_url=url).key
            for url in [
                "https://aspire.gov.kn/program",
                "https://aspire.gov.kn/program/",
                "https://www.aspire.gov.kn/program",
                "https://aspire.gov.kn/program?utm_source=x",
                "http://aspire.gov.kn/program",
            ]
        }
        assert len(keys) == 1

    def test_different_pages_do_not(self):
        keys = {
            sources.describe({}, stored_url=url).key
            for url in ["https://aspire.gov.kn/", "https://aspire.gov.kn/#faqs"]
        }
        assert len(keys) == 2

    def test_material_with_no_url_keys_on_its_name(self):
        keys = {
            sources.describe({}, stored_url="internal:eccb-aspire-quiz").key
            for _ in range(4)
        }
        assert keys == {"eccb aspire quiz"}

    def test_two_different_documents_key_apart(self):
        assert (
            sources.describe({}, stored_url="internal:eccb-aspire-quiz").key
            != sources.describe({}, stored_url="internal:eccb-aspire-affirmations").key
        )


class TestFieldsAreClippedWhereTheyAreBuilt:
    """`CitationRef` caps these, and it raises from inside the streaming turn."""

    def test_a_page_name_derived_from_a_huge_slug_is_cut(self):
        slug = "-".join(["word"] * 120)
        ref = sources.describe({}, stored_url=f"https://aspire.gov.kn/{slug}")
        assert ref is not None
        assert len(ref.page) <= sources.MAX_PAGE_CHARS

    def test_an_authored_title_far_too_long_is_cut(self):
        ref = sources.describe(
            {"source_title": "x" * 900}, stored_url="https://aspire.gov.kn/"
        )
        assert ref is not None
        assert len(ref.page) <= sources.MAX_PAGE_CHARS

    def test_a_registered_site_name_far_too_long_is_cut(self, tmp_path, monkeypatch):
        registry = tmp_path / "sources.yaml"
        registry.write_text("sites:\n  aspire.gov.kn: " + "y" * 900 + "\n", encoding="utf-8")
        monkeypatch.setattr(sources, "REGISTRY_PATH", registry)
        sources.forget_registry()
        try:
            ref = sources.describe({}, stored_url="https://aspire.gov.kn/")
            assert ref is not None
            assert len(ref.site) <= sources.MAX_SITE_CHARS
        finally:
            sources.forget_registry()

    def test_an_internal_documents_name_is_cut_too(self):
        ref = sources.describe({"source_title": "z" * 900}, stored_url="internal:x")
        assert ref is not None
        assert len(ref.page) <= sources.MAX_PAGE_CHARS

    def test_clipping_keeps_a_short_value_exactly(self):
        assert sources.clip("ASPIRE", 160) == "ASPIRE"

    def test_clipping_cuts_at_a_word_boundary(self):
        assert sources.clip("the quick brown fox jumps", 12) == "the quick…"

    def test_every_corpus_source_is_within_the_wire_caps(self):
        with CORPUS.open(newline="", encoding="utf-8-sig") as handle:
            urls = {(r.get("source_url") or "").strip() for r in csv.DictReader(handle)}
        for url in urls:
            ref = sources.describe({"as_of": "2026-07-30"}, stored_url=url)
            assert ref is not None
            assert len(ref.site) <= sources.MAX_SITE_CHARS
            assert len(ref.page) <= sources.MAX_PAGE_CHARS
            assert len(ref.url) <= sources.MAX_URL_CHARS
            assert len(ref.domain) <= 253


# ── keeping the URL away from the model ──────────────────────────────────────


class TestWithoutProvenance:
    #: A row exactly as `ingest.row_to_document` renders it.
    ROW = (
        "Category: Overview\n"
        "Question: What is the ASPIRE Programme?\n"
        "Answer: ASPIRE is a national financial education initiative.\n"
        "id: ASP-001\n"
        "subcategory: Definition\n"
        "keywords: aspire|what is aspire\n"
        "audience: general\n"
        "source_url: https://aspire.gov.kn/\n"
        "as_of: 2026-07-30"
    )

    def test_the_url_never_reaches_the_prompt(self):
        """§17: the model must not be in a position to reproduce a URL at all."""
        assert "https://" not in sources.without_provenance(self.ROW)
        assert "source_url" not in sources.without_provenance(self.ROW)

    def test_the_as_of_date_goes_too(self):
        """GLOBAL forbids the model surfacing it; it was being shown one anyway."""
        assert "as_of" not in sources.without_provenance(self.ROW)
        assert "2026-07-30" not in sources.without_provenance(self.ROW)

    def test_the_knowledge_survives_untouched(self):
        kept = sources.without_provenance(self.ROW)
        assert "What is the ASPIRE Programme?" in kept
        assert "ASPIRE is a national financial education initiative." in kept
        assert "Category: Overview" in kept
        assert "subcategory: Definition" in kept

    def test_prose_with_no_scaffolding_is_returned_as_it_was(self):
        text = "ASPIRE is open to children aged 5 to 18."
        assert sources.without_provenance(text) == text

    def test_empty_stays_empty(self):
        assert sources.without_provenance("") == ""


# ── the registry against the real corpus ─────────────────────────────────────


class TestRegistryCoversTheCorpus:
    """`data/sources.yaml`'s own header promises this suite checks these."""

    @staticmethod
    def corpus_urls() -> set[str]:
        with CORPUS.open(newline="", encoding="utf-8-sig") as handle:
            return {
                (row.get("source_url") or "").strip()
                for row in csv.DictReader(handle)
                if (row.get("source_url") or "").strip()
            }

    def test_the_registry_parses(self):
        registry = sources.registry()
        assert registry.sites and registry.pages and registry.documents

    def test_every_corpus_source_resolves_to_something_a_reader_can_read(self):
        unresolved = [
            url for url in self.corpus_urls() if sources.describe({}, stored_url=url) is None
        ]
        assert not unresolved, f"these rows would cite nothing: {sorted(unresolved)}"

    def test_no_corpus_source_is_named_by_a_bare_url(self):
        for url in self.corpus_urls():
            ref = sources.describe({}, stored_url=url)
            assert ref is not None
            assert "://" not in ref.label, f"{url} shows a raw URL as its name"

    def test_every_page_entry_is_written_in_canonical_form(self):
        """A `pages:` key that is not canonical can never match, silently."""
        wrong = [
            key
            for key in sources.registry().pages
            if sources.canonical(key) != key
        ]
        assert not wrong, f"not canonical, so they will never match: {wrong}"

    def test_every_registered_document_key_is_an_internal_one(self):
        for key in sources.registry().documents:
            assert key.startswith(sources.DOCUMENT_SCHEME)

    def test_the_corpus_path_the_settings_name_is_the_one_checked_here(self):
        settings = get_settings()
        assert settings.resolved(settings.knowledge_base_csv) == CORPUS


# ── the registry when it is broken ───────────────────────────────────────────


class TestABrokenRegistry:
    """Losing the wording must not lose the citation."""

    def test_a_missing_file_falls_back_to_domains(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sources, "REGISTRY_PATH", tmp_path / "gone.yaml")
        sources.forget_registry()
        try:
            ref = sources.describe({}, stored_url="https://aspire.gov.kn/#faqs")
            assert ref is not None
            assert ref.url == "https://aspire.gov.kn/#faqs"
            assert ref.domain == "aspire.gov.kn"
            assert ref.label
        finally:
            sources.forget_registry()

    def test_invalid_yaml_falls_back_rather_than_raising(self, tmp_path, monkeypatch):
        broken = tmp_path / "sources.yaml"
        broken.write_text("sites: [this is not: a mapping", encoding="utf-8")
        monkeypatch.setattr(sources, "REGISTRY_PATH", broken)
        sources.forget_registry()
        try:
            ref = sources.describe({}, stored_url="https://aspire.gov.kn/")
            assert ref is not None and ref.url
        finally:
            sources.forget_registry()
