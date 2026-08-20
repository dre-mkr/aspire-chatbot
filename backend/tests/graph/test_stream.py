"""The wire protocol, end to end, against a real FastAPI app."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault(
    "SESSION_SECRET", "test-only-secret-not-for-production-at-least-32-bytes"
)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

from app.api.stream import parse_sse, router  # noqa: E402
from app.graph.identity import mint_session_token  # noqa: E402
from app.graph.stream_interceptor import StreamInterceptor  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    """The v2 router alone, with the model calls stubbed."""
    from app.api import stream as stream_module
    from app.graph import main_graph

    async def no_checkpointer():
        return None

    async def classifier(system: str, user: str) -> str:
        return '{"agent": "learn_agent", "confidence": 0.95, "reason": "lesson"}'

    async def reprompt(instruction: str, text: str) -> str:
        return text

    monkeypatch.setattr(stream_module, "get_checkpointer", no_checkpointer)
    monkeypatch.setattr(stream_module, "_classifier_invoke", classifier)
    monkeypatch.setattr(stream_module, "_reprompt", reprompt)

    async def learn_stub(state):
        return {
            "messages": [
                AIMessage(content="Saving means keeping money for later.")
            ],
            "quick_replies": ["Tell me more", "Play a game"],
            "active_agent": "learn_agent",
        }

    monkeypatch.setitem(main_graph.AGENT_BUILDERS, "learn_agent", lambda: learn_stub)

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def token(**overrides) -> str:
    claims = {
        "session_id": "sess-stream",
        "user_id": "u-1",
        "device_id": "d-1",
        "persona": "stella",
        "age_band": "9-12",
        "account_status": "beneficiary",
        "locale": "en",
    }
    claims.update(overrides)
    return mint_session_token(**claims)


def post(client, *, auth: str | None, **body):
    headers = {"Authorization": f"Bearer {auth}"} if auth else {}
    with client.stream(
        "POST", "/v2/chat/stream", json=body, headers=headers
    ) as response:
        return response.status_code, parse_sse(
            "".join(chunk for chunk in response.iter_text())
        )


def post_raw(client, *, auth: str | None, **body):
    """For refusals decided BEFORE the stream opens, which are plain JSON."""
    headers = {"Authorization": f"Bearer {auth}"} if auth else {}
    response = client.post("/v2/chat/stream", json=body, headers=headers)
    return response.status_code, response.json()


class TestTheHappyTurn:
    def test_tokens_then_a_quick_replies_directive_then_done(self, client):
        status, events = post(client, auth=token(), message="what is saving")
        assert status == 200

        kinds = [event["event"] for event in events]
        assert "token" in kinds
        assert kinds[-1] == "done"

        directives = [
            event["data"]["d"] for event in events if event["event"] == "directive"
        ]
        chips = [d for d in directives if d["t"] == "quick_replies"]
        assert len(chips) == 1
        assert [option["label"] for option in chips[0]["options"]] == [
            "Tell me more",
            "Play a game",
        ]

    def test_every_content_event_carries_a_monotonic_ordinal(self, client):
        """
        Contiguous from 1, not merely increasing.

        Monotonic-and-unique was too weak to notice a GAP, and one appeared the
        moment prose started being held back for the outbound gates: the held
        events still ran through `_token` and took ordinals with them, so the
        reader's first frame arrived numbered 2. `OrdinalBuffer.text()` skips
        absent ordinals rather than waiting, so nothing broke and nothing said
        so -- which is the argument for pinning the sequence rather than its
        direction.
        """
        _status, events = post(client, auth=token(), message="what is saving")
        ordinals = [
            event["data"]["i"]
            for event in events
            if event["event"] in ("token", "directive", "done")
        ]
        assert ordinals == sorted(ordinals)
        assert len(set(ordinals)) == len(ordinals)
        assert ordinals == list(range(1, len(ordinals) + 1)), (
            f"ordinals are not contiguous from 1: {ordinals}"
        )

    def test_the_directive_ordinal_follows_the_last_token(self, client):
        """Position is what the ordinal is for."""
        _status, events = post(client, auth=token(), message="what is saving")
        last_token = max(
            event["data"]["i"] for event in events if event["event"] == "token"
        )
        directive = next(
            event["data"]["i"] for event in events if event["event"] == "directive"
        )
        assert directive > last_token

    def test_done_reports_the_agent_and_whether_to_speak(self, client):
        _status, events = post(client, auth=token(age_band="5-8"), message="hi")
        usage = events[-1]["data"]["usage"]
        assert usage["agent"] == "learn_agent"
        assert usage["speak"] is True
        assert usage["elapsed_ms"] >= 0

    def test_an_older_band_does_not_auto_speak(self, client):
        _status, events = post(
            client, auth=token(persona="orion", age_band="16-18"), message="hi"
        )
        assert events[-1]["data"]["usage"]["speak"] is False


class TestFailures:
    def test_no_token_is_a_401_carrying_the_error_shape(self, client):
        """Authentication is settled BEFORE the response starts, so it is a status."""
        status, body = post_raw(client, auth=None, message="hi")
        assert status == 401
        assert body == {
            "code": "unauthenticated",
            "message": "Please sign in again to keep chatting.",
        }

    def test_a_bad_token_is_the_same_refusal(self, client):
        status, body = post_raw(client, auth="not-a-token", message="hi")
        assert status == 401
        assert body["code"] == "unauthenticated"

    def test_a_failure_INSIDE_the_turn_is_still_an_error_event(self, client):
        """The original property, which still has to hold for everything else."""
        status, events = post(client, auth=token(), message="   ")
        assert status == 200
        assert events[0]["event"] == "error"
        assert events[0]["data"]["code"] == "empty_message"

    def test_an_empty_message_is_refused_before_any_model_call(self, client):
        _status, events = post(client, auth=token(), message="   ")
        assert events[0]["data"]["code"] == "empty_message"

    def test_an_error_message_names_no_internals(self, client):
        _status, body = post_raw(client, auth=None, message="hi")
        text = body["message"].lower()
        for leak in ("token", "jwt", "graph", "langgraph", "postgres", "openai"):
            assert leak not in text


class TestIdentityIsNotClientControlled:
    def test_a_body_claiming_a_persona_does_not_change_the_route(self, client, caplog):
        """The A2 acceptance case, seen from the transport."""
        with caplog.at_level("WARNING"):
            _status, events = post(
                client,
                auth=token(persona="stella", age_band="9-12"),
                message="I want to register",
                persona="aurora",
                age_band="adult",
                account_status="guardian",
            )

        assert "ignored" in caplog.text

        # What Aurora would have reached, and this caller must not.
        agent = events[-1]["data"]["usage"]["agent"]
        assert agent not in ("register_agent", "register_agent_step1", "servicing_agent")

        # What a Stella token earns here: told that a parent or guardian applies.
        prose = "".join(
            event["data"]["t"] for event in events if event["event"] == "token"
        )
        assert "parent or guardian" in prose

    def test_a_refused_combination_still_streams_a_gated_refusal(self, client):
        """Every path reaches `safety_out`, including this one."""
        _status, events = post(
            client,
            auth=token(persona="orion", age_band="5-8"),
            message="hello",
        )
        prose = "".join(
            event["data"]["t"] for event in events if event["event"] == "token"
        )
        assert "can't help with that from here" in prose
        assert events[-1]["event"] == "done"


class TestTheEncoding:
    def test_frames_are_well_formed_sse(self, client):
        headers = {"Authorization": f"Bearer {token()}"}
        with client.stream(
            "POST", "/v2/chat/stream", json={"message": "hi"}, headers=headers
        ) as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            # nginx buffers proxied responses by default, so the stream would land all at once.
            assert response.headers["x-accel-buffering"] == "no"
            raw = "".join(chunk for chunk in response.iter_text())

        assert raw.endswith("\n\n")
        for block in raw.split("\n\n"):
            if block.strip():
                assert block.startswith("event: ")
                assert "\ndata: " in block


# ── citation markers never reach the reader ──────────────────────────────────


class TestCitationMarkers:
    """`[ASP-001]` is grounding machinery, not copy."""

    CASES = {
        "ASPIRE is a savings programme. [ASP-001] It is run by the government [ASP-002].":
            "ASPIRE is a savings programme. It is run by the government.",
        "[ASP-001] leads the answer.": "leads the answer.",
        "Ends with a marker [FIN-1234]": "Ends with a marker",
        "Save EC$25 [ASP-003] each month [ASP-004] to start.":
            "Save EC$25 each month to start.",
        # Ordinary brackets are prose and must survive.
        "Use the form [see page 4] and bring ID.":
            "Use the form [see page 4] and bring ID.",
        "Money grows.  Two spaces stay.": "Money grows.  Two spaces stay.",
    }

    @pytest.mark.parametrize("chunk", [1, 2, 3, 4, 5, 7, 9, 13, 40, 500])
    def test_markers_are_stripped_at_every_chunk_boundary(self, chunk: int):
        """The whole difficulty is WHERE the boundary falls."""
        for text, want in self.CASES.items():
            interceptor = StreamInterceptor(widgets_enabled=True)
            for index in range(0, len(text), chunk):
                interceptor.feed(text[index : index + chunk])
            interceptor.flush()
            assert interceptor.prose == want, f"chunk={chunk} on {text!r}"

    def test_the_space_before_a_marker_goes_with_it(self):
        """Otherwise the sentence keeps a double space and a stranded " ."."""
        interceptor = StreamInterceptor(widgets_enabled=True)
        for char in "done. [ASP-001] next":
            interceptor.feed(char)
        interceptor.flush()
        assert interceptor.prose == "done. next"

    def test_a_bracket_too_long_to_be_a_marker_is_released(self):
        """A hold that never resolves is a stream that stops."""
        interceptor = StreamInterceptor(widgets_enabled=True)
        events = interceptor.feed("see [this very long bracketed aside that never closes")
        assert events, "the stream stalled on an unclosed bracket"


class TestChipsThatRunLong:
    """A chip too long for the schema must not take the answer down with it.

    The follow-ups are written by a model, so their length is not guaranteed, and
    the 60-character cap is about what fits on a chip. Enforcing it by raising
    inside the SSE generator lost an answer that had already been generated: the
    reader saw "The connection to the assistant was lost."
    """

    LONG = "What documentation is needed to confirm a child's eligibility during sign-up?"

    def test_a_long_chip_is_shortened_rather_than_raised(self):
        from app.api.stream import CHIP_LABEL_CHARS, _closing_directives

        out = _closing_directives({"quick_replies": [self.LONG]})
        options = next(d for d in out if d["t"] == "quick_replies")["options"]

        assert len(options[0]["label"]) <= CHIP_LABEL_CHARS
        assert options[0]["label"].endswith("…")
        # Tapping still asks the whole question.
        assert options[0]["value"] == self.LONG

    def test_a_chip_that_fits_is_left_exactly_alone(self):
        from app.api.stream import _closing_directives

        out = _closing_directives({"quick_replies": ["Tell me more"]})
        options = next(d for d in out if d["t"] == "quick_replies")["options"]
        assert options == [{"label": "Tell me more", "value": "Tell me more"}]

    def test_the_label_is_cut_at_a_word_boundary(self):
        from app.api.stream import _closing_directives

        out = _closing_directives({"quick_replies": [self.LONG]})
        label = next(d for d in out if d["t"] == "quick_replies")["options"][0]["label"]
        assert " " not in label[-2:], f"cut mid-word: {label!r}"
        assert self.LONG.startswith(label[:-1].rstrip())

    def test_a_blank_chip_is_dropped_not_rejected(self):
        """min_length=1 would raise on the empty string."""
        from app.api.stream import _closing_directives

        out = _closing_directives({"quick_replies": ["", "   ", "Tell me more"]})
        options = next(d for d in out if d["t"] == "quick_replies")["options"]
        assert [option["label"] for option in options] == ["Tell me more"]

    def test_chips_that_are_all_blank_emit_no_directive(self):
        from app.api.stream import _closing_directives

        assert _closing_directives({"quick_replies": ["", "  "]}) == []

    def test_the_builder_and_the_wire_agree_on_the_cap(self):
        """They drifted once -- builder 72, schema 60 -- and every corpus question
        between them was admitted and then rejected on the wire, killing the turn.
        """
        from app.agents.qa.nodes import CHIP_MAX_CHARS
        from app.schemas.directives import CHIP_LABEL_CHARS

        assert CHIP_MAX_CHARS == CHIP_LABEL_CHARS

    def test_a_chip_at_exactly_the_cap_survives_untouched(self):
        from app.api.stream import _closing_directives
        from app.schemas.directives import CHIP_LABEL_CHARS

        chip = "q" * CHIP_LABEL_CHARS
        out = _closing_directives({"quick_replies": [chip]})
        options = next(d for d in out if d["t"] == "quick_replies")["options"]
        assert options[0]["label"] == chip


class TestATurnThatSaysNothing:
    """The transport's backstop.

    A learning turn was measured ending with no prose, no directive and no row
    in `messages`: the reader got an empty bubble with a Play button and no way
    to tell it from a hang, and nothing in the log said so. The graph bugs
    behind that one are fixed; this is the net under the next one.
    """

    @pytest.fixture
    def silent_client(self, monkeypatch):
        """The same app, with an agent that returns nothing at all."""
        from app.api import stream as stream_module
        from app.graph import main_graph

        async def no_checkpointer():
            return None

        async def classifier(system: str, user: str) -> str:
            return '{"agent": "learn_agent", "confidence": 0.95, "reason": "lesson"}'

        monkeypatch.setattr(stream_module, "get_checkpointer", no_checkpointer)
        monkeypatch.setattr(stream_module, "_classifier_invoke", classifier)

        async def mute(state):
            return {"active_agent": "learn_agent"}

        monkeypatch.setitem(main_graph.AGENT_BUILDERS, "learn_agent", lambda: mute)

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_the_reader_gets_a_sentence_rather_than_an_empty_message(
        self, silent_client
    ):
        from app.api.stream import EMPTY_TURN

        status, events = post(
            silent_client, auth=token(), message="Building a saving habit"
        )
        assert status == 200

        prose = "".join(
            event["data"]["t"] for event in events if event["event"] == "token"
        )
        assert prose.strip() == EMPTY_TURN["en"]
        assert events[-1]["event"] == "done"

    def test_it_is_logged_as_an_error_not_swallowed(self, silent_client, caplog):
        import logging

        with caplog.at_level(logging.ERROR, logger="app.api.stream"):
            post(silent_client, auth=token(), message="Building a saving habit")

        assert any(
            "no prose and nothing to act on" in record.getMessage()
            for record in caplog.records
        ), "a silent turn must leave a record naming the agent"

    def test_the_reader_is_answered_in_their_own_language(self, silent_client):
        from app.api.stream import EMPTY_TURN

        _status, events = post(
            silent_client, auth=token(locale="fr"), message="Une habitude d'épargne"
        )
        prose = "".join(
            event["data"]["t"] for event in events if event["event"] == "token"
        )
        assert prose.strip() == EMPTY_TURN["fr"]

    def test_a_card_turn_says_nothing_and_is_left_alone(self, client, monkeypatch):
        """Cards, widgets and a paused upload all speak through directives."""
        from app.graph import main_graph

        async def card_only(state):
            return {
                "active_agent": "learn_agent",
                "ui_directives": [{"t": "game", "game": "true_false", "concept": "save"}],
            }

        monkeypatch.setitem(main_graph.AGENT_BUILDERS, "learn_agent", lambda: card_only)

        # Not "play a game": the card intent gate answers that one in prose
        # before any agent runs, and this is about the agent's own silence.
        _status, events = post(client, auth=token(), message="Building a saving habit")
        prose = "".join(
            event["data"]["t"] for event in events if event["event"] == "token"
        )
        assert prose == ""
        kinds = [
            event["data"]["d"]["t"] for event in events if event["event"] == "directive"
        ]
        assert "game" in kinds


class TestTheReaderGetsTheCorrectedAnswer:
    """
    Every outbound gate runs a graph step AFTER the agent that produced the
    text, so anything sent during the agent's step is pre-correction and cannot
    be taken back. Measured on the deployed app: "bitcoin" reached the screen
    four times, and a decline arrived welded onto the end of a finished answer.

    Asserted with the two gates that need no model call, so the test measures
    delivery rather than a stub: PII redaction and link stripping are both
    deterministic rewrites.
    """

    def _saying(self, monkeypatch, text: str):
        from app.graph import main_graph

        async def agent(state):
            return {
                "messages": [AIMessage(content=text)],
                "active_agent": "learn_agent",
            }

        monkeypatch.setitem(main_graph.AGENT_BUILDERS, "learn_agent", lambda: agent)

    def _prose(self, events) -> str:
        return "".join(
            event["data"]["t"] for event in events if event["event"] == "token"
        )

    def test_a_phone_number_is_redacted_before_it_is_sent(self, client, monkeypatch):
        self._saying(monkeypatch, "Ring the family on +1 (869) 555-0123 about it.")

        _status, events = post(client, auth=token(), message="what is saving")
        prose = self._prose(events)

        assert "555-0123" not in prose, "the reader received a phone number"
        assert "[a phone number]" in prose

    def test_a_link_is_stripped_before_it_is_sent(self, client, monkeypatch):
        """`stella` never gets a link, at any band."""
        self._saying(monkeypatch, "Read more at https://example.com/savings today.")

        _status, events = post(client, auth=token(), message="what is saving")
        prose = self._prose(events)

        assert "https://example.com/savings" not in prose
        assert "Read more" in prose

    def test_the_answer_is_still_delivered_when_no_gate_changes_it(self, client):
        """The common path: holding must not swallow an ordinary answer."""
        _status, events = post(client, auth=token(), message="what is saving")

        assert "Saving means keeping money for later." in self._prose(events)

    def test_what_is_stored_is_what_was_sent(self, client, monkeypatch):
        """
        The two used to disagree. `record.reply` read the interceptor's
        accumulated prose -- the UNCORRECTED text -- so Postgres and the
        response cache kept one version while the checkpoint kept another, and
        the model read back an answer the reader had never seen.
        """
        import app.turn as turn_service

        seen: list[str] = []

        original = turn_service.persist_turn

        async def capture(record):
            seen.append(record.reply)
            return await original(record)

        monkeypatch.setattr(turn_service, "persist_turn", capture)
        self._saying(monkeypatch, "Ring the family on +1 (869) 555-0123 about it.")

        _status, events = post(client, auth=token(), message="what is saving")
        prose = self._prose(events)

        assert seen, "the turn was never persisted"
        assert seen[-1] == prose, "stored text differs from delivered text"


class TestWhichMessageIsDelivered:
    """
    `final_reply` decides what the reader receives once the gates have run.

    Asserted directly rather than through the transport: the stream fixture
    runs without a checkpointer, so nothing carries between requests and the
    thread never HAS a previous answer to serve by mistake. A test driven
    through HTTP passed against the bug and against the fix alike, which is
    worse than no test.
    """

    def _state(self, *messages):
        return {"messages": list(messages)}

    def test_the_assistants_answer_is_delivered(self):
        from app.graph.main_graph import final_reply

        state = self._state(
            HumanMessage(content="what is saving"),
            AIMessage(content="Saving keeps money for later."),
        )

        assert final_reply(state) == "Saving keeps money for later."

    def test_a_decline_appended_after_the_answer_wins(self):
        """`ground_check` appends; the decline is the thing that may be served."""
        from app.graph.main_graph import final_reply

        state = self._state(
            HumanMessage(content="what is the rate"),
            AIMessage(content="It is 4.5%."),
            AIMessage(content="I do not have an answer for that."),
        )

        assert final_reply(state) == "I do not have an answer for that."

    def test_a_card_turn_delivers_nothing(self):
        """
        The regression this function was extracted for.

        A game or the eligibility wizard speaks through a directive and adds no
        message, so the thread ends on the reader's question. Looking backwards
        past it served the previous turn's answer again -- measured in the
        browser as an answer reappearing under an unrelated question, with the
        app never settling.
        """
        from app.graph.main_graph import final_reply

        state = self._state(
            HumanMessage(content="what is saving"),
            AIMessage(content="Saving keeps money for later."),
            HumanMessage(content="can we play true or false"),
        )

        assert final_reply(state) == ""

    def test_an_empty_thread_delivers_nothing(self):
        from app.graph.main_graph import final_reply

        assert final_reply({"messages": []}) == ""
        assert final_reply({}) == ""
