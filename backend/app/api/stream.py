"""The v2 turn, as server-sent events."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.messages import HumanMessage

from app import timing
from app import turn as turn_service
from app.auth import bearer_token
from app.config import get_settings
from app.graph.checkpointer import get_checkpointer, thread_config
from app.graph.identity import decode_session_token
from app.graph.main_graph import build_main_graph
from app.graph.nodes.hydrate import Unauthenticated
from app.graph.stream_interceptor import StreamInterceptor, WireEvent
from app.schemas.directives import (
    CHIP_LABEL_CHARS,
    CHIP_VALUE_CHARS,
    CitationsDirective,
    CitationRef,
    QuickRepliesDirective,
    QuickReplyOption,
    directive_payload,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2", tags=["graph"])

#: SSE headers.
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

#: A turn that produces nothing for this long is a turn something has gone wrong with.
TURN_TIMEOUT_SECONDS = 120.0

#: The longest question this transport will read.
MAX_MESSAGE_CHARS = 8_000

#: What a client may name a conversation. Wide enough for a UUID and for
#: `newThreadId`'s `t-<base36>-<base36>` fallback; the floor on length is what
#: keeps a guessable id like `probe-stream-1` out of a signed token.
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{16,128}$")

#: The same shape `/api/auth/anonymous` has always required of a device id, and
#: which this endpoint accepted anything in place of.
_DEVICE_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")

#: Directives that decorate an answer rather than being one. A turn carrying
#: only these, and no words, has said nothing to the reader.
DECORATIONS: frozenset[str] = frozenset({"quick_replies", "citations"})

#: How many cited rows one turn may send. Matches `CitationsDirective.refs`'s own
#: ceiling; the panel collapses them to at most a handful of distinct sources.
CITATION_REFS_MAX = 8

#: What to say when the graph produced no answer at all -- a bug, said out loud
#: rather than served as an empty message the reader cannot tell from a hang.
EMPTY_TURN: dict[str, str] = {
    "en": (
        "Sorry -- I lost my thread there and did not get an answer out. Could "
        "you ask me that again?"
    ),
    "es": (
        "Perdona, me perdí y no llegué a responderte. ¿Puedes preguntármelo "
        "otra vez?"
    ),
    "fr": (
        "Désolé, j'ai perdu le fil et je n'ai pas répondu. Peux-tu me le "
        "redemander?"
    ),
}


async def _events(token: str | None, body: dict[str, Any]) -> AsyncIterator[str]:
    """`_turn_frames`, measured.

    `app/timing.py` defines twenty stage constants and a ring buffer behind
    `/debug/timings`, and until now this module never imported it -- so
    `record_stage`, `mark_stage` and `annotate` were no-ops on every chat turn
    and only the two voice endpoints ever emitted a `turn_timing` line. The one
    latency number a chat turn produced was `elapsed_ms` on the `done` frame.

    A wrapper rather than a `with` around the body: the body is two hundred
    lines with a dozen early returns, and re-indenting all of it days before a
    demo is the kind of diff this work is meant to avoid. `bind` publishes
    through a ContextVar, and the inner generator is resumed in this same task,
    so everything it awaits sees the turn.
    """
    with timing.turn(endpoint="/v2/chat/stream"):
        async for frame in _turn_frames(token, body):
            yield frame


async def _turn_frames(token: str | None, body: dict[str, Any]) -> AsyncIterator[str]:
    """The turn, as encoded SSE frames."""
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
    # Who this turn is for. `begin` takes these, but the token is only decoded
    # here, inside the generator the wrapper is already measuring.
    timing.annotate(persona=claims.persona, lang=claims.locale, band=claims.age_band)

    interaction = body.get("__widget_interaction")
    game_score = body.get("__game_result")
    resume = body.get("__upload_result")
    message = str(body.get("message") or "").strip()
    # The reader's "Explain it simply" control. An answer-shaping request, so it
    # travels in the body; `hydrate` puts the same value into graph state.
    simple_mode = bool(body.get("simple_mode"))
    # A widget interaction, a game result and an upload resume are real turns with no prose.
    if not message and not interaction and not game_score and not resume:
        yield interceptor.error("empty_message", "There was nothing to answer.").encode()
        return

    # An upper bound on what one turn may cost.
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
        # Someone else's conversation.
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
        simple_mode=simple_mode,
        owner_id=owner_id,
    )

    # ── layer 1: this exact question, from this exact audience ──
    # Consulted before anything is embedded or generated.
    if message and not interaction and not _wants_card(message):
        cached = await turn_service.cached_answer(
            message,
            language=claims.locale,
            persona=claims.persona,
            account_status=claims.account_status,
            age_band=claims.age_band,
            simple_mode=simple_mode,
        )
        if cached is not None:
            logger.info("cache hit session=%s", thread_id)
            timing.annotate(cache_hit=True, cache_layer="exact")
            async for frame in _replay(interceptor, record, cached, started, claims):
                yield frame
            return

    # Started in flight and awaited later by `_settle`, so the first token is not delayed.
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

    # Just the message.
    payload: dict[str, Any] = {
        "messages": [HumanMessage(content=message)] if message else []
    }

    # A document the parent has just uploaded, resuming a paused registration.
    upload_result = body.get("__upload_result")
    graph_input: Any = payload
    if isinstance(upload_result, dict) and upload_result.get("document_id"):
        from langgraph.types import Command

        graph_input = Command(resume=upload_result)
        logger.info(
            "Resuming session %s with document %s.",
            thread_id,
            upload_result.get("document_id"),
        )

    try:
        # Not `subgraphs=True`: it doubles every answer, so subgraph directives ride in state.
        async for chunk in graph.astream(
            graph_input,
            config=config,
            stream_mode=["messages", "custom"],
        ):
            for event in await interceptor.process(chunk):
                # Prose is HELD, not sent. Every outbound safety gate runs a
                # graph step after the agent that produced the text -- the word
                # caps, the banned vocabulary, the PII redaction, the link
                # stripping, and `ground_check`'s decline -- so anything sent
                # here is pre-correction and cannot be taken back. Measured:
                # "bitcoin" reached the screen four times, and a decline arrived
                # welded onto the end of a finished answer.
                #
                # This costs nothing in perceived speed, which is the whole
                # reason it is possible. Nothing streams tokens: every prose
                # call is `ainvoke`, so LangGraph emits one message and this
                # branch fires exactly once per turn with the entire answer.
                # There is no incremental output to preserve.
                if event.event == "token":
                    # The agent's first text, NOT the reader's. `T_TTFT` is
                    # marked at the delivery below, once the gates have run;
                    # marking it here would keep reporting a moment when
                    # nothing is sent, and `timing.py` already derives
                    # `d_buffer_hold` as the difference between the two.
                    timing.mark_stage(timing.T_AGENT_FIRST_DELTA)
                    continue
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

        # Anything the sentinel machine was still holding.
        for event in interceptor.flush():
            if event.event == "token":
                continue
            yield event.encode()
    except Unauthenticated:
        await _settle(opening)
        yield interceptor.error(
            "unauthenticated", "Please sign in again to keep chatting."
        ).encode()
        return
    except Exception:
        # The traceback goes to the log; the reader gets a sentence with no internal names.
        logger.exception("v2 turn failed for session %s", thread_id)
        await _settle(opening)
        yield interceptor.error(
            "upstream", "The assistant is temporarily unavailable. Please try again."
        ).encode()
        return

    # ── the answer, once every gate has had it ──
    #
    # `persist` is the last node, so the reply it publishes has been through the
    # word caps, the vocabulary excision, the PII redaction, the link stripping
    # and `ground_check`'s decline. That is the text the reader gets, and it is
    # also the text that gets stored -- the two used to disagree, with Postgres
    # and the response cache keeping the uncorrected version while the
    # checkpoint kept the corrected one, so the model read back an answer the
    # reader had never seen.
    #
    # The fallback is what actually crossed the interceptor. A turn that halts
    # before `persist` publishes -- an upstream failure, a timeout -- has no
    # corrected text to serve, and silence would be worse than uncorrected
    # prose.
    turn = interceptor.turn or {}
    delivered = str(turn.get("reply") or "").strip() or interceptor.prose.strip()
    # Reset first, so `prose` ends up as exactly what the reader received rather
    # than the held text plus the corrected text. `record.reply` reads it below,
    # and so does the did-this-turn-say-anything check. The ordinals go back to
    # the start with it, because the held events took numbers with them.
    interceptor.restart_numbering()
    if delivered:
        # Time to first token, measured where the reader actually gets one.
        timing.mark_stage(timing.T_TTFT)
        # Through `token` rather than around it: citation markers are stripped
        # for display there, and the final message still carries them.
        yield interceptor.token(delivered).encode()

    # ── the turn's directives ──
    # Emitted after the prose, from the closing summary `persist` published.
    directives = _closing_directives(turn, claims=claims)

    # A paused `interrupt()` is asking the reader for something, and its payload is the directive.
    directives.extend(await _pending_interrupts(graph, config))

    # A turn that says nothing is a bug, and the reader should not be the one
    # who discovers it. Cards, widgets and a paused `interrupt()` all speak
    # through directives of their own, so only the decorations count as silence.
    if not interceptor.prose.strip() and all(
        directive.get("t") in DECORATIONS for directive in directives
    ):
        logger.error(
            "The turn for session %s produced no prose and nothing to act on "
            "(agent=%s, directives=%s); serving the fallback.",
            thread_id,
            turn.get("active_agent"),
            [directive.get("t") for directive in directives],
        )
        yield interceptor.token(
            EMPTY_TURN.get(claims.locale, EMPTY_TURN["en"])
        ).encode()

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

    # ── after the answer, once the reader already has everything ──
    record.reply = interceptor.prose
    record.directives = directives
    record.citations = list(turn.get("citations") or [])
    record.quick_replies = list(turn.get("quick_replies") or [])
    record.agent = turn.get("active_agent")
    record.card = _card_kind(directives)
    # Read off the finished turn: `cards` set it, and it is what makes this
    # reply personal to the reader who asked.
    record.story = bool(turn.get("story_topic"))

    await _settle(opening)
    await turn_service.persist_turn(record)
    await turn_service.cache_answer(record)
    # Compression is a model call, deliberately past `done`, so the reader never waits for it.
    await turn_service.summarise_thread(graph, config)


async def _pending_interrupts(graph: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Directives for whatever the graph is paused waiting for."""
    try:
        snapshot = await graph.aget_state(config)
    except Exception:
        logger.warning("Could not read the graph state for pending interrupts.", exc_info=True)
        return []

    found: list[dict[str, Any]] = []
    for task in getattr(snapshot, "tasks", ()) or ():
        for interrupt in getattr(task, "interrupts", ()) or ():
            value = getattr(interrupt, "value", None)
            if isinstance(value, dict) and value.get("t"):
                # `type` means nothing on the wire; `t` is the directive discriminator.
                found.append({key: item for key, item in value.items() if key != "type"})
            elif value is not None:
                logger.warning(
                    "A graph interrupt carried %s, which is not a directive; the "
                    "reader has no way to answer it.",
                    type(value).__name__,
                )
    return found


def _wants_card(message: str) -> bool:
    """Whether the card node will claim this turn.

    This is a cache guard, and getting it wrong is silent. The layer-1 cache
    answers before the graph runs at all, so a turn missing from here is
    replayed from somebody else's answer and the card node NEVER EXECUTES --
    which means any state it would have set is never set either.

    That is not theoretical. "Tell me a story" is a plain question to the cache
    and a latch to the card node: served from cache, the reply was right, the
    chips were right, and `awaiting_story_topic` was never written, so the
    reader's chosen topic came back as an ordinary question and no story was
    ever told. A video acceptance fails the same way.

    Every intent the card node claims belongs here.
    """
    from app.graph.nodes.intents import (
        wants_eligibility,
        wants_game,
        wants_story,
        wants_video,
    )

    return (
        wants_eligibility(message)
        or wants_game(message)
        or wants_story(message)
        or wants_video(message)
    )


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
    claims: Any = None,
) -> AsyncIterator[str]:
    """Serve a cached answer over the same wire shape as a live one."""
    yield interceptor.token(cached.reply).encode()

    # `claims` is threaded through so a replayed turn goes past the same link
    # gate a live one does. Without it, a cached answer written for an adult
    # would hand a five-year-old the links the live path withholds.
    directives = list(_closing_directives(
        {"quick_replies": cached.quick_replies, "citations": cached.citations},
        claims=claims,
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


def _chip(text: str) -> QuickReplyOption:
    """One follow-up, shortened to fit rather than rejected.

    The QA builder respects the cap, but the learning, registration and escalation
    agents write their own chips with nothing checking the length. The cap is
    cosmetic; raising here would discard a turn that has already been answered and
    paid for -- so the label is trimmed at a word boundary and the full question
    stays as what gets sent.
    """
    said = " ".join(text.split())
    label = said
    if len(label) > CHIP_LABEL_CHARS:
        clipped = label[: CHIP_LABEL_CHARS - 1]
        cut = clipped.rfind(" ")
        if cut >= CHIP_LABEL_CHARS // 2:
            clipped = clipped[:cut]
        label = f"{clipped.rstrip(' ,;:.') or clipped}…"
    return QuickReplyOption(label=label, value=said[:CHIP_VALUE_CHARS])


def _closing_directives(
    turn: dict[str, Any], *, claims: Any = None
) -> list[dict[str, Any]]:
    """The directives derivable from the finished turn, in render order."""
    out: list[dict[str, Any]] = list(turn.get("ui_directives") or [])

    chips = [str(chip).strip() for chip in (turn.get("quick_replies") or [])]
    chips = [chip for chip in chips if chip]
    if chips:
        out.append(
            directive_payload(
                QuickRepliesDirective(options=[_chip(chip) for chip in chips[:4]])
            )
        )

    refs = citation_refs(turn.get("citations") or [], claims=claims)
    if refs:
        out.append(directive_payload(CitationsDirective(refs=refs)))
    return out


def citation_refs(
    citations: list[dict[str, Any]], *, claims: Any = None
) -> list[CitationRef]:
    """The turn's citations, as the refs the client renders.

    Two things happen here and nowhere else, so that a live turn and a replayed
    cached one cannot drift apart:

    *The link gate.* `safety_out.strips_links` decides whether this reader gets
    links at all, and a citation is not the exception to it -- a five-year-old
    who never sees a URL in the prose should not be handed one in the panel. The
    source keeps its NAME either way, so nothing goes un-attributed; it simply
    is not a link. `claims` is effectively required: omitting it withholds every
    link rather than granting them.

    *A last validation.* The URL was validated when the citation was built, but
    a turn can also arrive from the response cache or the checkpointer, written
    by an older build against an older registry. Re-checking is cheap, and it is
    the only guarantee that what reaches an `href` was validated by THIS code.

    Deduplication is NOT done here. Every row keeps the URL it actually came
    from, and the panel groups the rows under their shared source -- so five
    chunks off one page render as one heading with five extracts beneath it,
    and a conversation reloaded from history groups identically without the
    server having to remember what it collapsed.
    """
    from app import sources
    from app.graph.account import YOUNGEST_BAND
    from app.graph.nodes.safety_out import strips_links

    # Fails CLOSED. `claims=None`, a claims object missing either field, or an
    # empty persona all resolve to the youngest reader, so the answer to "we do
    # not know who this is" is the same one `conversations._UnknownReader`
    # gives: a child until proven otherwise. Defaulting to `adult` here meant a
    # future call site that forgot to thread `claims` would quietly hand links
    # to every reader, and nothing would fail to say so.
    linkable = not strips_links(
        str(getattr(claims, "persona", "") or "stella"),
        str(getattr(claims, "age_band", "") or YOUNGEST_BAND),
    )

    refs: list[CitationRef] = []
    distinct: set[str] = set()
    unattributed = 0

    # `list(...)` rather than a slice on the argument: this is fed from JSONB, a
    # response-cache entry and a checkpoint, and one of those could hand over a
    # tuple, a generator or something with no `__getitem__` at all.
    for citation in list(citations or [])[:CITATION_REFS_MAX]:
        if not isinstance(citation, dict):
            continue
        raw = str(citation.get("url") or "")
        url = sources.safe_url(raw) if linkable else None
        if raw and url is None and linkable:
            # Validated once already, so reaching here means the stored value
            # came from an older build or a hand-edited row. Worth saying.
            logger.warning(
                "Dropped a stored citation URL that no longer validates (row %s).",
                citation.get("kb_id"),
            )
        if url:
            distinct.add(sources.canonical(url) or url)
        elif not str(citation.get("site") or citation.get("page") or ""):
            unattributed += 1

        # Clipped here as well as where the source was named. A stored turn can
        # carry a value written before the caps existed, and `CitationRef`'s
        # length limits raise from inside the streaming generator -- so an
        # over-long page title would not degrade one citation, it would kill
        # the turn, and `_replay` would serve the same failure every time the
        # question was asked again.
        refs.append(
            CitationRef(
                kb_id=str(citation.get("kb_id") or ""),
                title=str(citation.get("title") or ""),
                question=str(citation.get("question") or ""),
                snippet=str(citation.get("snippet") or ""),
                url=url or "",
                site=sources.clip(str(citation.get("site") or ""), sources.MAX_SITE_CHARS),
                page=sources.clip(str(citation.get("page") or ""), sources.MAX_PAGE_CHARS),
                # Withheld with the link, not just alongside it. `aspire.gov.kn`
                # IS a URL, and printing it under a source for a reader the
                # product never shows one to would defeat the gate by half.
                domain=str(citation.get("domain") or "")[:253] if linkable else "",
                updated=sources.clip(
                    str(citation.get("updated") or ""), sources.MAX_UPDATED_CHARS
                ),
            )
        )

    if refs:
        logger.info(
            "Citations: %d row(s), %d linkable source(s), %d with no source at "
            "all, links %s.",
            len(refs),
            len(distinct),
            unattributed,
            "on" if linkable else "withheld for this reader",
        )
    return refs


# ── the model calls this transport supplies to the graph ─────────────────────


async def _reprompt(instruction: str, text: str) -> str:
    """`safety_out`'s one retry."""
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
    """Rate-limit before the response is opened, not inside it."""
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
    """One turn through the graph."""
    token = bearer_token(authorization)
    _meter(request, token)

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    # Authentication is settled BEFORE the response starts, so it can be a real status code.
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
    """A widget interaction, answered as a turn."""
    token = bearer_token(authorization)
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


@router.post("/game/result")
async def game_result(
    request: Request, authorization: str | None = Header(default=None)
) -> StreamingResponse:
    """A finished game's score, answered as a turn."""
    token = bearer_token(authorization)
    _meter(request, token)

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    return StreamingResponse(
        _events(token, {"message": "", "__game_result": body}),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/documents/presign")
async def presign(
    request: Request, authorization: str | None = Header(default=None)
) -> dict[str, Any]:
    """A URL the browser may PUT one document to."""
    from app.storage.presign import (
        StorageUnavailable,
        owns_application,
        presign_upload,
    )

    claims = decode_session_token(bearer_token(authorization))
    if claims is None:
        raise HTTPException(status_code=401, detail="A valid session is required.")

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    # The application id is a resource identifier supplied by the client, so ownership is checked.
    requested = str(body.get("application_id") or claims.session_id)
    if not await owns_application(requested, claims):
        # 404, not 403.
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
    """Issue a graph session token for an already-authenticated caller."""
    from app.auth import optional_principal
    from app.limits import session_mint_rate_limit

    # Metered before anything is read or looked up: this endpoint had no limit
    # at all, and it is where the tokens for every metered endpoint come from.
    session_mint_rate_limit(request)

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

    # Both of these are signed into the token, and `sid` becomes the LangGraph
    # thread id, the conversation id and — until now — the rate-limit key. They
    # arrived from the request body unread: anything at all became a signed
    # claim. The database still carries what that allowed, 56 conversations
    # whose id is under thirty characters, `probe-stream-1` among them, and any
    # caller naming one of those could pick up a thread that has no owner.
    #
    # Not a UUID requirement, deliberately. `newThreadId` falls back to
    # `t-<base36>-<base36>` when `crypto.randomUUID` is unavailable — an older
    # Safari on a school tablet, or a plain-HTTP staging box, which is a fair
    # description of this audience. A charset and a floor on length keep those
    # working and reject the guessable ones. Anything malformed is REPLACED
    # rather than refused, so a bad client gets a fresh conversation instead of
    # an error it cannot act on.
    session_id = str(body.get("session_id") or "")
    if not _SESSION_ID_RE.match(session_id):
        if session_id:
            logger.warning("Replacing an unusable session id (%d chars).", len(session_id))
        session_id = str(uuid.uuid4())

    device_id = str(body.get("device_id") or "")
    if not _DEVICE_RE.match(device_id):
        device_id = "unknown"

    locale = str(body.get("locale") or "en")
    if locale not in ("en", "es", "fr"):
        locale = "en"

    requested = body.get("persona")
    # An anonymous account is a place to keep a visitor's chats until they sign up,
    # not a proof of who they are. Reading it as an identity derived `aurora/adult`
    # from its empty date of birth, which handed a signed-out visitor the guardian
    # row -- `register_agent` included. The id still travels, so those chats can
    # still be claimed at sign-up; only the access decision changes.
    proven = principal is not None and not principal.is_anonymous
    claims = await claims_for(
        str(principal.user_id) if proven else None,
        requested_persona=str(requested) if requested else None,
    )
    if claims.persona_request_refused:
        # Worth a log line: a client repeatedly asking to widen is either a bug or a probe.
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
        identity_proven=proven,
    )
    return {
        "token": token,
        "session_id": session_id,
        # Echoed so the client can pick the mascot and reading level without decoding the JWT.
        "persona": claims.persona,
        "age_band": claims.age_band,
        "account_status": claims.account_status,
        "locale": locale,
        # Whether the persona above is the one that was asked for.
        "persona_refused": claims.persona_request_refused,
    }


def sse_lines(payload: list[WireEvent]) -> str:
    """Encode a list of events. Used by the tests and by `curl` fixtures."""
    return "".join(event.encode() for event in payload)


def parse_sse(raw: str) -> list[dict[str, Any]]:
    """Read an SSE body back into events."""
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
