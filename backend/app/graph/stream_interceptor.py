"""Everything the graph emits, turned into wire events with stable ordinals."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings
from app.schemas.directives import CITATION_ID, WidgetDirective, directive_payload
from app.widgets.sentinel import CLOSE, OPEN
from app.messages import text_of

logger = logging.getLogger(__name__)

# `OPEN` / `CLOSE` (U+27E6 / U+27E7) are re-exported from `widgets.sentinel`, their one definition.
__all__ = ["OPEN", "CLOSE", "WIDGET_AGENTS", "INTERNAL_NODES", "StreamInterceptor"]

#: The agents that may emit widgets.
WIDGET_AGENTS: frozenset[str] = frozenset(
    {"learn_agent", "learning_preview", "learning_sample"}
)

#: Nodes whose model calls are INTERNAL and must never reach the reader.
INTERNAL_NODES: frozenset[str] = frozenset(
    {
        "classify",        # routing JSON
        "rewrite_query",   # the search query, not an answer
        "safety_out",      # the re-prompt's rewrite, streamed twice otherwise
        "plan_widget",     # which primitive, as JSON
        "doc_check",       # a vision verdict, as JSON
        "persist",         # the rolling summary
        "summarise",       # the escalation summary
        # The tutor is here for a different reason: its lesson is republished once validated.
        "tutor",
    }
)


@dataclass(frozen=True, slots=True)
class WireEvent:
    """One SSE event, before it is serialised."""

    event: str
    data: dict[str, Any]

    def encode(self) -> str:
        """The event in SSE wire format."""
        body = json.dumps(self.data, ensure_ascii=False, separators=(",", ":"))
        return f"event: {self.event}\ndata: {body}\n\n"


#: A citation marker as `generate` is instructed to write it: `[ASP-001]`.
#:
#: `CITATION_ID` is shared with grounding, so a marker this strips is exactly
#: one grounding counted. When the two disagreed, `[ASP-00A]` was both declined
#: as uncited AND left in the prose for the reader to see.
_CITATION = re.compile(rf"[ \t]*\[{CITATION_ID}\]")

#: The longest a partial marker can be before it cannot be one.
_CITATION_MAX = 16


def strip_citation_markers(text: str) -> str:
    """Remove `[KB-001]` markers, with the space that precedes them."""
    return _CITATION.sub("", text)


def _partial_citation_suffix(text: str) -> int:
    """How many trailing characters might still become a citation marker."""
    open_at = text.rfind("[")
    if open_at == -1:
        # No bracket, but a trailing space may be the one preceding a marker in the next chunk.
        trailing = len(text) - len(text.rstrip(" \t"))
        return trailing

    tail = text[open_at:]
    if "]" in tail or len(tail) > _CITATION_MAX:
        # Either complete, which `strip_citation_markers` handles, or too long to be a marker.
        return len(text) - len(text.rstrip(" \t"))

    # `[`, then letters, then optionally a hyphen and digits.
    if not re.fullmatch(r"\[[A-Za-z]{0,8}(-\d{0,6})?", tail):
        return len(text) - len(text.rstrip(" \t"))

    # Extend left over the whitespace that `strip_citation_markers` will eat.
    start = open_at
    while start > 0 and text[start - 1] in " \t":
        start -= 1
    return len(text) - start


def _longest_partial_suffix(text: str, marker: str) -> int:
    """How many trailing characters of `text` could still grow into `marker`."""
    limit = min(len(text), len(marker) - 1)
    for size in range(limit, 0, -1):
        if marker.startswith(text[-size:]):
            return size
    return 0


@dataclass
class StreamInterceptor:
    """Turns graph chunks into wire events, holding back anything unsafe to show."""

    #: Which agent is running.
    active_agent: str | None = None
    #: Band and locale, needed by validation gates 3 and 6.
    age_band: str = "5-8"
    locale: str = "en"
    #: Whether this turn is about ASPIRE itself.
    #:
    #: Set from the reader's own question at the top of the turn, the same way
    #: `safety_out` decides it, so a widget beside a programme answer is held to
    #: the same ladder the prose is. Without it a label reading "EC$500
    #: invested" was refused at 5-8 on a turn whose sentence had just said it.
    programme_scope: bool = False
    #: Whether widget sentinels are honoured at all.
    widgets_enabled: bool = True

    #: The closing summary `persist` published, or None if it never ran.
    turn: dict[str, Any] | None = None

    #: Every character of prose that actually crossed the wire, in order.
    prose: str = ""

    #: A marker was stripped from the reply's front, so the space it left is still owed removal.
    _eat_leading_space: bool = False

    _ordinal: int = 0
    #: Which node produced the last prose.
    _last_node: str | None = None
    #: Prose held back because it might be the start of an opening sentinel.
    _pending: str = ""
    #: Widget JSON accumulated between the sentinels.
    _widget: str | None = None
    #: Per-gate failure counts, surfaced by `stats()` for metrics.
    _gate_failures: dict[str, int] = field(default_factory=dict)
    _widgets_emitted: int = 0

    def _next(self) -> int:
        self._ordinal += 1
        return self._ordinal

    # ── the entry point ─────────────────────────────────────────────────────

    async def process(self, chunk: Any) -> list[WireEvent]:
        """One `astream` chunk in, zero or more wire events out; `subgraphs=True` 3-tuples work too."""
        if not isinstance(chunk, tuple):
            return []
        if len(chunk) == 3:
            _namespace, mode, payload = chunk
        elif len(chunk) == 2:
            mode, payload = chunk
        else:
            return []

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

        text = text_of(message)
        if not text:
            return []

        events = self._separate_from(node)
        self._last_node = node
        return events + self.feed(text)

    def _separate_from(self, node: str | None) -> list[WireEvent]:
        """A paragraph break when a DIFFERENT node starts speaking."""
        if node is None or self._last_node is None or node == self._last_node:
            return []
        if self._widget is not None:
            return []
        if not self.prose.strip() or self.prose.endswith("\n"):
            return []

        self.prose += "\n\n"
        return [WireEvent("token", {"i": self._next(), "t": "\n\n"})]

    def feed(self, text: str) -> list[WireEvent]:
        """Push raw model text through the sentinel machine."""
        if not self.widgets_enabled:
            return [self._token(text)]

        events: list[WireEvent] = []
        buffer = self._pending + text
        self._pending = ""

        while buffer:
            if self._widget is not None:
                # Inside a widget block: nothing is forwarded until it closes.
                self._widget += buffer
                buffer = ""

                close_at = self._widget.find(CLOSE)
                if close_at == -1:
                    if len(self._widget.encode("utf-8")) > _buffer_limit():
                        # Rule 4.
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

            # No complete opening sentinel.
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
        """Release anything still held, at the end of the turn."""
        events: list[WireEvent] = []
        if self._pending:
            events.append(self._token(self._pending))
            self._pending = ""
        if self._widget is not None:
            logger.warning("Turn ended inside a widget block; discarding it.")
            self._count("unterminated")
            self._widget = None
        return events

    def restart_numbering(self) -> None:
        """Forget the prose held so far, and the ordinals it consumed.

        The transport holds every prose event until the outbound gates have had
        the text, then sends the corrected version. The held events still ran
        through `_token`, so they took ordinals with them and left a gap at the
        front of what the reader actually receives. `OrdinalBuffer` on the
        client tolerates a gap -- `text()` skips absent ordinals rather than
        waiting for them -- but a numbering that starts at 2 is a puzzle for
        whoever reads a frame dump next, and `placed()` measures directive
        offsets against exactly this sequence.
        """
        self.prose = ""
        self._ordinal = 0
        self._eat_leading_space = False

    def token(self, text: str) -> WireEvent:
        """Emit prose that did not come from the model."""
        return self._token(text)

    def _token(self, text: str) -> WireEvent:
        stripped = strip_citation_markers(text)

        # A marker opened the reply.
        if stripped != text and not self.prose:
            self._eat_leading_space = True
        if self._eat_leading_space:
            stripped = stripped.lstrip()
            if stripped:
                self._eat_leading_space = False

        text = stripped
        # Accumulated as it goes out: what the reader received, not what the model produced.
        self.prose += text
        return WireEvent("token", {"i": self._next(), "t": text})

    # ── widgets ─────────────────────────────────────────────────────────────

    def _emit_widget(self, raw: str) -> WireEvent | None:
        """Validate a buffered widget block and turn it into a directive."""
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

        result = validate_widget(
            raw,
            age_band=self.age_band,
            locale=self.locale,
            programme_scope=self.programme_scope,
        )
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
        """A directive a node emitted via `get_stream_writer()`."""
        if not isinstance(payload, dict):
            return []

        # `meta` carries no content and produces no event.
        meta = payload.get("meta")
        if isinstance(meta, dict):
            if "active_agent" in meta:
                self.active_agent = meta["active_agent"]
            if "age_band" in meta:
                self.age_band = meta["age_band"]
            if "locale" in meta:
                self.locale = meta["locale"]
            return []

        # `turn` is the closing summary `persist` writes: chips, citations, and state directives.
        turn = payload.get("turn")
        if isinstance(turn, dict):
            self.turn = turn
            return []

        # `prose` is a finished, validated lesson from the tutor node.
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
        """An error event."""
        return WireEvent("error", {"code": code, "message": message})

    # ── instrumentation ─────────────────────────────────────────────────────

    def _count(self, gate: str) -> None:
        self._gate_failures[gate] = self._gate_failures.get(gate, 0) + 1

    def stats(self) -> dict[str, Any]:
        """Per-turn counters, for metrics."""
        return {
            "events": self._ordinal,
            "widgets_emitted": self._widgets_emitted,
            "gate_failures": dict(self._gate_failures),
        }


def _buffer_limit() -> int:
    return get_settings().widget_buffer_limit_bytes

