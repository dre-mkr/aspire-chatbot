"""An unmigrated database must not become a 500 on the first message."""

import asyncio

import pytest

from app.db import engine as db_engine


class _FakeSession:
    """Just enough of AsyncSession for `session()` to run to completion."""

    committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def commit(self):
        self.committed = True

    async def rollback(self):
        pass


@pytest.fixture(autouse=True)
def reset_latch():
    """The latch is process-wide, so a test must not leak into the next one."""
    original = db_engine._SCHEMA_MISSING
    db_engine._SCHEMA_MISSING = False
    yield
    db_engine._SCHEMA_MISSING = original


class TestSchemaLatch:
    def test_persistence_is_off_when_the_schema_is_missing(self, monkeypatch):
        monkeypatch.setattr(db_engine, "get_engine", lambda: object())
        assert db_engine.database_enabled() is True

        db_engine._SCHEMA_MISSING = True
        assert db_engine.database_enabled() is False

    def test_no_engine_still_reads_as_disabled(self, monkeypatch):
        monkeypatch.setattr(db_engine, "get_engine", lambda: None)
        assert db_engine.database_enabled() is False

    def test_session_yields_none_rather_than_a_doomed_one(self, monkeypatch):
        # The important half.
        monkeypatch.setattr(db_engine, "get_engine", lambda: object())
        monkeypatch.setattr(db_engine, "get_sessionmaker", lambda: _FakeSession)
        db_engine._SCHEMA_MISSING = True

        async def check():
            async with db_engine.session() as db:
                return db

        assert asyncio.run(check()) is None

    def test_a_healthy_schema_still_hands_out_a_session(self, monkeypatch):
        monkeypatch.setattr(db_engine, "get_engine", lambda: object())
        monkeypatch.setattr(db_engine, "get_sessionmaker", lambda: _FakeSession)

        async def check():
            async with db_engine.session() as db:
                return db

        db = asyncio.run(check())
        assert isinstance(db, _FakeSession)
        # The happy path still commits, so the guard did not quietly turn every write into a no-op.
        assert db.committed is True


def test_the_tables_we_require_are_the_ones_the_request_path_writes():
    # `documents` is absent on purpose: it is only read, and an empty corpus still answers.
    assert set(db_engine.REQUIRED_TABLES) == {"conversations", "messages"}
