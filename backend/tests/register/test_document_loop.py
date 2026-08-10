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


class TestTheObjectIsWhereTheRowSaysItIs:
    """The signed upload and the recorded key must name the same object.

    They did not. The card asked `/v2/documents/presign` for a URL without an
    `application_id`, so the endpoint fell back to the caller's SESSION id and
    signed a PUT to `applications/<session>/<slot>/<doc>`. `_record_document`
    then wrote the row with `storage_key_for(draft.application_id, ...)` --
    `applications/<application>/<slot>/<doc>`. `store.new_draft` mints the
    application id as a fresh UUID, so the two are never equal.

    Both halves reported success. The PUT returned 200, the row was inserted,
    the parent was told "Got it, thank you." The 404 waited until `doc_check`
    read the document or an admin opened it -- for every document ever uploaded.

    The `payload["storage_key"]` fallback in `_record_document` could not save
    it either: the resume path is a plain text message ("I uploaded <slot>:
    <id>"), so no key, mime or size ever reaches the graph.

    These tests are written as a ROUND TRIP -- derive the key from what the
    client is actually told, and compare it to what the database is actually
    given -- because that is the only form that would have failed before. Each
    half on its own was self-consistent and passed review.
    """

    @staticmethod
    def _draft():
        from datetime import date

        from app.agents.register import schema as rs
        from app.agents.register import store

        values = {}
        for slot in rs.GUARDIAN_SLOTS:
            if slot.document:
                continue
            values[slot.path] = (
                date(1985, 3, 14) if slot.path == "guardian.date_of_birth" else "x"
            )
        return store.Draft(
            # Deliberately not the session id the state below carries. That is
            # the whole point: `new_draft` mints a UUID, and no session id is one.
            application_id="11111111-2222-3333-4444-555555555555",
            resume_token="t",
            values=values,
        )

    @staticmethod
    async def _pause_on_the_document(draft):
        """Drive the real graph to the first document slot and return its card."""
        from langchain_core.messages import HumanMessage
        from langgraph.checkpoint.memory import InMemorySaver

        from app.agents.register import graph as rg
        from app.graph.state import initial_state

        async def loader(token: str):
            return draft

        graph = rg.build_register_graph(
            loader=loader, recorder=rg._record_document, checkpointer=InMemorySaver()
        )
        state = initial_state(
            session_id="s-reg",
            user_id="u-reg",
            device_id="d",
            persona="aurora",
            age_band="adult",
            account_status="guardian",
        )
        state["messages"] = [HumanMessage(content="hi")]
        state["active_agent"] = "register_agent"
        state["safety_flags"] = {"resume_token": "t"}

        config = {"configurable": {"thread_id": "documents-1"}}
        await graph.ainvoke(state, config)
        directive = (await _pending_interrupts(graph, config))[0]
        return graph, config, directive

    @pytest.mark.anyio
    async def test_the_card_is_told_which_application_to_upload_into(self):
        """The regression, at the point it becomes visible to the client.

        `_pending_interrupts` is the real path the payload takes to the browser,
        so this asserts on the directive as rendered rather than on the node's
        return value.
        """
        draft = self._draft()

        _graph, _config, directive = await self._pause_on_the_document(draft)

        assert directive["t"] == "upload"
        assert directive["slot"] == "guardian.id_document"
        assert directive["application_id"] == draft.application_id
        assert directive["application_id"] != "s-reg", (
            "the card was told the session id, which is what the presign "
            "endpoint already defaults to -- the bug, restored"
        )

    @pytest.mark.anyio
    async def test_the_recorded_key_is_the_key_the_upload_was_signed_for(
        self, monkeypatch
    ):
        """The round trip, end to end: sign where the row will point.

        `storage_key_for` is called here with exactly what the endpoint would
        call it with -- the `application_id` off the directive -- so this is the
        real key the browser PUT to, not a restatement of the recorder's own
        arithmetic.
        """
        from langgraph.types import Command

        from app.agents.register import store
        from app.storage.presign import storage_key_for

        draft = self._draft()
        graph, config, directive = await self._pause_on_the_document(draft)

        written: list[dict] = []

        async def _capture(_draft, rows):
            written.extend(rows)

        monkeypatch.setattr(store, "record_documents", _capture)

        document_id = "d3adb33f000000000000000000000000"
        signed_key = storage_key_for(
            directive["application_id"], directive["slot"], document_id
        )

        await graph.ainvoke(
            Command(
                resume={
                    "document_id": document_id,
                    "mime": "image/jpeg",
                    "size_bytes": 2048,
                }
            ),
            config,
        )

        assert len(written) == 1, "the document was not recorded"
        assert written[0]["storage_key"] == signed_key, (
            "the row points at an object that was never written there"
        )

    def test_the_endpoints_default_cannot_reach_the_recorded_key(self):
        """Why the field is load-bearing rather than a convenience.

        Says the thing that makes the two tests above necessary: the prefix the
        presign endpoint picks on its own can never be the prefix the recorder
        writes. So there is no arrangement of defaults under which omitting the
        id happens to work -- the card has to send it.

        This one holds with or without the fix, deliberately. It is the standing
        statement of the constraint, not a regression guard.
        """
        from app.storage.presign import storage_key_for

        document_id = "d3adb33f000000000000000000000000"
        session_scoped = storage_key_for("s-reg", "guardian.id_document", document_id)
        application_scoped = storage_key_for(
            "11111111-2222-3333-4444-555555555555",
            "guardian.id_document",
            document_id,
        )

        assert session_scoped != application_scoped


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
