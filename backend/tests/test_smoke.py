"""Phase 1 smoke checks.

Deliberately small: these cover the pieces that break silently (CSV mapping,
source extraction) plus /health. They do not call the LLM, so they run without
an API key.

    uv run pytest
"""

from fastapi.testclient import TestClient
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.ingest import row_to_document
from app.main import _extract_reply, _extract_sources, app


def test_health_returns_ok():
    # Used outside a context manager, TestClient skips the lifespan, so this
    # touches neither the embedding model nor the chat model.
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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


def test_extract_sources_reads_tool_artifacts_from_latest_turn():
    messages = [
        HumanMessage(content="older question"),
        ToolMessage(
            content="stale",
            tool_call_id="old",
            artifact=[Document(page_content="from a previous turn")],
        ),
        HumanMessage(content="current question"),
        ToolMessage(
            content="fresh",
            tool_call_id="new",
            artifact=[
                Document(page_content="tuition is free", metadata={"category": "Fees"}),
                Document(page_content="tuition is free", metadata={"category": "Fees"}),
            ],
        ),
        AIMessage(content="Tuition is free."),
    ]

    sources = _extract_sources(messages)

    assert len(sources) == 1, "duplicates collapse and prior turns are excluded"
    assert sources[0].content == "tuition is free"
    assert sources[0].metadata["category"] == "Fees"


def test_extract_reply_handles_block_content():
    messages = [AIMessage(content=[{"type": "text", "text": "Hello there."}])]
    assert _extract_reply(messages) == "Hello there."
