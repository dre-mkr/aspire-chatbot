"""Everything the graph emits, turned into wire events with stable ordinals.

Sits between `graph.astream(...)` and the SSE writer. One class, one method:
`process(chunk) -> list[WireEvent]`. Nothing else in the streaming path knows
about langgraph's chunk shapes, and nothing in the graph knows about SSE.

## The ordinal

Every event carries a monotonically increasing `i`. It is the only thing that
lets the client put a directive back in the right place in the prose: SSE
guarantees order over one connection, but the client's own rendering is
asynchronous -- a directive that arrives between two tokens must render between
those two tokens even if React batches the updates differently.

The counter is over EVENTS, not characters. A token event and a directive event
are each one tick.

## Widget sentinels (D1)

The learning agent emits widgets inline in its prose:

    Here is how it grows.⟦widget⟧{"kind":"growth_stack",...}⟦/widget⟧ Try it.

U+27E6 and U+27E7 -- MATHEMATICAL LEFT/RIGHT WHITE SQUARE BRACKET. Not backtick
fences, and that choice is load-bearing: a model explaining code, JSON, or
markdown emits triple backticks constantly, and a transport that collides with
ordinary output is a transport that eats ordinary output. These two codepoints
do not appear in this product's prose in any of its three locales.

Four rules govern the buffering, and each of them exists because the obvious
implementation fails on it:

  1. **A partial sentinel must not be forwarded.** Tokens split anywhere, so
     `⟦wid` can arrive alone. Forwarding it puts a stray bracket on screen a
     tick before the widget appears. So a tail that could still become an
     opening sentinel is held.

  2. **Widget JSON must never reach the client.** Once open, nothing is
     forwarded until the closing sentinel. A client that received half a JSON
     object would have to decide whether to render it, and there is no correct
     answer to that question.

  3. **Validation failure emits nothing at all.** Not an error event, not a
     placeholder. The child gets prose, and the gate that failed is logged.
     A visible failure would be a child being shown that something went wrong
     with something they never knew was coming.

  4. **An unterminated sentinel must not hang the stream.** The buffer is
     capped; past the cap the whole thing is discarded, forwarding resumes, and
     the turn completes. A model that opens a widget block and never closes it
     costs one widget, not the reply.

## Only the learning agent may emit a widget

Asserted here rather than trusted. A widget arriving while `qa_agent` is active
is dropped and logged: the widget system is a teaching device with a curriculum
behind it, and a Q&A turn producing one means either a prompt leaked between
agents or something is being tried.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings
from app.schemas.directives import WidgetDirective, directive_payload
from app.widgets.sentinel import CLOSE, OPEN

logger = logging.getLogger(__name__)

# `OPEN` / `CLOSE` (U+27E6 / U+27E7) are re-exported from `widgets.sentinel`,
# which is also what `safety_out` splits on. One definition, because two copies
# of a protocol marker is a protocol with two versions.
__all__ = ["OPEN", "CLOSE", "WIDGET_AGENTS", "INTERNAL_NODES", "StreamInterceptor"]

#: The agents that may emit widgets.
#:
#: All three learning names, because they are ONE subgraph registered three
#: times (`agents/learn/graph.py:register`) and the difference between them is
#: which mastery row they write. A guardian previewing a lesson and a signed-out
#: visitor sampling one are looking at the same teaching, and a taste of a
#: lesson with the interactive part silently dropped is a worse advertisement
#: for it than no taste at all.
WIDGET_AGENTS: frozenset[str] = frozenset(
    {"learn_agent", "learning_preview", "learning_sample"}
)

#: Nodes whose model calls are INTERNAL and must never reach the reader.
#:
#: `stream_mode="messages"` streams tokens from every model call in the graph,
#: not only the one writing the answer. Without this filter the classifier's
#: `{"agent": "qa_agent", "confidence": 0.99}` is streamed to the client as
#: prose, in front of the answer -- which is exactly what happened the first
#: time this was run end to end.
#:
#: A deny-list rather than an allow-list, because the prose-producing nodes live
#: inside agent subgraphs and their names are that subgraph's business. Adding a
#: node here is the obligation that comes with adding an internal model call;
#: the failure mode of forgetting is loud and immediate, which is why a
#: deny-list is safe in a way it usually is not.
INTERNAL_NODES: frozenset[str] = frozenset(
    {
        "classify",        # routing JSON
        "rewrite_query",   # the search query, not an answer
        "safety_out",      # the re-prompt's rewrite, streamed twice otherwise
        "plan_widget",     # which primitive, as JSON
        "doc_check",       # a vision verdict, as JSON
        "persist",         # the rolling summary
        "summarise",       # the escalation summary
        # The tutor is here for a DIFFERENT reason than the rest of this list,
        # and it is the more important one.
        #
        # Everything above is suppressed because its model output is machinery --
        # JSON a reader must not see. The tutor's model output is prose, and it is
        # suppressed because it has not been CHECKED yet. `agents/learn/render.py`
        # validates a lesson against the band contract and regenerates it once if
        # it fails, and neither is possible for text that has already been
        # forwarded token by token. So the tutor emits its lesson explicitly, on
        # the custom channel, after it has passed -- see `_on_custom`'s `prose`
        # branch.
        #
        # The invariant this buys: no token a model produced reaches a child
        # without having passed the band contract first.
        "tutor",
    }
)


@dataclass(frozen=True, slots=True)
class WireEvent:
    """One SSE event, before it is serialised.

    `event` is the SSE event name; `data` is the JSON object that follows it.
    A dataclass rather than a dict so that a typo in an event name is a
    construction error rather than an event the client silently ignores.
    """

    event: str
    data: dict[str, Any]

    def encode(self) -> str:
        """The event in SSE wire format.

        `ensure_ascii=False` keeps EC$ and accented text as themselves rather
        than as escapes -- the stream is UTF-8 and the client decodes it as
        such. The double newline terminates the event and is not optional.
        """
        body = json.dumps(self.data, ensure_ascii=False, separators=(",", ":"))
        return f"event: {self.event}\ndata: {body}\n\n"


#: A citation marker as `generate` is instructed to write it: `[ASP-001]`.
#:
#: These are the machinery of the grounding check, not copy. `ground_check`
#: parses them out of the answer to prove the model can point at the row it used
#: -- an answer citing nothing is escalated rather than served -- and the ids
#: then travel to the client as a `citations` directive, which the transcript
#: renders as a "1 source" disclosure.
#:
#: Which leaves the marker itself with nothing to do except sit in the middle of
#: a sentence a six-year-old is reading. Stripped here rather than at the model:
#: telling the model not to emit them would mean removing the grounding check's
#: only input.
_CITATION = re.compile(r"[ \t]*\[[A-Za-z]{2,8}-\d{1,6}\]")

#: The longest a partial marker can be before it cannot be one. `[` plus eight
#: letters, a hyphen and six digits is sixteen characters; a run longer than
#: that with no `]` is ordinary bracketed prose and must be released.
_CITATION_MAX = 16


def strip_citation_markers(text: str) -> str:
    """Remove `[KB-001]` markers, with the space that precedes them."""
    return _CITATION.sub("", text)


def _partial_citation_suffix(text: str) -> int:
    """How many trailing characters might still become a citation marker.

    A chunk boundary falls inside `[ASP-001]` constantly -- it is nine
    characters and the model emits a few at a time -- so releasing the tail
    unconditionally would put `[ASP` on screen and then `-001]` after it, which
    is worse than leaving the marker whole.

    The SPACE in front is held with it, and that detail is the whole reason this
    is fiddly. `strip_citation_markers` removes the marker and the space before
    it, so that "programme. [ASP-001] It" closes up to "programme. It". If the
    space was released in an earlier chunk, the regex never sees the two
    together and the reader is left with a double space and a stranded " .".
    Measured across chunk sizes 1, 2, 3, 5 and 9 -- every one of them produced
    it before this held the space.
    """
    open_at = text.rfind("[")
    if open_at == -1:
        # No bracket, but a trailing space might be the one that precedes the
        # marker in the next chunk.
        trailing = len(text) - len(text.rstrip(" \t"))
        return trailing

    tail = text[open_at:]
    if "]" in tail or len(tail) > _CITATION_MAX:
        # Either it is already complete -- and `strip_citation_markers` will
        # deal with it -- or it is too long to be one. A trailing space after a
        # finished bracket is still a candidate for the next marker.
        return len(text) - len(text.rstrip(" \t"))

    # `[`, then letters, then optionally a hyphen and digits. Anything else is
    # ordinary prose that happens to contain a bracket.
    if not re.fullmatch(r"\[[A-Za-z]{0,8}(-\d{0,6})?", tail):
        return len(text) - len(text.rstrip(" \t"))

    # Extend left over the whitespace that `strip_citation_markers` will eat.
    start = open_at
    while start > 0 and text[start - 1] in " \t":
        start -= 1
    return len(text) - start


def _longest_partial_suffix(text: str, marker: str) -> int:
    """How many trailing characters of `text` could still grow into `marker`.

    The reason rule 1 works. `"...here is⟦wid"` returns 4, so those four
    characters are held back rather than shown; when the rest of the sentinel
    arrives they are consumed by it, and when ordinary text arrives instead they
    are released together with it.
    """
    limit = min(len(text), len(marker) - 1)
    for size in range(limit, 0, -1):
        if marker.startswith(text[-size:]):
            return size
    return 0


@dataclass
class StreamInterceptor:
    """Turns graph chunks into wire events, holding back anything unsafe to show.

    Stateful and single-use: one instance per streamed turn. Sharing one between
    turns would share the ordinal counter and the widget buffer, which is two
    different kinds of corruption.
    """

    #: Which agent is running. Set by the caller when `classify` resolves, and
    #: consulted before a widget is allowed out.
    active_agent: str | None = None
    #: Band and locale, needed by validation gates 3 and 6. Defaulted to the
    #: NARROWEST values rather than the widest: a stream constructed without
    #: them should fail a band gate, not silently pass one.
    age_band: str = "5-8"
    locale: str = "en"
    #: Whether widget sentinels are honoured at all. False forwards them as
    #: literal text, which is what a deployment with `WIDGETS_ENABLED=false`
    #: wants -- and is still safe, because the sentinels are inert characters.
    widgets_enabled: bool = True

    #: The closing summary `persist` published, or None if it never ran.
    turn: dict[str, Any] | None = None

    #: Every character of prose that actually crossed the wire, in order. This
    #: is what gets persisted as the turn's reply -- see `_token`.
    prose: str = ""

    #: A citation marker was stripped from the front of the reply, so the space
    #: it left behind is still owed a removal. See `_token`.
    _eat_leading_space: bool = False

    _ordinal: int = 0
    #: Which node produced the last prose. Two nodes speaking in one turn are
    #: two paragraphs, and this is how the boundary is noticed -- see
    #: `_on_message`.
    _last_node: str | None = None
    #: Prose held back because it might be the start of an opening sentinel.
    _pending: str = ""
    #: Widget JSON accumulated between the sentinels. None means "not inside a
    #: widget block", which is distinct from "inside one and empty so far".
    _widget: str | None = None
    #: Per-gate failure counts, surfaced by `stats()` for the metrics D7 wants.
    _gate_failures: dict[str, int] = field(default_factory=dict)
    _widgets_emitted: int = 0

    def _next(self) -> int:
        self._ordinal += 1
        return self._ordinal

    # ── the entry point ─────────────────────────────────────────────────────

    async def process(self, chunk: Any) -> list[WireEvent]:
        """One graph chunk in, zero or more wire events out.

        Accepts the two shapes `astream(stream_mode=["messages", "custom"])`
        produces: `("messages", (message_chunk, metadata))` and
        `("custom", payload)`. Anything else is ignored rather than raised on --
        langgraph adds stream modes, and a new one arriving must not break a
        turn in progress.
        """
        if not isinstance(chunk, tuple) or len(chunk) != 2:
            return []
        mode, payload = chunk

        if mode == "messages":
            return await self._on_message(payload)
        if mode == "custom":
            return self._on_custom(payload)
        return []

    # ── prose ───────────────────────────────────────────────────────────────

    async def _on_message(self, payload: Any) -> list[WireEvent]:
        try:
            message, metadata = payload
        except (TypeError, ValueError):
            return []

        # The filter that stops the router's JSON being read as an answer.
        node = (metadata or {}).get("langgraph_node") if isinstance(metadata, dict) else None
        if node in INTERNAL_NODES:
            return []

        text = _text_of(message)
        if not text:
            return []

        events = self._separate_from(node)
        self._last_node = node
        return events + self.feed(text)

    def _separate_from(self, node: str | None) -> list[WireEvent]:
        """A paragraph break when a DIFFERENT node starts speaking.

        A turn can have two speakers. `teach` explains and `check` asks the
        question, both in the same turn, and each returns its own message; the
        stream carries them as separate `messages` events with nothing between,
        so the reader gets

            ...choosing to move money from now to later.You move EC$25 into
            your account instead of spending it this week. What is that?

        -- one sentence running into the next with no space, which reads as a
        rendering bug and was one. The nodes are right to be separate messages:
        the check question is authored, the explanation is generated, and
        joining them upstream would put the authored text through the teaching
        model's output path.

        So the join is the transport's problem, which is what this is. Applied
        on the node BOUNDARY rather than per message, because a streamed node
        arrives as hundreds of chunks that all carry the same node name and must
        not be separated from each other.

        Three things suppress it: nothing said yet (no leading blank line), an
        open widget block (a break inside the JSON would corrupt it), and prose
        that already ends in a newline (the node did it itself).
        """
        if node is None or self._last_node is None or node == self._last_node:
            return []
        if self._widget is not None:
            return []
        if not self.prose.strip() or self.prose.endswith("\n"):
            return []

        self.prose += "\n\n"
        return [WireEvent("token", {"i": self._next(), "t": "\n\n"})]

    def feed(self, text: str) -> list[WireEvent]:
        """Push raw model text through the sentinel machine.

        Separate from `_on_message` so the tests can drive it with a string and
        an arbitrary chunking, which is the only way to prove rules 1 and 2 --
        the failure modes both live in *where the chunk boundary falls*, and a
        test that always feeds whole sentinels proves nothing.
        """
        if not self.widgets_enabled:
            return [self._token(text)]

        events: list[WireEvent] = []
        buffer = self._pending + text
        self._pending = ""

        while buffer:
            if self._widget is not None:
                # Inside a widget block: nothing is forwarded until it closes.
                #
                # The whole accumulated buffer is searched, not just the new
                # chunk. `CLOSE` is eleven characters and a chunk boundary falls
                # inside it often -- searching only the arrival would append
                # "⟦/wid" to the buffer, never match, and hold the stream until
                # the byte cap fired.
                self._widget += buffer
                buffer = ""

                close_at = self._widget.find(CLOSE)
                if close_at == -1:
                    if len(self._widget.encode("utf-8")) > _buffer_limit():
                        # Rule 4. Discard and resume; one widget is lost and the
                        # reply is not.
                        logger.warning(
                            "Discarding an unterminated widget block after %d "
                            "bytes; resuming prose.",
                            len(self._widget),
                        )
                        self._count("unterminated")
                        self._widget = None
                    break

                raw = self._widget[:close_at]
                buffer = self._widget[close_at + len(CLOSE) :]
                self._widget = None
                event = self._emit_widget(raw)
                if event is not None:
                    events.append(event)
                continue

            open_at = buffer.find(OPEN)
            if open_at != -1:
                prose = buffer[:open_at]
                if prose:
                    events.append(self._token(prose))
                self._widget = ""
                buffer = buffer[open_at + len(OPEN) :]
                continue

            # No complete opening sentinel. Hold back only the tail that could
            # still become one (rule 1) and release the rest.
            #
            # Two things can be mid-formation at a chunk boundary: a widget
            # sentinel, and a citation marker. Whichever starts EARLIER wins the
            # hold, because releasing the text in front of it is safe and
            # releasing the text inside it is not.
            held = max(
                _longest_partial_suffix(buffer, OPEN),
                _partial_citation_suffix(buffer),
            )
            if held:
                self._pending = buffer[-held:]
                buffer = buffer[:-held]
            if buffer:
                events.append(self._token(buffer))
            break

        return events

    def flush(self) -> list[WireEvent]:
        """Release anything still held, at the end of the turn.

        Two cases and they are handled differently. Held prose was only held
        because it *might* have become a sentinel; the turn is over, so it did
        not, and it is ordinary text that must be shown. An unterminated widget
        block is discarded -- it is JSON, and JSON was never for the reader.
        """
        events: list[WireEvent] = []
        if self._pending:
            events.append(self._token(self._pending))
            self._pending = ""
        if self._widget is not None:
            logger.warning("Turn ended inside a widget block; discarding it.")
            self._count("unterminated")
            self._widget = None
        return events

    def token(self, text: str) -> WireEvent:
        """Emit prose that did not come from the model.

        Used by the cache replay, which has a whole answer and no stream to
        take it apart. It goes through the same counter and the same accumulator
        as a live token, so a replayed turn is indistinguishable on the wire and
        is persisted by exactly the same code.
        """
        return self._token(text)

    def _token(self, text: str) -> WireEvent:
        stripped = strip_citation_markers(text)

        # A marker opened the reply. `strip_citation_markers` eats the space
        # BEFORE a marker -- correct mid-sentence -- so removing one at position
        # 0 leaves the space that FOLLOWED it stranded at the front.
        #
        # Conditioned on a marker actually having been removed, not merely on
        # this being the first token: prose that legitimately begins with a
        # space (the resumption after a discarded widget block, which
        # `test_the_buffer_cap_releases_the_stream` pins) is none of this rule's
        # business.
        #
        # The flag has to OUTLIVE this call. At one character per chunk the
        # marker arrives as its own token and strips to nothing, so the space
        # after it is in the NEXT call -- by which time `text` contains no
        # marker to notice.
        if stripped != text and not self.prose:
            self._eat_leading_space = True
        if self._eat_leading_space:
            stripped = stripped.lstrip()
            if stripped:
                self._eat_leading_space = False

        text = stripped
        # Accumulated as it goes out, so the turn's reply is what the READER
        # received rather than what the model produced. The two differ whenever
        # a widget block is stripped, and persisting the second would write the
        # widget's JSON into the conversation history.
        self.prose += text
        return WireEvent("token", {"i": self._next(), "t": text})

    # ── widgets ─────────────────────────────────────────────────────────────

    def _emit_widget(self, raw: str) -> WireEvent | None:
        """Validate a buffered widget block and turn it into a directive.

        Returns None on any failure, having logged the gate that failed. Rule 3:
        the reader is never told, because they were never told a widget was
        coming.
        """
        if self.active_agent not in WIDGET_AGENTS:
            logger.warning(
                "Dropping a widget emitted while %r was active; widgets are for "
                "%s only.",
                self.active_agent,
                ", ".join(sorted(WIDGET_AGENTS)),
            )
            self._count("wrong_agent")
            return None

        from app.widgets.validate import validate_widget

        result = validate_widget(raw, age_band=self.age_band, locale=self.locale)
        if not result.ok:
            logger.info(
                "Widget dropped at gate %s: %s", result.gate, result.reason
            )
            self._count(result.gate or "unknown")
            return None

        self._widgets_emitted += 1
        directive = WidgetDirective(payload=result.widget)
        return WireEvent(
            "directive", {"i": self._next(), "d": directive_payload(directive)}
        )

    # ── directives from the graph itself ────────────────────────────────────

    def _on_custom(self, payload: Any) -> list[WireEvent]:
        """A directive a node emitted via `get_stream_writer()`.

        The graph's own channel, distinct from the sentinel channel: quick
        replies, citations, games, uploads and progress all come this way,
        already typed, and need no parsing at all.
        """
        if not isinstance(payload, dict):
            return []

        # `meta` carries no content and produces no event. It is how `classify`
        # tells the interceptor which agent is running, which the widget gate
        # needs and which is otherwise only visible in the `updates` stream mode
        # -- a third mode this transport deliberately does not subscribe to.
        meta = payload.get("meta")
        if isinstance(meta, dict):
            if "active_agent" in meta:
                self.active_agent = meta["active_agent"]
            if "age_band" in meta:
                self.age_band = meta["age_band"]
            if "locale" in meta:
                self.locale = meta["locale"]
            return []

        # `turn` is the closing summary `persist` writes: the chips, the
        # citations, the directives a node put in state, and whether to speak.
        # It travels on this channel rather than being read back from the
        # checkpoint so that a deployment WITHOUT a database still gets its
        # directives -- and a turn whose chips silently vanish when Postgres is
        # unset is the kind of difference that only shows up in production.
        turn = payload.get("turn")
        if isinstance(turn, dict):
            self.turn = turn
            return []

        # `prose` is a finished, validated lesson from the tutor node.
        #
        # It travels on this channel rather than on `messages` because the tutor
        # is on `INTERNAL_NODES`: its raw model tokens are suppressed so that a
        # lesson which fails the band contract can be regenerated before anybody
        # reads it. What arrives here has already passed.
        #
        # Pushed through `feed` rather than emitted directly so that it goes
        # through exactly the same machinery a streamed token does -- citation
        # markers stripped, `self.prose` accumulated -- which is what keeps a
        # tutor turn and a Q&A turn persisting identically.
        prose = payload.get("prose")
        if isinstance(prose, str) and prose:
            events = self._separate_from("tutor")
            self._last_node = "tutor"
            return events + self.feed(prose)

        directive = payload.get("directive")
        if directive is None:
            return []
        return [WireEvent("directive", {"i": self._next(), "d": directive})]

    def directive(self, payload: dict[str, Any]) -> WireEvent:
        """Emit an already-serialised directive at the next ordinal."""
        return WireEvent("directive", {"i": self._next(), "d": payload})

    def done(self, usage: dict[str, Any] | None = None) -> WireEvent:
        return WireEvent("done", {"i": self._next(), "usage": usage or {}})

    def error(self, code: str, message: str) -> WireEvent:
        """An error event. Note it does NOT consume an ordinal.

        The ordinal sequence describes the answer's content, and an error is not
        content -- it is the reason there is no more of it. A client that
        positions by ordinal must not have to reason about a gap.
        """
        return WireEvent("error", {"code": code, "message": message})

    # ── instrumentation ─────────────────────────────────────────────────────

    def _count(self, gate: str) -> None:
        self._gate_failures[gate] = self._gate_failures.get(gate, 0) + 1

    def stats(self) -> dict[str, Any]:
        """Per-turn counters, for the metrics D7 surfaces."""
        return {
            "events": self._ordinal,
            "widgets_emitted": self._widgets_emitted,
            "gate_failures": dict(self._gate_failures),
        }


def _buffer_limit() -> int:
    return get_settings().widget_buffer_limit_bytes


def _text_of(message: Any) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""
