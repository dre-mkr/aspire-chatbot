"""The wire protocol, end to end, against a real FastAPI app."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault(
    "SESSION_SECRET", "test-only-secret-not-for-production-at-least-32-bytes"
)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402

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
        _status, events = post(client, auth=token(), message="what is saving")
        ordinals = [
            event["data"]["i"]
            for event in events
            if event["event"] in ("token", "directive", "done")
        ]
        assert ordinals == sorted(ordinals)
        assert len(set(ordinals)) == len(ordinals)

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
