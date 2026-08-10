"""Phase 1 smoke checks."""

from fastapi.testclient import TestClient

from app.ingest import row_to_document
from app.main import app


def test_health_returns_ok():
    # Used outside a context manager, TestClient skips the lifespan, so this touches neither the embedding model no…
    response = TestClient(app).get("/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    # The probe also reports whether the data layer connected, so a deployment that fell back to in-process memory…
    assert set(body) >= {"status", "database", "cache", "cache_stats"}


def test_row_to_document_formats_qa_columns():
    row = {"question": "What is ASPIRE?", "answer": "A skills program.", "category": "Overview"}
    document = row_to_document(row, row_number=2, source="kb.csv")

    assert document is not None
    assert "Question: What is ASPIRE?" in document.page_content
    assert "Answer: A skills program." in document.page_content
    assert document.metadata["category"] == "Overview"
    assert document.metadata["row"] == 2
    assert document.metadata["source"] == "kb.csv"


def test_row_to_document_falls_back_for_unknown_schema():
    row = {"policy_name": "Deferral", "details": "Defer once before week eight."}
    document = row_to_document(row, row_number=5, source="kb.csv")

    assert document is not None
    assert "policy_name: Deferral" in document.page_content
    assert "details: Defer once before week eight." in document.page_content


def test_row_to_document_skips_empty_rows():
    assert row_to_document({"question": "", "answer": "   "}, 9, "kb.csv") is None


# `_extract_sources` and `_extract_reply` were tested here.
