"""Everything a turn does besides producing the answer.

The graph answers the question. This module does the bookkeeping around it: who
the conversation belongs to, recording the question before it is answered,
recording the answer after, and the response cache.

## Why this is not in the graph

Every function here writes to Postgres or Valkey. A node that does I/O against
the application's own database is a node whose unit test needs a database, and
`AspireState` would have to carry a connection, an owner id and a cache key --
none of which any agent reads. The graph's state is what the *conversation*
needs; this is what the *service* needs, and the two have different lifetimes.

The practical consequence is that the graph can be invoked with no database at
all -- which is exactly how `evals/harness.py` runs it, and how every subgraph
test runs it.

## What survived the removal of `/chat`, and what did not

Kept, because a real reader depends on it:

  * `open_conversation` -- the question is recorded BEFORE it is answered, so a
    turn whose answer fails still leaves a conversation that can be reopened.
  * `persist_turn` -- history, the rail, the title.
  * the response cache, on both layers.

Dropped, because the graph replaced it:

  * `suggest_follow_ups`. It was a second model call per turn to produce two
    chips. The graph's agents emit `quick_replies` from what they actually did
    -- the lesson's next step, the registration slot, the concepts a Q&A answer
    touched -- and those are better chips for no extra call. `stream.ts` maps
    them onto the same UI.
  * `TurnBuffer`. It existed to discard prose the model wrote alongside a card.
    Cards are now decided before the model runs (`graph/nodes/cards.py`), so
    there is no prose to discard.
"""

from __future__ import annotations

import logging
import uuid as uuid_module
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings
from app.db import database_enabled, session
from app.db.repository import append_turn, ensure_conversation

logger = logging.getLogger(__name__)

#: Matches the client's own truncation, because the two produce the same list.
TITLE_MAX = 60


@dataclass(slots=True)
class TurnRecord:
    """What a finished turn leaves behind. Assembled by the transport.

    A dataclass rather than the old sprawl of keyword arguments because there
    are now six callers' worth of fields and two of them (`card`, `directives`)
    did not exist when `_persist_turn` took them one at a time.
    """

    thread_id: str
    question: str
    reply: str
    language: str = "en"
    persona: str | None = None
    account_status: str | None = None
    #: Part of the response-cache key. One persona spans three bands and each
    #: has a different word cap, so persona alone would let a 16-18 answer be
    #: served to a nine-year-old -- see `cache.cache_key`.
    age_band: str | None = None
    owner_id: uuid_module.UUID | None = None
    #: `"game"`, `"eligibility"`, or None. Decides the history line.
    card: str | None = None
    #: The turn's directives, already JSON. Only the card ones are read here.
    directives: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    quick_replies: list[str] = field(default_factory=list)
    agent: str | None = None


def provisional_title(question: str) -> str:
    """The first question, tidied and truncated.

    The middle rung of the fallback ladder: better than "New chat", worse than a
    generated title, and replaced by one as soon as `/api/title` answers.
    """
    clean = " ".join(question.split())
    if not clean:
        return ""
    if len(clean) > TITLE_MAX:
        return clean[: TITLE_MAX - 1] + "…"
    return clean


# ── the history lines a card leaves ──────────────────────────────────────────


def game_history_line(directive: dict[str, Any]) -> str:
    """What a game turn leaves in the transcript in place of prose.

    An empty assistant turn would be worse than useless: the model reads its own
    history back, and would find a question followed by silence, then wonder why
    nobody replied. This is a factual note that the card was shown -- it carries
    no puzzle text and no answer, so re-reading history cannot leak either.

    English regardless of the conversation's language, on purpose. It is context
    for the model, not copy for the reader; nothing renders it.
    """
    name = str(directive.get("game") or "a game").replace("_", " ")
    return (
        f"[Started the {name} game. The interactive card is on screen and it "
        "grades its own answers. I cannot see the items or the answers.]"
    )


def eligibility_history_line() -> str:
    """What an eligibility turn leaves in the transcript in place of prose.

    Same job as `game_history_line`. What it deliberately does NOT carry is the
    flow's outcome or any answer: the verdict is not here, the age band is not
    here, and nothing about citizenship, island or school is here. That is not
    caution for its own sake -- this string is written to Postgres inside a
    transcript that identifies a conversation, and the anonymised outcome row
    exists precisely so that the two never sit together.

    What it does carry is enough to stop the model re-asking.
    """
    return (
        "[Opened the ASPIRE eligibility check. The interactive card is on screen "
        "and it asks its own questions, shows the result, the document checklist "
        "and the application steps. I cannot see the answers or the outcome. Do "
        "not re-ask their age, citizenship, parish or school -- the card covered "
        "them -- and do not restate any eligibility rule.]"
    )


def history_content(record: TurnRecord) -> str:
    """The assistant's transcript line: the reply, or a note that a card opened."""
    if record.card == "eligibility":
        return eligibility_history_line()
    if record.card == "game":
        game = next(
            (d for d in record.directives if d.get("t") == "game"),
            {},
        )
        return game_history_line(game)
    return record.reply


# ── identity ─────────────────────────────────────────────────────────────────


async def resolve_owner(user_id: str | None) -> uuid_module.UUID | None:
    """The conversation's owner, as a UUID, or None for an anonymous turn.

    Anonymous callers are welcome and always have been: asking a question has
    never required identifying yourself. None simply means the conversation is
    stored unowned and will not appear in anybody's list.
    """
    if not user_id:
        return None
    try:
        return uuid_module.UUID(str(user_id))
    except (TypeError, ValueError):
        logger.warning("A session token carried an unusable user id; storing unowned.")
        return None


async def owns_thread(thread_id: str, owner_id: uuid_module.UUID | None) -> bool:
    """Whether this caller may continue this conversation.

    Fail-closed only where there is something to be closed against: a thread
    with no row yet is new and belongs to whoever is starting it, and a thread
    stored unowned was started anonymously and stays open. A thread with a
    DIFFERENT owner is refused.

    This did not exist on `/chat`, which read history by thread id alone and
    relied on the id being an unguessable UUID. That is a real property and not
    nothing, but it is one leaked URL away from being no property at all -- and
    a graph session token carries a persona and an age band, so continuing
    somebody else's thread would carry them into it.
    """
    if not database_enabled():
        return True

    from sqlalchemy import text as sql

    try:
        async with session() as db:
            if db is None:
                return True
            row = (
                await db.execute(
                    sql("SELECT owner_id FROM conversations WHERE id = :id"),
                    {"id": thread_id},
                )
            ).first()
    except Exception:
        # A database that cannot be read must not lock everybody out of their
        # own conversations. Logged loudly; the turn proceeds.
        logger.warning("Could not check ownership of %s.", thread_id, exc_info=True)
        return True

    if row is None or row[0] is None:
        return True
    return str(row[0]) == str(owner_id) if owner_id is not None else False


# ── persistence ──────────────────────────────────────────────────────────────


async def open_conversation(record: TurnRecord) -> None:
    """Create the conversation and record the question, before answering it.

    Deliberately ahead of the graph rather than after it. A first message whose
    answer fails must still leave a conversation behind: the client commits the
    chat the instant it is sent -- it is in the address bar and in the rail --
    and a chat that exists on screen with nothing behind it is a dead end with
    no route out. Recording the question here is what lets that conversation be
    reopened and the question asked again.

    Swallows its own failures for the same reason `persist_turn` does: the user
    is owed an answer, and losing the record of the question is our problem.
    """
    if not database_enabled() or not record.question.strip():
        return

    try:
        async with session() as db:
            if db is None:
                return
            await ensure_conversation(
                db,
                record.thread_id,
                language=record.language,
                persona=record.persona,
                account_status=record.account_status,
                # Recorded on creation only, so the first turn settles whose
                # conversation this is and no later request can take it over.
                owner_id=record.owner_id,
                title=provisional_title(record.question),
            )
            await append_turn(
                db, record.thread_id, role="user", content=record.question
            )
    except Exception:
        logger.warning(
            "Could not open conversation %s; the turn was still served.",
            record.thread_id,
            exc_info=True,
        )


async def persist_turn(record: TurnRecord) -> None:
    """Write the exchange to Postgres, whole.

    Called after the answer has already gone out, so nothing here may take it
    away. Swallows its own failures on purpose: the user has an answer, and
    losing the record of it is a problem for us, not a reason to replace a
    correct answer on screen with an error.
    """
    if not database_enabled():
        return

    content = history_content(record)
    if not content.strip():
        # Nothing was said and no card opened -- an interrupted turn waiting on
        # an upload, for instance. There is no assistant message to append, and
        # appending an empty one would put a silent turn in the model's history.
        return

    try:
        async with session() as db:
            if db is None:
                return
            # `open_conversation` already created the row and recorded the
            # question before the graph ran. This is an upsert and a no-op when
            # that succeeded; it stays because that call swallows its own
            # failures, and a turn whose opening write failed should still be
            # persisted rather than silently losing its question.
            await ensure_conversation(
                db,
                record.thread_id,
                language=record.language,
                persona=record.persona,
                account_status=record.account_status,
                owner_id=record.owner_id,
                title=provisional_title(record.question),
            )
            await append_turn(
                db,
                record.thread_id,
                role="assistant",
                content=content,
                extra={
                    "sources": record.citations,
                    "follow_ups": record.quick_replies,
                    "agent": record.agent,
                    **({"event": f"{record.card}_started"} if record.card else {}),
                },
            )
    except Exception:
        logger.warning(
            "Could not persist the turn for thread %s; the answer was still served.",
            record.thread_id,
            exc_info=True,
        )


# ── the response cache ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CachedTurn:
    reply: str
    citations: list[dict[str, Any]]
    quick_replies: list[str]


#: Agents whose turns belong to one learner and may never be replayed to another.
#:
#: See `cacheable`. Named here rather than inline because the same three names
#: appear in four places now (`safety_out.LEARNING_AGENTS`,
#: `stream_interceptor.WIDGET_AGENTS`, the registration loop in
#: `agents/learn/graph.py`, and this) and the set is one fact.
LESSON_AGENTS: frozenset[str] = frozenset(
    {"learn_agent", "learning_preview", "learning_sample"}
)


def cacheable(record: TurnRecord) -> bool:
    """Whether this turn may be served to somebody else later.

    Four exclusions and each closes a specific hole:

      * **a card turn** -- the reply is empty and the card is a live server-side
        session belonging to one conversation. Replaying it would show a second
        reader a card with nothing behind it.
      * **a lesson turn** -- see below.
      * **a turn with directives beyond citations and chips** -- a widget is
        generated for a specific band and a specific concept, and the widget
        promotion cache (`app/widgets/cache.py`) is where a reusable one goes.
      * **an empty reply** -- there is nothing to serve.

    ## Why a lesson turn is not a cacheable answer

    The cache key is `(question, language, persona, account_status, age_band)`.
    It does not include the learner, and it cannot: the whole point of layer 1
    is that one answer serves an audience. That is right for "when is the
    deadline?" and wrong for every turn of a lesson, for two reasons.

    The visible one is repetition. "teach me about saving" from any nine-year-old
    on `stella` fills the same key, so for the next six hours every child asking
    it -- and the same child asking again tomorrow -- reads a byte-identical
    lesson. Every defence against that (`recent_openings`, a fresh generation
    per turn, the widget planner's variety rule) lives inside the graph, and a
    cache hit does not run the graph.

    The worse one is that a lesson turn is not an answer at all, it is a state
    transition. `resume_or_place` picks a lesson, `teach` advances `phase` to
    `checking`, `mastery_update` writes a row. A replay serves the prose and
    performs none of it, so the reader gets a lesson and the machine does not
    move: the check question that should follow never comes, and their mastery
    never records that they were taught. Measured against a live session before
    this exclusion existed -- the same opening lesson came back three
    conversations running and the check question never arrived.
    """
    if record.card or not record.reply.strip():
        return False
    if record.agent in LESSON_AGENTS:
        return False
    return all(
        directive.get("t") in ("citations", "quick_replies")
        for directive in record.directives
    )


async def cached_answer(
    question: str,
    *,
    language: str,
    persona: str | None,
    account_status: str | None,
    age_band: str | None = None,
) -> CachedTurn | None:
    """Layer 1: this exact question, from this exact audience, asked before.

    The audience is part of the key and always has been. An answer written for
    an adult prospect is not an answer for a nine-year-old account holder, and a
    cache that ignored the band would be a cache that eventually serves one to
    the other.
    """
    from app import cache as response_cache

    if not response_cache.cache_enabled():
        return None
    try:
        hit = await response_cache.get_answer(
            question,
            language=language,
            persona=persona,
            account_status=account_status,
            age_band=age_band,
        )
    except Exception:
        logger.warning("The response cache could not be read.", exc_info=True)
        return None
    if not hit:
        return None
    return CachedTurn(
        reply=str(hit.get("reply") or ""),
        citations=list(hit.get("sources") or []),
        quick_replies=list(hit.get("follow_ups") or []),
    )


async def cache_answer(record: TurnRecord) -> None:
    """Store a plain-prose turn for the next person who asks the same thing."""
    if not cacheable(record):
        return

    from app import cache as response_cache

    if not response_cache.cache_enabled():
        return
    try:
        await response_cache.put_answer(
            record.question,
            {
                "reply": record.reply,
                "sources": record.citations,
                "follow_ups": record.quick_replies,
            },
            language=record.language,
            persona=record.persona,
            account_status=record.account_status,
            age_band=record.age_band,
        )
    except Exception:
        logger.warning("The response cache could not be written.", exc_info=True)


# ── the rolling summary ──────────────────────────────────────────────────────

#: Messages kept verbatim in the checkpoint before older ones are compressed.
#: Matches `main_graph.SUMMARY_AFTER_MESSAGES`, and is read from there rather
#: than redeclared -- two thresholds for one behaviour is how a conversation
#: comes to be summarised twice or never.


def summarisation_wanted() -> bool:
    """Whether this deployment folds older turns into a summary at all.

    `memory_window_enabled` AND a database. The flag alone must not switch it
    on: with no Postgres there is nowhere for a checkpoint to live, so there is
    no thread to summarise and the work would be a model call against nothing.
    """
    settings = get_settings()
    return settings.memory_window_enabled and database_enabled()


async def summarise_thread(graph: Any, config: dict[str, Any]) -> bool:
    """Compress a long thread's older turns, AFTER the answer has gone out.

    Returns whether it wrote anything.

    ## Why it is here and not in the `persist` node

    `persist` is inside `graph.astream`, so a model call there sits between the
    last token and `done` -- and the client cannot settle a turn until `done`
    arrives. The reader would watch a finished answer with no sources, no chips
    and no action row for as long as compression took.

    Out here it costs the reader nothing: the stream has already closed.

    ## Why not the arq worker, which used to do this

    Because the summary now lives in the CHECKPOINT rather than in a Postgres
    column. `conversations.summary` was read by `load_context`, which fed
    `build_prompt`, which fed the v1 agent -- and all three are gone. The graph
    reads `state["summary"]`, so that is what has to be written, and
    `aupdate_state` is the only thing that can write it.

    Redaction happens before the model sees anything, not after. A date of birth
    that reaches a summary is a date of birth in every future prompt on this
    thread, forever; summarising first and redacting the result would mean the
    value had already been sent.
    """
    if not summarisation_wanted():
        return False

    from app.graph.main_graph import SUMMARY_AFTER_MESSAGES

    # A graph compiled without a checkpointer has no state to read back, and
    # that is a supported configuration rather than a fault -- the eval harness
    # and every subgraph test run that way. Checked rather than caught, because
    # `aget_state` raises a bare `ValueError` for it and catching that would
    # swallow real failures alongside it.
    if getattr(graph, "checkpointer", None) is None:
        return False

    try:
        snapshot = await graph.aget_state(config)
    except Exception:
        logger.warning("Could not read state back to summarise.", exc_info=True)
        return False

    values = getattr(snapshot, "values", None) or {}
    messages = values.get("messages") or []
    if len(messages) <= SUMMARY_AFTER_MESSAGES:
        return False

    from app.safety import pii

    older = messages[:-SUMMARY_AFTER_MESSAGES]
    redacted = [
        pii.redact_for_summary(_text_of(message))
        for message in older
        if _text_of(message).strip()
    ]
    if not redacted:
        return False

    from app.agent import summarise_conversation

    turns = [("earlier", line) for line in redacted]
    try:
        summary = await summarise_conversation(turns, values.get("summary") or None)
    except Exception:
        logger.warning("Summarising the thread failed.", exc_info=True)
        return False
    if not summary:
        return False

    try:
        await graph.aupdate_state(config, {"summary": summary})
    except Exception:
        logger.warning("Could not write the summary back.", exc_info=True)
        return False
    return True


def _text_of(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""
