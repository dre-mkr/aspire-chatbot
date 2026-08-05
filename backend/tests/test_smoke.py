"""Phase 1 smoke checks.

Deliberately small: these cover the pieces that break silently (CSV mapping,
source extraction) plus /health. They do not call the LLM, so they run without
an API key.

    uv run pytest
"""

from fastapi.testclient import TestClient

from app.ingest import row_to_document
from app.main import app


def test_health_returns_ok():
    # Used outside a context manager, TestClient skips the lifespan, so this
    # touches neither the embedding model nor the chat model.
    response = TestClient(app).get("/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    # The probe also reports whether the data layer connected, so a deployment
    # that fell back to in-process memory is visible rather than merely slower.
    # Asserted by key rather than whole-dict equality: this payload is expected
    # to grow, and a probe should not break because it learned to say more.
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


# `_extract_sources` and `_extract_reply` were tested here. Both were `/chat`
# helpers -- one read a ContextVar the retriever tool filled, the other pulled
# the last AIMessage's text out of an agent result -- and both are gone with the
# endpoint.
#
# What replaced them, and where each is tested:
#
#   citations   `agents/qa/nodes.py::ground_check`, which does far more than
#               deduplicate: an answer citing a row that was not retrieved is an
#               `invented_citation` escalation rather than a source list.
#               -> tests/agents/test_qa_grounding.py
#   the reply   `StreamInterceptor.prose`, accumulated as tokens cross the wire,
#               so the persisted reply is what the READER received and not what
#               the model produced -- the two differ whenever a widget block is
#               stripped.
#               -> tests/graph/test_stream.py
