"""The v2 turn, as server-sent events.

    event: token      data: {"i": 3, "t": "Saving means"}
    event: directive  data: {"i": 4, "d": {"t": "quick_replies", ...}}
    event: done       data: {"i": 9, "usage": {...}}
    event: error      data: {"code": "unauthenticated", "message": "..."}

Mounted at `/v2/chat/stream`, and it is the chat. `/chat` and `/chat/stream`
are gone: they were one agent behind one system prompt, with no age band, no
access matrix, no outbound gate and no router, and keeping them beside this
would have left a second door into the same product with none of those.

Everything they did that a reader depends on lives somewhere specific now --
persistence and the response cache in `app/turn.py`, card turns in
`app/graph/nodes/cards.py`, chips in the agents that emit them.

## Prose streams. Directives do not wait for it, and it does not wait for them.

`graph.astream(stream_mode=["messages", "custom"])` gives two interleaved
channels: model tokens, and structured payloads a node wrote deliberately. The
interceptor turns both into wire events sharing one ordinal counter, so the
client can place a directive between two specific tokens without depending on
packet timing.

Nothing is buffered to the end. The first token leaves this process the moment
the model produces it -- which is the property `/chat/stream` was built for and
the reason it is not being replaced by something that assembles a JSON object.

## Errors

An error event is sent and the stream closes. It is never a retry: the graph
records the question before it answers it, so retrying would ask the model
twice and append a second turn. `error` carries a code the client can branch on
and a message safe to show a child -- which means the message names no
component, no provider and no rule.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.messages import HumanMessage

from app import turn as turn_service
from app.config import get_settings
from app.graph.checkpointer import get_checkpointer, thread_config
from app.graph.identity import decode_session_token
from app.graph.main_graph import build_main_graph
from app.graph.nodes.hydrate import Unauthenticated
from app.graph.stream_interceptor import StreamInterceptor, WireEvent
from app.schemas.directives import (
    CitationsDirective,
    CitationRef,
    QuickRepliesDirective,
    QuickReplyOption,
    directive_payload,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2", tags=["graph"])

#: SSE headers.
#:
#: `X-Accel-Buffering: no` is the one that is easy to forget and impossible to
#: debug from the client: nginx buffers proxied responses by default, so without
#: it the whole stream arrives at once after the turn completes and every
#: latency property this transport exists for is silently gone in production
#: and present in development.
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

#: A turn that produces nothing for this long is a turn something has gone
#: wrong with. The client's own timeout is shorter; this is the backstop that
#: stops a hung provider holding a connection open indefinitely.
TURN_TIMEOUT_SECONDS = 120.0

#: The longest question this transport will read.
#:
#: Matches the cap the v1 pydantic schema enforced. v2 reads a raw dict so that
#: `hydrate` can see -- and log -- a client trying to set its own persona, and
#: the cost of that choice is that every bound the model gave for free has to be
#: written down here instead.
MAX_MESSAGE_CHARS = 8_000


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


async def _events(token: str | None, body: dict[str, Any]) -> AsyncIterator[str]:
    """The turn, as encoded SSE frames.

    Everything is inside one generator and one try/except on purpose: a
    `StreamingResponse` that raises mid-body produces a truncated response with
    a 200 status, which the client cannot distinguish from a successful short
    answer. Catching here means every failure arrives as an `error` event.

    ## The order of the bookkeeping around the graph

        cache lookup ─┐
        open the conversation (in flight)
                      └─► graph.astream ─► directives ─► done
                                                          │
                                     persist ─ cache ─ summarise

    Nothing after `done` can take the answer away, which is why persistence,
    caching and summarisation all sit there. Nothing before the graph may block
    on a database round trip that the reader would feel, which is why the
    conversation write is started and not awaited: `open_conversation`'s
    guarantee is that a turn whose answer fails still leaves the question
    behind, and a task created before the graph runs delivers that whether or
    not the graph raises.
    """
    interceptor = StreamInterceptor(widgets_enabled=get_settings().widgets_enabled)
    started = time.monotonic()

    claims = decode_session_token(token)
    if claims is None:
        yield interceptor.error(
            "unauthenticated", "Please sign in again to keep chatting."
        ).encode()
        return

    interceptor.age_band = claims.age_band
    interceptor.locale = claims.locale

    interaction = body.get("__widget_interaction")
    message = str(body.get("message") or "").strip()
    if not message and not interaction:
        yield interceptor.error("empty_message", "There was nothing to answer.").encode()
        return

    # An upper bound on what one turn may cost.
    #
    # This transport reads a raw dict rather than a pydantic model -- deliberately,
    # so `hydrate` can SEE a client's attempt to set `persona` and log it -- and
    # the consequence was that nothing bounded `message` at all. A 2MB body was
    # accepted and answered, which is a model bill an unauthenticated caller can
    # write: an anonymous session is free, and the rate limiter counts REQUESTS,
    # not bytes, so 30 requests a minute at 2MB each is the ceiling it enforces.
    #
    # 8,000 characters is the cap the v1 schema carried and nothing about the
    # graph needs more; the longest legitimate turn measured here is a few
    # hundred. Refused rather than truncated: silently answering half a question
    # is worse than saying it was too long.
    if len(message) > MAX_MESSAGE_CHARS:
        logger.warning(
            "Refused a %d-character message (cap %d).", len(message), MAX_MESSAGE_CHARS
        )
        yield interceptor.error(
            "message_too_long",
            "That message is too long for me to read. Could you shorten it?",
        ).encode()
        return

    thread_id = claims.session_id
    owner_id = await turn_service.resolve_owner(claims.user_id)
    if not await turn_service.owns_thread(thread_id, owner_id):
        # Someone else's conversation. Refused rather than answered into,
        # because a graph session token carries a persona and an age band and
        # continuing a stranger's thread would carry them into it.
        logger.warning(
            "Refusing a turn on conversation %s: it belongs to somebody else.",
            thread_id,
        )
        yield interceptor.error(
            "forbidden", "That conversation is not available. Start a new one."
        ).encode()
        return

    record = turn_service.TurnRecord(
        thread_id=thread_id,
        question=message,
        reply="",
        language=claims.locale,
        persona=claims.persona,
        account_status=claims.account_status,
        age_band=claims.age_band,
        owner_id=owner_id,
    )

    # ── layer 1: this exact question, from this exact audience ──────────────
    #
    # Consulted before anything is embedded and before the graph is built. A
    # hit skips the whole turn -- which is the point: the four landing starter
    # chips are the highest-collision strings in the product.
    #
    # Skipped for two kinds of turn:
    #
    #   * a widget interaction -- a reply to something this child did, with no
    #     question to key on;
    #   * anything that wants a CARD. `turn.cacheable` already refuses to write
    #     one, but the lookup has to refuse to read one too, and for a reason
    #     the write side cannot cover: an entry stored before the card matcher
    #     existed, or before it recognised a phrasing, is prose sitting under a
    #     key a card turn now hashes to. Observed live -- "can we play true or
    #     false" replayed a cached lesson instead of opening a game.
    if message and not interaction and not _wants_card(message):
        cached = await turn_service.cached_answer(
            message,
            language=claims.locale,
            persona=claims.persona,
            account_status=claims.account_status,
            age_band=claims.age_band,
        )
        if cached is not None:
            logger.info("cache hit session=%s", thread_id)
            async for frame in _replay(interceptor, record, cached, started):
                yield frame
            return

    # In flight, not awaited. See the docstring.
    opening = asyncio.create_task(turn_service.open_conversation(record))

    checkpointer = await get_checkpointer()
    graph = build_main_graph(
        token=token,
        body=body,
        reprompt=_reprompt,
        classifier_invoke=_classifier_invoke,
        checkpointer=checkpointer,
    )
    config = thread_config(thread_id)

    # Just the message. An interaction is NOT passed in the initial state --
    # `hydrate` reads it off the request body, because `hydrate` clears
    # `safety_flags` to drop the previous turn's outputs and would wipe anything
    # placed here before `classify` could route on it. See
    # `hydrate.CONTINUATION_FIELDS`.
    payload: dict[str, Any] = {
        "messages": [HumanMessage(content=message)] if message else []
    }

    try:
        async for chunk in graph.astream(
            payload,
            config=config,
            stream_mode=["messages", "custom"],
        ):
            for event in await interceptor.process(chunk):
                yield event.encode()
            if time.monotonic() - started > TURN_TIMEOUT_SECONDS:
                logger.warning(
                    "Turn for session %s exceeded %.0fs; closing the stream.",
                    thread_id,
                    TURN_TIMEOUT_SECONDS,
                )
                yield interceptor.error(
                    "timeout", "That took too long. Please try again."
                ).encode()
                await _settle(opening)
                return

        # Anything the sentinel machine was still holding. Held prose was only
        # held in case it became a sentinel; the turn is over, so it did not.
        for event in interceptor.flush():
            yield event.encode()
    except Unauthenticated:
        await _settle(opening)
        yield interceptor.error(
            "unauthenticated", "Please sign in again to keep chatting."
        ).encode()
        return
    except Exception:
        # The traceback goes to the log; the reader gets a sentence with no
        # component names, no provider names and no rule descriptions in it.
        # The question is still recorded -- that is what `opening` is for.
        logger.exception("v2 turn failed for session %s", thread_id)
        await _settle(opening)
        yield interceptor.error(
            "upstream", "The assistant is temporarily unavailable. Please try again."
        ).encode()
        return

    # ── the turn's directives ───────────────────────────────────────────────
    #
    # Emitted AFTER the prose, from the settled state, rather than during it.
    # Quick replies and citations are both properties of the finished answer:
    # `safety_out` can rewrite the chips, and the grounding check can drop a
    # citation, so sending either early would mean sending one the turn then
    # changed its mind about.
    turn = interceptor.turn or {}
    directives = _closing_directives(turn)
    for directive in directives:
        yield interceptor.directive(directive).encode()

    yield interceptor.done(
        {
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "agent": turn.get("active_agent"),
            "speak": bool(turn.get("speak", False)),
            "thread_id": thread_id,
            **interceptor.stats(),
        }
    ).encode()

    # ── after the answer ────────────────────────────────────────────────────
    #
    # The reader has everything. Nothing below this line may raise into the
    # stream, and each of these three swallows its own failures.
    record.reply = interceptor.prose
    record.directives = directives
    record.citations = list(turn.get("citations") or [])
    record.quick_replies = list(turn.get("quick_replies") or [])
    record.agent = turn.get("active_agent")
    record.card = _card_kind(directives)

    await _settle(opening)
    await turn_service.persist_turn(record)
    await turn_service.cache_answer(record)
    # Compression is a model call and it is deliberately out here, past `done`,
    # so the reader never waits through it. See `turn.summarise_thread`.
    await turn_service.summarise_thread(graph, config)


def _wants_card(message: str) -> bool:
    """Whether the card node will claim this turn.

    The same two matchers the node itself uses, so the cache and the graph
    cannot disagree about what a card turn is. Cheap enough to run twice: two
    regex sweeps over one sentence, against a cache round trip and a graph.
    """
    from app.graph.nodes.intents import wants_eligibility, wants_game

    return wants_eligibility(message) or wants_game(message)


def _card_kind(directives: list[dict[str, Any]]) -> str | None:
    """Whether this turn opened a card, and which. Decides the history line."""
    for directive in directives:
        if directive.get("t") in ("game", "eligibility"):
            return str(directive["t"])
    return None


async def _settle(task: "asyncio.Task[None]") -> None:
    """Wait for the conversation write, without letting it break the turn."""
    try:
        await task
    except Exception:
        logger.warning("The opening conversation write failed.", exc_info=True)


async def _replay(
    interceptor: StreamInterceptor,
    record: "turn_service.TurnRecord",
    cached: "turn_service.CachedTurn",
    started: float,
) -> AsyncIterator[str]:
    """Serve a cached answer over the same wire shape as a live one.

    Sent as ONE token event rather than retimed into fake deltas. A cached
    answer that pretends to be typed is a cached answer that gives up the whole
    latency win it exists for, and the client's reveal handles a single large
    delta correctly -- see `settled.ts`, which paces from its own buffer rather
    than from packet arrival.

    The conversation is still opened and the turn is still persisted. v1's
    `/chat` cache hit returned without recording anything, which left a
    question in the rail with no reply behind it whenever the hit was the first
    turn of a thread; this does not repeat that.
    """
    yield interceptor.token(cached.reply).encode()

    directives = list(_closing_directives(
        {"quick_replies": cached.quick_replies, "citations": cached.citations}
    ))
    for directive in directives:
        yield interceptor.directive(directive).encode()

    yield interceptor.done(
        {
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "agent": "cache",
            "speak": False,
            "thread_id": record.thread_id,
            "cached": True,
            **interceptor.stats(),
        }
    ).encode()

    record.reply = cached.reply
    record.citations = cached.citations
    record.quick_replies = cached.quick_replies
    record.agent = "cache"
    await turn_service.open_conversation(record)
    await turn_service.persist_turn(record)


def _closing_directives(turn: dict[str, Any]) -> list[dict[str, Any]]:
    """The directives derivable from the finished turn, in render order.

    Node-emitted directives first, then chips, then citations. That is reading
    order under an answer, and it is the order the client renders them in
    without having to sort.
    """
    out: list[dict[str, Any]] = list(turn.get("ui_directives") or [])

    chips = turn.get("quick_replies") or []
    if chips:
        out.append(
            directive_payload(
                QuickRepliesDirective(
                    options=[
                        QuickReplyOption(label=chip, value=chip) for chip in chips[:4]
                    ]
                )
            )
        )

    citations = turn.get("citations") or []
    if citations:
        out.append(
            directive_payload(
                CitationsDirective(
                    refs=[
                        CitationRef(
                            kb_id=citation.get("kb_id", ""),
                            title=citation.get("title", ""),
                        )
                        for citation in citations[:8]
                    ]
                )
            )
        )
    return out


# ── the model calls this transport supplies to the graph ─────────────────────


async def _reprompt(instruction: str, text: str) -> str:
    """`safety_out`'s one retry.

    Uses the answer model rather than the classifier's: this is a rewrite of
    prose a reader will see, and a smaller model rewriting a mascot's voice
    produces something that no longer sounds like the mascot.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.agent import build_chat_model

    model = build_chat_model()
    response = await model.ainvoke(
        [
            SystemMessage(content=instruction),
            HumanMessage(content=text),
        ]
    )
    content = response.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return text


async def _classifier_invoke(system: str, user: str) -> str:
    from app.graph.nodes.classify import default_invoke

    return await default_invoke(system, user)


def _meter(request: Request, token: str | None) -> None:
    """Rate-limit before the response is opened, not inside it.

    An `HTTPException` raised inside a streaming generator does not become a
    429 -- the status line has already gone out with a 200, and the client sees
    a truncated body. So the token is decoded twice on a metered turn: once
    here to find out who to count, once inside the generator. It is an HMAC
    verification of a short string; the alternative is a rate limit the client
    cannot tell apart from a network fault.
    """
    from app.limits import graph_rate_limit

    claims = decode_session_token(token)
    graph_rate_limit(
        request,
        session_id=claims.session_id if claims else "",
        user_id=claims.user_id if claims else None,
    )


@router.post("/chat/stream")
async def chat_stream_v2(
    request: Request, authorization: str | None = Header(default=None)
) -> StreamingResponse:
    """One turn through the graph.

    The body is read as a raw dict rather than a pydantic model, deliberately.
    `hydrate` has to SEE a client's attempt to set `persona` in order to log it,
    and a typed model with `extra="ignore"` would silently drop the field before
    anything could notice -- turning a security signal into no signal at all.
    """
    token = _bearer(authorization)
    _meter(request, token)

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    # Authentication is settled BEFORE the response starts, so it can be a real
    # status code.
    #
    # This used to return 200 with `event: error data: {"code":"unauthenticated"}`
    # inside the body for an unauthenticated caller. SSE does not force that --
    # nothing had been written yet at this point -- and a 200 carrying a failure
    # is a lie to every monitoring system, which counts it as a success.
    #
    # The body keeps the same `{code, message}` shape the SSE error frame uses,
    # so the client has one thing to read whichever way the failure arrives.
    # `_events` still re-checks: it is reachable from the widget path too, and a
    # guard that exists in one caller is a guard that goes missing in the next.
    if decode_session_token(token) is None:
        return JSONResponse(
            status_code=401,
            content={
                "code": "unauthenticated",
                "message": "Please sign in again to keep chatting.",
            },
        )

    return StreamingResponse(
        _events(token, body),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/widget/interaction")
async def widget_interaction(
    request: Request, authorization: str | None = Header(default=None)
) -> StreamingResponse:
    """A widget interaction, answered as a turn.

    It is a TURN, not telemetry, and that is why it streams back through the
    same transport: the agent must respond within one turn referencing the
    child's actual numbers, and a fire-and-forget endpoint would make that
    impossible to deliver.

    The interaction rides in on `safety_flags` rather than as a message,
    because it is not something the child said. Putting it in `messages` would
    mean the model reads "widget_interaction {...}" back as dialogue on every
    later turn.
    """
    token = _bearer(authorization)
    _meter(request, token)

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    return StreamingResponse(
        _events(token, {"message": "", "__widget_interaction": body}),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/documents/presign")
async def presign(
    request: Request, authorization: str | None = Header(default=None)
) -> dict[str, Any]:
    """A URL the browser may PUT one document to.

    Returns 503 rather than accepting the upload when storage is unconfigured.
    A fallback that routed file bytes through this process would mean the safe
    path silently stops being used the moment a key is missing -- see
    `storage/presign.py`.
    """
    from app.storage.presign import (
        StorageUnavailable,
        owns_application,
        presign_upload,
    )

    claims = decode_session_token(_bearer(authorization))
    if claims is None:
        raise HTTPException(status_code=401, detail="A valid session is required.")

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    # The application id is a RESOURCE IDENTIFIER supplied by the client, and it
    # was previously trusted. Anyone could mint an anonymous session at
    # `/v2/session` and ask for a signed PUT scoped to somebody else's
    # application -- including their `national_id` slot -- because nothing
    # compared the id to the caller.
    #
    # `owns_application` is the same shape as `turn.owns_thread`, which this API
    # already applies to conversations one file over. The default is unchanged:
    # a caller who names no application still gets their own session's.
    requested = str(body.get("application_id") or claims.session_id)
    if not await owns_application(requested, claims):
        # 404, not 403. Confirming that an application id exists but belongs to
        # somebody else is itself a disclosure -- the same reasoning
        # `load_transcript` uses for "not yours" and "not there".
        logger.warning(
            "Refused a presign for application %s from session %s.",
            requested,
            claims.session_id,
        )
        raise HTTPException(status_code=404, detail="No such application.")

    try:
        signed = presign_upload(
            application_id=requested,
            slot=str(body.get("slot") or "document"),
            mime=str(body.get("mime") or ""),
            size_bytes=int(body.get("size") or 0),
        )
    except StorageUnavailable:
        logger.error("An upload was requested but no object storage is configured.")
        raise HTTPException(
            status_code=503,
            detail="Uploads are not available right now. Please try again later.",
        ) from None
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None

    return {
        "url": signed.url,
        "document_id": signed.document_id,
        "headers": signed.headers,
        "expires_at": signed.expires_at.isoformat(),
    }


@router.post("/session")
async def mint_session(request: Request) -> dict[str, Any]:
    """Issue a graph session token for an already-authenticated caller.

    The claims it signs -- persona, age band, account status -- are derived
    from the caller's own record by `graph/account.py`, never from the request.
    That is the whole security property of this endpoint: a body field naming
    an age band is ignored here for exactly the same reason `hydrate` ignores
    one, and for a much sharper consequence, because the band decides whether
    `register_agent` (which collects a national ID) is reachable.

    Two fields the client MAY set, and neither grants anything:

      * `locale`, which chooses which copy is shown;
      * `persona`, which is honoured only when it is *narrower* than the one
        derived from the account -- an adult may ask for Nova instead of
        Aurora, a six-year-old may not ask for Aurora instead of Stella. See
        `account._narrowing`.

    `session_id` is the conversation thread. Continuing an existing one is
    allowed and normal; whether the caller may actually turn in it is checked
    per-turn against the conversation's owner (`turn.owns_thread`), because
    that is the check that has to hold even for a token minted honestly.
    """
    from app.auth import optional_principal

    principal = await optional_principal(request.headers.get("authorization"))

    from app.graph.account import claims_for
    from app.graph.identity import mint_session_token

    body: dict[str, Any] = {}
    try:
        parsed = await request.json()
        if isinstance(parsed, dict):
            body = parsed
    except Exception:
        body = {}

    session_id = str(body.get("session_id") or uuid.uuid4())
    device_id = str(body.get("device_id") or "unknown")
    locale = str(body.get("locale") or "en")
    if locale not in ("en", "es", "fr"):
        locale = "en"

    requested = body.get("persona")
    claims = await claims_for(
        str(principal.user_id) if principal else None,
        requested_persona=str(requested) if requested else None,
    )
    if claims.persona_request_refused:
        # Worth a line in the log: a client repeatedly asking to widen is
        # either a bug or a probe, and neither is visible without this.
        logger.warning(
            "Refused a request for persona %r on a %s band session.",
            requested,
            claims.age_band,
        )

    token = mint_session_token(
        session_id=session_id,
        user_id=str(principal.user_id) if principal else None,
        device_id=device_id,
        persona=claims.persona,
        age_band=claims.age_band,
        account_status=claims.account_status,
        locale=locale,
    )
    return {
        "token": token,
        "session_id": session_id,
        # Echoed so the client can render the right mascot and reading level
        # without decoding a JWT it must not depend on the shape of.
        "persona": claims.persona,
        "age_band": claims.age_band,
        "account_status": claims.account_status,
        "locale": locale,
    }


def sse_lines(payload: list[WireEvent]) -> str:
    """Encode a list of events. Used by the tests and by `curl` fixtures."""
    return "".join(event.encode() for event in payload)


def parse_sse(raw: str) -> list[dict[str, Any]]:
    """Read an SSE body back into events. The inverse of `WireEvent.encode`.

    Lives here rather than in the tests because the eval harness reads streams
    too, and two parsers for one format is one parser too many.
    """
    events: list[dict[str, Any]] = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        name = ""
        data = ""
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line[7:].strip()
            elif line.startswith("data: "):
                data = line[6:]
        if not name:
            continue
        try:
            events.append({"event": name, "data": json.loads(data)})
        except json.JSONDecodeError:
            continue
    return events
