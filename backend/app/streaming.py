"""The same answer as `/chat`, delivered a token at a time.

`POST /chat/stream` is additive. `/chat` is untouched and still serves the whole
reply in one response — it is the fallback, and it is what every existing client
and test still talks to. Nothing here changes that contract.

The wire format is AG-UI, because that is what `@tanstack/ai-client` speaks. The
alternative was inventing a private event vocabulary and writing an adapter on
the client to translate it, which is two formats to keep in agreement instead of
one.

## The thing this file exists to get right

A game or eligibility turn has no prose. The model is asked to be silent on
those turns and usually is; `/chat` does not depend on that, and drops any
narration it produced *before it crosses the wire* -- so the card is never
accompanied by a second, unaudited answer to the question the card is about to
answer properly.

Streaming breaks that guarantee by default: tokens are already on screen by the
time a tool call reveals what kind of turn this is. So text is not forwarded as
it arrives. Each assistant message is held until it is known not to be a
tool-calling message, and the whole turn is suppressed the moment a game or
eligibility tool fires.

The cost is real and worth stating: this does **not** reduce time-to-first-token
versus `/chat`. In a tool-using agent the final answer only begins after the
tools have run, and that is exactly when we learn whether there is an answer to
show. What streaming buys here is that a long reply arrives progressively
instead of all at once -- not that it starts sooner.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from app.timing import T_TTFT, TurnTimings

logger = logging.getLogger(__name__)

#: Tools whose presence means this turn is a card, and its prose must not ship.
SILENT_TOOLS = frozenset({"start_game", "start_eligibility_check"})


def sse(event: dict[str, Any]) -> str:
    """One AG-UI event, framed for `text/event-stream`.

    No `event:` line. AG-UI puts the discriminator in the JSON body, and a
    client reading `data:` alone gets everything it needs.
    """
    return f"data: {json.dumps(event, separators=(',', ':'))}\n\n"


class TurnBuffer:
    """Holds an assistant message until it is safe to send.

    The rule is narrow and mechanical: text belonging to a message that turns
    out to be calling a tool is discarded, and text belonging to a turn that
    started a card is discarded. Everything else is released in order.

    Deliberately not clever. A heuristic that usually keeps a puzzle's answer
    off the screen is not a guarantee, and this is the half of the design that
    must not depend on the model complying with a prompt.
    """

    def __init__(self) -> None:
        self.pending: list[str] = []
        self.released = ""
        #: The current message has emitted tool-call chunks, so it is a request
        #: to call a tool rather than an answer.
        self.is_tool_message = False
        #: A card tool fired this turn. Nothing more may be sent, ever.
        self.silenced = False
        self.started = False
        #: At least one tool has been called, so what kind of turn this is has
        #: already been decided. Until that is true, nothing is released.
        self.tools_ran = False

    def note_tool_call(self, name: str | None) -> None:
        self.is_tool_message = True
        self.tools_ran = True
        self.pending.clear()
        if name in SILENT_TOOLS:
            self.silenced = True
            self.released = ""

    def add(self, delta: str) -> str:
        """Accepts a delta and returns whatever may now be sent.

        Nothing is released before a tool has run, and that is the guarantee the
        whole file turns on. A card turn announces itself by calling its tool in
        the agent's first assistant message, so any preamble the model produced
        alongside it is still in hand and can be dropped. Releasing eagerly and
        retracting later is not an option: the retraction is a visible flash, and
        by then the words have been read.

        It costs nothing in the ordinary case. Answering anything here means
        retrieving first, so by the time real prose exists the tools have run.
        """
        if self.silenced or not delta:
            return ""
        self.pending.append(delta)
        if self.is_tool_message or not self.tools_ran:
            return ""
        out = "".join(self.pending)
        self.pending.clear()
        self.released += out
        return out

    def end_message(self) -> str:
        """A message finished. Returns anything held back that is now safe."""
        held = "" if (self.is_tool_message or self.silenced) else "".join(self.pending)
        self.pending.clear()
        self.is_tool_message = False
        self.released += held
        return held


async def agui_stream(
    *,
    thread_id: str,
    run_events: AsyncIterator[dict[str, Any]],
    timings: TurnTimings | None = None,
) -> AsyncIterator[str]:
    """Wraps a turn's events in the AG-UI envelope.

    `run_events` yields the app's own vocabulary -- `{"delta": ...}`,
    `{"tool": name}`, `{"done": payload}`, `{"error": message}` -- so the
    envelope and the agent plumbing stay separable and each can be read on its
    own.

    `timings` is optional and measurement-only. It exists here because this is
    the only place that knows when a token actually crossed the wire: the buffer
    above holds text back until a tool has run, so "the model produced a token"
    and "the reader saw one" are different moments, and TTFT is the second.
    Passing None -- as `/chat`'s tests do -- changes nothing.
    """
    run_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    buffer = TurnBuffer()
    #: `TEXT_MESSAGE_END` has been sent, so `done` must not send a second one.
    text_closed = False

    def start() -> str | None:
        """The `TEXT_MESSAGE_START` this message owes, the first time it is due."""
        if buffer.started:
            return None
        buffer.started = True
        return sse(
            {"type": "TEXT_MESSAGE_START", "messageId": message_id, "role": "assistant"}
        )

    def content(text: str) -> str:
        # The one funnel every visible token passes through, which is why the
        # TTFT stamp belongs here and not at any of the four call sites.
        if timings is not None:
            timings.mark(T_TTFT)
        return sse(
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": message_id, "delta": text}
        )

    yield sse({"type": "RUN_STARTED", "threadId": thread_id, "runId": run_id})

    try:
        async for event in run_events:
            if "message" in event:
                held = buffer.end_message()
                if held:
                    opening = start()
                    if opening:
                        yield opening
                    yield content(held)
                continue

            if "tool" in event:
                buffer.note_tool_call(event["tool"])
                continue

            if "delta" in event:
                text = buffer.add(event["delta"])
                if not text:
                    continue
                opening = start()
                if opening:
                    yield opening
                yield content(text)
                continue

            if "text_end" in event:
                # The model has stopped writing, and the turn has not finished:
                # sources, follow-ups and persistence are still to come. Closing
                # the message here is what lets the client reveal the last word
                # of the answer on time rather than holding it until all of that
                # lands. Anything still held back that turned out to be safe is
                # released first, because after this nothing more will be.
                held = buffer.end_message()
                if held:
                    opening = start()
                    if opening:
                        yield opening
                    yield content(held)
                if buffer.started:
                    text_closed = True
                    yield sse({"type": "TEXT_MESSAGE_END", "messageId": message_id})
                continue

            if "error" in event:
                yield sse(
                    {
                        "type": "RUN_ERROR",
                        "message": event["error"],
                        "runId": run_id,
                    }
                )
                return

            if "done" in event:
                # Anything held back that turned out to be safe — a reply the
                # model produced without calling a tool never met the release
                # condition, so it is still in hand here. Normally `text_end`
                # has already drained this; a caller that does not send one
                # still gets a correctly closed message.
                held = buffer.end_message()
                if held:
                    opening = start()
                    if opening:
                        yield opening
                    yield content(held)
                if buffer.started and not text_closed:
                    text_closed = True
                    yield sse({"type": "TEXT_MESSAGE_END", "messageId": message_id})
                # Everything `/chat` returns beside the prose: the sources and
                # which card -- if any -- this turn opened. One event so the
                # client applies them together, in the same commit as the answer
                # settling.
                #
                # No `return` here any more. The turn is announced as soon as it
                # is known, and the follow-up chips are still being written; the
                # run finishes when they arrive, below.
                yield sse(
                    {
                        "type": "CUSTOM",
                        "name": "aspire.turn",
                        "value": event["done"],
                    }
                )
                continue

            if "follow_ups" in event:
                # Chips, late and on their own. They cost a second model call,
                # which is the whole reason they are not in `aspire.turn`: making
                # the sources and the action row wait for them left a finished
                # answer looking unfinished for seconds at a time.
                yield sse(
                    {
                        "type": "CUSTOM",
                        "name": "aspire.follow_ups",
                        "value": {"follow_ups": event["follow_ups"]},
                    }
                )
                continue

        # Reached when `run_events` is exhausted. A turn that ended without a
        # `follow_ups` event -- a card turn, an error path that returned early --
        # still has to be closed.
        yield sse({"type": "RUN_FINISHED", "threadId": thread_id, "runId": run_id})
    except Exception:
        logger.exception("Streaming turn failed for thread %s", thread_id)
        yield sse(
            {
                "type": "RUN_ERROR",
                "message": "The assistant is temporarily unavailable. Please try again.",
                "runId": run_id,
            }
        )
