"""Shared setup for the safety suites."""

from __future__ import annotations

import os

os.environ.setdefault(
    "SESSION_SECRET", "test-only-secret-not-for-production-at-least-32-bytes"
)

import pytest  # noqa: E402

from app.graph.identity import mint_session_token  # noqa: E402
from app.graph.state import initial_state  # noqa: E402


@pytest.fixture
def token_for():
    """Mint a session token for an arbitrary identity."""

    def _mint(
        *,
        session_id: str = "sess-test",
        user_id: str | None = "user-1",
        device_id: str = "device-1",
        persona: str = "stella",
        age_band: str = "5-8",
        account_status: str = "beneficiary",
        locale: str = "en",
    ) -> str:
        return mint_session_token(
            session_id=session_id,
            user_id=user_id,
            device_id=device_id,
            persona=persona,
            age_band=age_band,
            account_status=account_status,
            locale=locale,
        )

    return _mint


@pytest.fixture
def state_for():
    """A fully-populated `AspireState`, so tests never build a partial one."""

    def _state(**overrides):
        base = initial_state(
            session_id=overrides.pop("session_id", "sess-test"),
            user_id=overrides.pop("user_id", "user-1"),
            device_id=overrides.pop("device_id", "device-1"),
            persona=overrides.pop("persona", "stella"),
            age_band=overrides.pop("age_band", "5-8"),
            account_status=overrides.pop("account_status", "beneficiary"),
            locale=overrides.pop("locale", "en"),
        )
        base.update(overrides)
        return base

    return _state


@pytest.fixture
def recorder():
    """A `reprompt` that records its calls and returns a scripted reply."""

    class Recorder:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []
            self.replies: list[str] = []

        def scripted(self, *replies: str) -> "Recorder":
            self.replies = list(replies)
            return self

        async def __call__(self, instruction: str, text: str) -> str:
            self.calls.append((instruction, text))
            if self.replies:
                return self.replies.pop(0)
            return text

    return Recorder()
