"""The upload request must reach the reader, and their answer must resume the graph."""

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
        """`t` is the discriminator; `type` is the node's private name for it."""
        graph = _Graph(_Snapshot([_Task([_Interrupt(dict(UPLOAD_REQUEST))])]))

        directive = (await _pending_interrupts(graph, {}))[0]

        assert "type" not in directive
        assert directive["t"] == "upload"

    @pytest.mark.anyio
    async def test_a_graph_that_is_not_paused_yields_nothing(self):
        assert await _pending_interrupts(_Graph(_Snapshot([])), {}) == []

    @pytest.mark.anyio
    async def test_an_interrupt_that_is_not_a_directive_is_not_forwarded(self):
        """Only a payload carrying `t` can be rendered."""
        graph = _Graph(_Snapshot([_Task([_Interrupt({"waiting": "for something"})])]))

        assert await _pending_interrupts(graph, {}) == []

    @pytest.mark.anyio
    async def test_a_checkpointer_blip_costs_the_card_and_not_the_turn(self):
        """This runs after the prose has been sent. It may never raise."""
        graph = _Graph(RuntimeError("checkpointer is down"))

        assert await _pending_interrupts(graph, {}) == []


class TestTheObjectIsWhereTheRowSaysItIs:
    """The signed upload and the recorded key must name the same object."""

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
            # Deliberately not the session id the state below carries.
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
        """The regression, at the point it becomes visible to the client."""
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
        """The round trip, end to end: sign where the row will point."""
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
        """Why the field is load-bearing rather than a convenience."""
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
    """`save_slot` must survive contact with Postgres."""

    @pytest.mark.anyio
    async def test_the_expression_resolves_against_postgres(self):
        """The jsonb expression `save_slot` builds, evaluated for real."""
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
        """Pins the cause, so a future edit that drops the casts is recognised."""
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
