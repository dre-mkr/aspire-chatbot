"""The upload request must reach the reader, and their answer must resume the graph.

Registration collects seventeen slots and four of them are documents. The graph
pauses on each with `interrupt()`, carrying a payload that is already a valid
`upload` directive -- correct slot, correct label, correct accepted MIME types.

Nothing read it. `api/stream.py` subscribes to the "messages" and "custom" stream
modes, `__interrupt__` is published on "updates" and "values", and no code
anywhere called `Command(resume=...)` -- the phrase appeared in three docstrings
and in no statement. So a parent answered every typed question, reached the ID
photo, and the assistant went silent. Ten of seventeen slots were unreachable.

The existing tests in this package could not see it: they drive the register
subgraph directly, where the interrupt is simply the return value, and never ask
whether anything downstream would turn it into something a browser can answer.
"""

from __future__ import annotations

import pytest

from app.api.stream import _pending_interrupts


class _Interrupt:
    def __init__(self, value):
        self.value = value


class _Task:
    def __init__(self, interrupts):
        self.interrupts = interrupts


class _Snapshot:
    def __init__(self, tasks):
        self.tasks = tasks


class _Graph:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    async def aget_state(self, config):
        if isinstance(self._snapshot, Exception):
            raise self._snapshot
        return self._snapshot


UPLOAD_REQUEST = {
    "type": "upload_request",
    "t": "upload",
    "slot": "guardian.id_document",
    "label": "A photo of your ID",
    "accepts": ["image/jpeg", "image/png", "image/heic", "application/pdf"],
    "max_mb": 10,
    "help": "A clear photo of the whole card is fine.",
}


class TestTheUploadRequestReachesTheClient:
    @pytest.mark.anyio
    async def test_a_paused_graph_yields_its_directive(self):
        graph = _Graph(_Snapshot([_Task([_Interrupt(dict(UPLOAD_REQUEST))])]))

        directives = await _pending_interrupts(graph, {})

        assert len(directives) == 1
        assert directives[0]["t"] == "upload"
        assert directives[0]["slot"] == "guardian.id_document"
        assert directives[0]["label"] == "A photo of your ID"

    @pytest.mark.anyio
    async def test_the_nodes_own_type_key_is_not_put_on_the_wire(self):
        """`t` is the discriminator; `type` is the node's private name for it.

        Both are in the payload `upload.py` builds. Only `t` means anything to
        `DirectiveRegistry`, and shipping a second near-synonym invites a client
        to switch on the wrong one.
        """
        graph = _Graph(_Snapshot([_Task([_Interrupt(dict(UPLOAD_REQUEST))])]))

        directive = (await _pending_interrupts(graph, {}))[0]

        assert "type" not in directive
        assert directive["t"] == "upload"

    @pytest.mark.anyio
    async def test_a_graph_that_is_not_paused_yields_nothing(self):
        assert await _pending_interrupts(_Graph(_Snapshot([])), {}) == []

    @pytest.mark.anyio
    async def test_an_interrupt_that_is_not_a_directive_is_not_forwarded(self):
        """Only a payload carrying `t` can be rendered. Anything else is dropped.

        A future node may interrupt for its own reasons. Forwarding an object the
        client cannot switch on would render nothing and warn, which is a worse
        failure than declining to send it.
        """
        graph = _Graph(_Snapshot([_Task([_Interrupt({"waiting": "for something"})])]))

        assert await _pending_interrupts(graph, {}) == []

    @pytest.mark.anyio
    async def test_a_checkpointer_blip_costs_the_card_and_not_the_turn(self):
        """This runs after the prose has been sent. It may never raise."""
        graph = _Graph(RuntimeError("checkpointer is down"))

        assert await _pending_interrupts(graph, {}) == []


class TestANonSensitiveSlotCanActuallyBeSaved:
    """`save_slot` must survive contact with Postgres.

    `to_jsonb(:value)` and `jsonb_build_object(:slot, ...)` are polymorphic, and
    asyncpg sends bind parameters untyped. Postgres cannot resolve
    `to_jsonb(unknown)` and raised DatatypeMismatchError on every non-sensitive
    slot -- so registration collected the guardian's name, national ID and date
    of birth (all sensitive, all on the encrypted branch) and then died on
    `guardian.relationship`, the first slot that touches `applications.answers`.

    Far enough in to look like it was working, and far enough in to have stored
    real PII about a real person first.

    Every test in this package ran without a database, where `session()` yields
    None and `save_slot` returns before reaching any SQL. That is the whole
    reason a statement that could never execute shipped.
    """

    @pytest.mark.anyio
    async def test_the_expression_resolves_against_postgres(self):
        """The jsonb expression `save_slot` builds, evaluated for real.

        A bare SELECT rather than a table: what failed was Postgres resolving a
        polymorphic function against untyped bind parameters, and that resolution
        happens the same way with or without somewhere to put the result. It also
        sidesteps Neon's connection pooling, under which a TEMP table created on
        one backend is not visible to the next statement.
        """
        import os

        url = os.environ.get("DATABASE_URL", "")
        if not url:
            pytest.skip("no DATABASE_URL; this assertion needs a real Postgres")

        import asyncpg

        connection = await asyncpg.connect(
            url.replace("postgresql+asyncpg://", "postgresql://")
        )
        try:
            built = await connection.fetchval(
                "SELECT jsonb_build_object(CAST($1 AS text), to_jsonb(CAST($2 AS text)))",
                "guardian.relationship",
                "mother",
            )
        finally:
            await connection.close()

        assert built == '{"guardian.relationship": "mother"}'

    @pytest.mark.anyio
    async def test_the_uncast_form_is_the_one_that_fails(self):
        """Pins the cause, so a future edit that drops the casts is recognised.

        Without this a reader could reasonably conclude the casts are noise and
        remove them, and the test above would still pass -- it would simply be
        testing an expression the product no longer builds.
        """
        import os

        url = os.environ.get("DATABASE_URL", "")
        if not url:
            pytest.skip("no DATABASE_URL; this assertion needs a real Postgres")

        import asyncpg

        connection = await asyncpg.connect(
            url.replace("postgresql+asyncpg://", "postgresql://")
        )
        try:
            with pytest.raises(asyncpg.exceptions.DatatypeMismatchError):
                await connection.fetchval(
                    "SELECT jsonb_build_object($1, to_jsonb($2))",
                    "guardian.relationship",
                    "mother",
                )
        finally:
            await connection.close()

    def test_the_source_still_carries_the_casts(self):
        """Cheap, database-free, and the one that runs in CI."""
        import inspect

        from app.agents.register import store

        source = inspect.getsource(store.save_slot)
        assert "CAST(:value AS text)" in source and "CAST(:slot AS text)" in source, (
            "save_slot must cast its bind parameters. Without the casts Postgres "
            "cannot resolve to_jsonb(unknown) and every non-sensitive slot fails."
        )
