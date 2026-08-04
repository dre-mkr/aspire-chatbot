"""Phase 1 smoke checks.

Deliberately small: these cover the pieces that break silently (CSV mapping,
source extraction) plus /health. They do not call the LLM, so they run without
an API key.

    uv run pytest
"""

from fastapi.testclient import TestClient
from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from app.ingest import row_to_document
from app.main import _extract_reply, _extract_sources, app


class _FakeVar:
    """Stands in for the retrieval ContextVar without touching real context."""

    def __init__(self, documents):
        self._documents = documents

    def get(self):
        return self._documents


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


def test_extract_sources_reads_this_turns_retrieval(monkeypatch):
    """Sources come from what the request retrieved, not from the agent's messages.

    Rewritten in P13-005. It used to walk the turn for a ToolMessage and pull
    `artifact` off it, because while retrieval was a tool that was the only route
    available -- and there is no such message any more. The intent it was written
    to protect is unchanged and still asserted: duplicates collapse, and a prior
    turn's documents never leak into this turn's sources.

    The second half is now true by construction rather than by filtering: the
    ContextVar holds exactly the documents this request retrieved, so there is no
    "previous turn" in scope to exclude.
    """
    from app import main

    monkeypatch.setattr(
        main,
        "_RETRIEVED",
        _FakeVar(
            [
                Document(page_content="tuition is free", metadata={"category": "Fees"}),
                Document(page_content="tuition is free", metadata={"category": "Fees"}),
            ]
        ),
    )

    # `messages` is still accepted and still ignored, so both endpoints can keep
    # calling this the same way.
    sources = _extract_sources([AIMessage(content="Tuition is free.")])

    assert len(sources) == 1, "duplicates must still collapse"
    assert sources[0].content == "tuition is free"
    assert sources[0].metadata["category"] == "Fees"


def test_extract_sources_is_empty_when_nothing_was_retrieved(monkeypatch):
    """A refused turn retrieved nothing, so it cites nothing."""
    from app import main

    monkeypatch.setattr(main, "_RETRIEVED", _FakeVar([]))
    assert _extract_sources([AIMessage(content="I don't have that one.")]) == []


def test_extract_reply_handles_block_content():
    messages = [AIMessage(content=[{"type": "text", "text": "Hello there."}])]
    assert _extract_reply(messages) == "Hello there."
