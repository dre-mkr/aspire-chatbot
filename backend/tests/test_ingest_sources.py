"""What ingest writes into `documents.source_url`, and what it refuses to write.

Provenance is checked at the door because the alternative is checking it on
every turn that retrieves the row -- and because a value that is neither a URL
nor NULL is one that nothing downstream can reason about.
"""

from __future__ import annotations

import pytest

from app import ingest


def row(**cells: str) -> dict[str, str]:
    """A knowledge-base row in the real CSV's column order."""
    base = {
        "id": "ASP-001",
        "category": "Overview",
        "question": "What is ASPIRE?",
        "answer": "A national financial education programme.",
        "audience": "general",
        "source_url": "https://aspire.gov.kn/",
        "as_of": "2026-07-30",
    }
    base.update(cells)
    return base


def metadata_for(**cells: str) -> dict:
    document = ingest.row_to_document(row(**cells), 2, "knowledge_base.csv")
    assert document is not None
    return dict(document.metadata)


class TestSourceUrlIsCheckedAtTheDoor:
    def test_a_real_url_is_stored_exactly_as_authored(self):
        """§10: the stored value is the one a reader opens."""
        given = "https://www.sknis.gov.kn/2024/11/28/a-story/"
        assert ingest._source_url(metadata_for(source_url=given), "ASP-001") == given

    def test_material_with_no_public_page_is_stored_as_it_is(self):
        stored = ingest._source_url(
            metadata_for(source_url="internal:eccb-aspire-quiz"), "ASP-001"
        )
        assert stored == "internal:eccb-aspire-quiz"

    def test_a_blank_source_url_is_stored_as_null_and_not_as_the_filename(self):
        """The defect this fixes: `_pick` used to fall through to the CSV's name.

        `row_to_document` drops empty cells, so a blank `source_url` was simply
        absent -- and `SOURCE_URL_COLUMNS` contained `source`, the key holding
        the CSV filename. The row was stored citing `knowledge_base.csv`.
        """
        metadata = metadata_for(source_url="")
        assert metadata["source"] == "knowledge_base.csv"
        assert ingest._source_url(metadata, "ASP-001") is None

    def test_a_url_that_will_not_validate_is_stored_as_null(self):
        for junk in ("javascript:alert(1)", "http://localhost:8000/x", "see the website"):
            assert ingest._source_url(metadata_for(source_url=junk), "ASP-001") is None

    def test_a_defective_row_is_logged_by_id(self, caplog):
        with caplog.at_level("WARNING"):
            ingest._source_url(metadata_for(source_url="not a url"), "ASP-042")
        assert any("ASP-042" in record.message for record in caplog.records)

    def test_a_row_naming_no_source_at_all_is_logged(self, caplog):
        with caplog.at_level("WARNING"):
            ingest._source_url({}, "ASP-042")
        assert any("names no source" in record.message for record in caplog.records)


class TestPickReadsTheCallersOrderAndNotTheFiles:
    def test_source_url_wins_over_a_url_column_to_its_left(self):
        """Column order in the CSV must not decide which field is provenance."""
        metadata = {
            "url": "https://wrong.example/",
            "source_url": "https://aspire.gov.kn/",
        }
        assert ingest._pick(metadata, ingest.SOURCE_URL_COLUMNS) == "https://aspire.gov.kn/"

    def test_the_injected_filename_is_no_longer_a_candidate(self):
        assert ingest._pick({"source": "knowledge_base.csv"}, ingest.SOURCE_URL_COLUMNS) is None

    def test_a_key_is_matched_whatever_its_case_and_spacing(self):
        assert ingest._pick({" Source_URL ": "https://x.example/"}, ingest.SOURCE_URL_COLUMNS)

    def test_an_empty_value_falls_through_to_the_next_candidate(self):
        metadata = {"source_url": "  ", "url": "https://aspire.gov.kn/"}
        assert ingest._pick(metadata, ingest.SOURCE_URL_COLUMNS) == "https://aspire.gov.kn/"

    def test_nothing_matching_returns_none(self):
        assert ingest._pick({"question": "q"}, ingest.SOURCE_URL_COLUMNS) is None


class TestTheRowsMetadataKeepsWhatCitationsNeed:
    def test_the_source_url_stays_in_the_stored_metadata(self):
        assert metadata_for()["source_url"] == "https://aspire.gov.kn/"

    def test_the_as_of_date_stays_in_the_stored_metadata(self):
        assert metadata_for()["as_of"] == "2026-07-30"

    def test_a_source_title_column_would_be_carried_without_a_code_change(self):
        """The extension path §4 asks for: add the column, re-ingest, done."""
        from app import sources

        metadata = metadata_for(source_title="How to apply, step by step")
        ref = sources.describe(metadata, stored_url=metadata["source_url"])
        assert ref is not None
        assert ref.page == "How to apply, step by step"

    @pytest.mark.parametrize("column", ["source_url", "as_of", "keywords", "audience", "id"])
    def test_the_bookkeeping_columns_are_in_the_text_and_taken_out_before_the_prompt(
        self, column: str
    ):
        """Why the scrubbing exists: ingest writes all of this into the row's text."""
        from app import sources

        document = ingest.row_to_document(
            row(keywords="aspire|overview"), 2, "knowledge_base.csv"
        )
        assert document is not None
        assert f"{column}:" in document.page_content
        assert f"{column}:" not in sources.without_provenance(document.page_content)
