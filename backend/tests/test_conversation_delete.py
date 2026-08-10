"""Deleting a conversation, and what "deleted" has to actually mean.

Two halves, and the second is the one worth writing down.

The first is the obvious one: the row goes, its messages go with it, the rail
stops listing it, and nobody else can aim the delete at a conversation of
yours by guessing its id.

The second is that the transcript is not the only copy. The checkpoint holds
the same conversation in the form the model reads, and a game or eligibility
session can be sitting under the same thread id. Removing the copy a reader can
see and keeping the copies they cannot is the failure this endpoint exists to
avoid, so the purge is asserted rather than assumed.

Database-backed, and skipped cleanly without one -- a deletion test that
silently passes when it could not run is worse than no test.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

os.environ.setdefault("SESSION_SECRET", "test-only-secret-not-for-production")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db import database_enabled, session  # noqa: E402
from app.db.models import Conversation, Message  # noqa: E402
from app.main import app  # noqa: E402

#: P0-010 -- see the `slow` marker note in pyproject.toml. Both markers apply:
#: this needs a live dependency AND is dominated by wall-clock cost.
pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not database_enabled(), reason="These are database-backed deletion tests."
    ),
]


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def anonymous(client: TestClient) -> dict:
    response = client.post("/api/auth/anonymous", json={})
    assert response.status_code == 200, response.text
    return response.json()


def auth(account: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {account['token']}"}


async def _seed(owner_id: str, thread_id: str, question: str) -> None:
    async with session() as db:
        db.add(Conversation(id=thread_id, owner_id=uuid.UUID(owner_id), title=question))
        await db.flush()
        db.add(
            Message(conversation_id=thread_id, seq=1, role="user", content=question)
        )
        db.add(
            Message(
                conversation_id=thread_id, seq=2, role="assistant", content="Here you go."
            )
        )


def seed(account: dict, question: str = "How do I open a savings account?") -> str:
    """One conversation with a real transcript, owned by this account.

    Written straight to the tables rather than driven through `/v2/chat/stream`,
    which is what `test_auth_idor` does: this suite is about what a delete
    removes, and a real turn would add a model call, a retrieval and several
    seconds to every case for a row it can write in one statement. The state is
    the same state a turn leaves behind.

    `asyncio.run` per call is safe here and only here because `conftest` swaps
    the engine to `NullPool` under pytest -- no connection outlives the loop
    that opened it.
    """
    thread_id = f"t-{uuid.uuid4()}"
    asyncio.run(_seed(account["user_id"], thread_id, question))
    return thread_id


async def _messages(thread_id: str) -> list[Message]:
    async with session() as db:
        result = await db.execute(
            select(Message).where(Message.conversation_id == thread_id)
        )
        return list(result.scalars().all())


# ── the delete itself ────────────────────────────────────────────────────────


def test_a_deleted_conversation_is_gone_from_the_list_and_the_transcript(
    client: TestClient,
):
    user = anonymous(client)
    thread_id = seed(user)

    listing = client.get("/api/conversations", headers=auth(user))
    assert thread_id in [c["thread_id"] for c in listing.json()["conversations"]]

    removed = client.delete(f"/api/conversations/{thread_id}", headers=auth(user))
    assert removed.status_code == 204, removed.text

    listing = client.get("/api/conversations", headers=auth(user))
    assert thread_id not in [c["thread_id"] for c in listing.json()["conversations"]]
    assert (
        client.get(f"/api/conversations/{thread_id}", headers=auth(user)).status_code
        == 404
    )


def test_the_messages_go_with_the_conversation(client: TestClient):
    """ON DELETE CASCADE, asserted rather than trusted.

    The transcript is the whole of what somebody is asking to delete. If the
    cascade were ever dropped from the schema this endpoint would leave every
    message behind and the listing would still look right.
    """
    user = anonymous(client)
    thread_id = seed(user)
    assert asyncio.run(_messages(thread_id)) != []

    assert (
        client.delete(f"/api/conversations/{thread_id}", headers=auth(user)).status_code
        == 204
    )
    assert asyncio.run(_messages(thread_id)) == []


def test_deleting_one_conversation_leaves_the_others(client: TestClient):
    user = anonymous(client)
    doomed = seed(user, "What is an index fund?")
    kept = seed(user, "How does compound interest work?")

    assert (
        client.delete(f"/api/conversations/{doomed}", headers=auth(user)).status_code
        == 204
    )

    listing = client.get("/api/conversations", headers=auth(user))
    ids = [c["thread_id"] for c in listing.json()["conversations"]]
    assert kept in ids and doomed not in ids


def test_deleting_the_same_conversation_twice_is_a_404(client: TestClient):
    """There is no soft delete, so the second attempt has nothing to find."""
    user = anonymous(client)
    thread_id = seed(user)

    assert (
        client.delete(f"/api/conversations/{thread_id}", headers=auth(user)).status_code
        == 204
    )
    assert (
        client.delete(f"/api/conversations/{thread_id}", headers=auth(user)).status_code
        == 404
    )


# ── whose conversation it is ─────────────────────────────────────────────────


def test_one_identity_cannot_delete_anothers_conversation(client: TestClient):
    """Even knowing the exact id, and the conversation must survive intact."""
    victim = anonymous(client)
    thread_id = seed(victim)

    attacker = anonymous(client)
    response = client.delete(
        f"/api/conversations/{thread_id}", headers=auth(attacker)
    )
    # 404, not 403: "not yours" and "does not exist" must stay indistinguishable,
    # or the API becomes an oracle for which conversation ids are real.
    assert response.status_code == 404

    still_there = client.get(f"/api/conversations/{thread_id}", headers=auth(victim))
    assert still_there.status_code == 200
    assert len(still_there.json()["messages"]) == 2


def test_deleting_without_a_token_is_refused(client: TestClient):
    user = anonymous(client)
    thread_id = seed(user)

    assert client.delete(f"/api/conversations/{thread_id}").status_code == 401
    assert client.get(f"/api/conversations/{thread_id}", headers=auth(user)).status_code == 200


# ── the copies that do not live in the conversations table ───────────────────


class _RecordingStore:
    """A session store that only remembers what it was asked to forget."""

    def __init__(self) -> None:
        self.deleted: list[str] = []

    def get(self, session_id: str):
        return None

    def put(self, session) -> None:  # pragma: no cover - never called here
        pass

    def delete(self, session_id: str) -> None:
        self.deleted.append(session_id)


def test_deleting_a_conversation_purges_everything_keyed_on_its_thread_id(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """The game session, the eligibility answers, and the model's own copy.

    None of these are reachable from the `conversations` row, so none of them
    are removed by deleting it. The eligibility session is the one that matters
    most: it holds a minor's answers, and a delete that leaves them behind is
    not a delete.
    """
    from app.eligibility import store as eligibility_store
    from app.games import store as game_store
    from app.graph import checkpointer

    games = _RecordingStore()
    eligibility = _RecordingStore()
    monkeypatch.setattr(game_store, "_store", games)
    monkeypatch.setattr(eligibility_store, "_store", eligibility)

    forgotten: list[str] = []

    class _Saver:
        async def adelete_thread(self, thread_id: str) -> None:
            forgotten.append(thread_id)

    async def _saver() -> _Saver:
        return _Saver()

    monkeypatch.setattr(checkpointer, "get_checkpointer", _saver)

    user = anonymous(client)
    thread_id = seed(user)
    assert (
        client.delete(f"/api/conversations/{thread_id}", headers=auth(user)).status_code
        == 204
    )

    assert games.deleted == [thread_id]
    assert eligibility.deleted == [thread_id]
    assert forgotten == [thread_id]


def test_a_deleted_conversation_is_not_resurrected_by_the_turn_that_was_running():
    """A delete must survive the answer that was still being written.

    `persist_turn` runs seconds after the reader has their answer, and it used
    to upsert the conversation row before appending to it. On every ordinary
    turn that upsert is a no-op, because `open_conversation` created the row
    before the graph ran -- so the one case where it did anything was the case
    where the row had been deleted in between, and there it undid the delete.
    """
    from app.turn import TurnRecord, persist_turn

    thread_id = f"t-{uuid.uuid4()}"
    asyncio.run(
        persist_turn(
            TurnRecord(
                thread_id=thread_id,
                question="What is an index fund?",
                reply="A fund that tracks an index.",
                # What `open_conversation` sets once it has written the row.
                opened=True,
            )
        )
    )

    async def gone() -> bool:
        async with session() as db:
            return (await db.get(Conversation, thread_id)) is None

    assert asyncio.run(gone())


def test_a_turn_whose_opening_write_failed_still_creates_its_conversation():
    """The other side of the same gate, so it is not closed too far.

    `open_conversation` swallows its own failures, and when it does the answer
    must still leave a conversation behind -- otherwise a chat committed on
    screen has nothing behind it and no route out.
    """
    from app.turn import TurnRecord, persist_turn

    thread_id = f"t-{uuid.uuid4()}"
    asyncio.run(
        persist_turn(
            TurnRecord(
                thread_id=thread_id,
                question="What is an index fund?",
                reply="A fund that tracks an index.",
                opened=False,
            )
        )
    )

    async def title() -> str | None:
        async with session() as db:
            row = await db.get(Conversation, thread_id)
            return row.title if row else None

    assert asyncio.run(title()) == "What is an index fund?"


def test_a_refused_delete_purges_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """The ownership check gates the purge, not just the row.

    None of the three stores below knows who owns anything, so reaching them
    before the DELETE has actually removed a row would let a stranger wipe a
    running game -- or a checkpoint -- by guessing a thread id and accepting a
    404 in return.
    """
    from app.eligibility import store as eligibility_store
    from app.games import store as game_store
    from app.graph import checkpointer

    games = _RecordingStore()
    eligibility = _RecordingStore()
    monkeypatch.setattr(game_store, "_store", games)
    monkeypatch.setattr(eligibility_store, "_store", eligibility)

    forgotten: list[str] = []

    class _Saver:
        async def adelete_thread(self, thread_id: str) -> None:  # pragma: no cover
            forgotten.append(thread_id)

    async def _saver() -> _Saver:
        return _Saver()

    monkeypatch.setattr(checkpointer, "get_checkpointer", _saver)

    victim = anonymous(client)
    thread_id = seed(victim)
    attacker = anonymous(client)

    assert (
        client.delete(
            f"/api/conversations/{thread_id}", headers=auth(attacker)
        ).status_code
        == 404
    )
    assert games.deleted == []
    assert eligibility.deleted == []
    assert forgotten == []
