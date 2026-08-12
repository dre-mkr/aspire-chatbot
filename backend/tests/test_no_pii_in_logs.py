"""Children's questions must not reach the system journal."""

from __future__ import annotations

import io
import logging

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.slow

#: Distinctive enough that a log match cannot be coincidence, yet shaped like real child input.
NAME = "Zephaniah Quillfeather"
ADDRESS = "17 Marigold Crescent, Basseterre"
SCHOOL = "Saint Ambrose Preparatory"
EMAIL = "zephaniah.q@example-parent.test"
NATIONAL_ID = "SKN-99-887766"

MESSAGE = (
    f"Hi, my name is {NAME}, I live at {ADDRESS}, I go to {SCHOOL}. "
    f"My mum's email is {EMAIL} and my ID is {NATIONAL_ID}. "
    "What is the ASPIRE Programme?"
)


@pytest.fixture(scope="module")
def client():
    """ONE app lifespan for the whole module."""
    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _turn_capturing_logs(client, level: int, message: str = MESSAGE) -> str:
    """Run one real turn with the root logger at `level`; return everything logged."""
    captured = io.StringIO()
    handler = logging.StreamHandler(captured)
    handler.setLevel(level)
    root = logging.getLogger()
    previous = root.level
    root.setLevel(level)
    root.addHandler(handler)
    try:
        token = client.post(
            "/v2/session", json={"device_id": "pii-probe", "locale": "en"}
        ).json()["token"]
        client.post(
            "/v2/chat/stream",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": message},
        )
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)
    return captured.getvalue()


@pytest.mark.parametrize(
    "level, label",
    [(logging.INFO, "INFO (the default)"), (logging.DEBUG, "DEBUG (an operator debugging)")],
)
def test_a_childs_message_never_reaches_the_log(client, level, label):
    logs = _turn_capturing_logs(client, level)

    for what, needle in (
        ("child's name", NAME),
        ("home address", ADDRESS),
        ("school", SCHOOL),
        ("parent's email", EMAIL),
        ("national id", NATIONAL_ID),
        ("the question itself", MESSAGE[:50]),
    ):
        assert needle not in logs, (
            f"at {label}, the {what} was written to the log. "
            f"First offending line: "
            f"{next((line for line in logs.splitlines() if needle in line), '')[:200]}"
        )


def test_the_retrieval_line_still_says_something_useful(client):
    """De-identifying must not mean logging nothing."""
    # A question no previous run can have cached.
    import uuid

    logs = _turn_capturing_logs(
        client,
        logging.INFO,
        f"How much does the government contribute per child? (probe {uuid.uuid4().hex[:8]})",
    )
    assert "hybrid retrieval:" in logs, "the retrieval line disappeared entirely"
    assert "sha=" in logs, "no correlation handle survived the de-identification"


def test_third_party_http_loggers_are_capped(client):
    """The SDK's own request dump is the leak an app-level fix cannot reach."""
    for noisy in ("openai", "httpx", "httpcore"):
        assert logging.getLogger(noisy).level >= logging.INFO, (
            f"{noisy} is below INFO; at DEBUG it logs the full request body, "
            "which contains the child's message"
        )
