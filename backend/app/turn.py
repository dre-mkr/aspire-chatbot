"""Everything a turn does besides producing the answer."""

from __future__ import annotations

import logging
import uuid as uuid_module
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings
from app.db import database_enabled, session
from app.db.repository import append_turn, ensure_conversation
from app.messages import text_of

logger = logging.getLogger(__name__)

#: Matches the client's own truncation, because the two produce the same list.
TITLE_MAX = 60


@dataclass(slots=True)
class TurnRecord:
    """What a finished turn leaves behind."""

    thread_id: str
    question: str
    reply: str
    language: str = "en"
    persona: str | None = None
    account_status: str | None = None
    #: Part of the response-cache key.
    age_band: str | None = None
    #: Also part of the cache key: a simplified answer is different text.
    simple_mode: bool = False
    owner_id: uuid_module.UUID | None = None
    #: `"game"`, `"eligibility"`, or None. Decides the history line.
    card: str | None = None
    #: The turn's directives, already JSON. Only the card ones are read here.
    directives: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    quick_replies: list[str] = field(default_factory=list)
    agent: str | None = None
    #: Whether this turn told a story, which is personal and never replayed.
    story: bool = False
    #: Whether the conversation row is already somebody else's guarantee.
    opened: bool = False


def provisional_title(question: str) -> str:
    """The first question, tidied and truncated."""
    clean = " ".join(question.split())
    if not clean:
        return ""
    if len(clean) > TITLE_MAX:
        return clean[: TITLE_MAX - 1] + "…"
    return clean


# ── the history lines a card leaves ──────────────────────────────────────────


def game_history_line(directive: dict[str, Any]) -> str:
    """What a game turn leaves in the transcript in place of prose."""
    name = str(directive.get("game") or "a game").replace("_", " ")
    return (
        f"[Started the {name} game. The interactive card is on screen and it "
        "grades its own answers. I cannot see the items or the answers.]"
    )


def eligibility_history_line() -> str:
    """What an eligibility turn leaves in the transcript in place of prose."""
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
    """The conversation's owner, as a UUID, or None for an anonymous turn."""
    if not user_id:
        return None
    try:
        return uuid_module.UUID(str(user_id))
    except (TypeError, ValueError):
        logger.warning("A session token carried an unusable user id; storing unowned.")
        return None


async def owns_thread(thread_id: str, owner_id: uuid_module.UUID | None) -> bool:
    """Whether this caller may continue this conversation."""
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
        # A database that cannot be read must not lock everybody out of their own conversations.
        logger.warning("Could not check ownership of %s.", thread_id, exc_info=True)
        return True

    if row is None or row[0] is None:
        return True
    return str(row[0]) == str(owner_id) if owner_id is not None else False


# ── persistence ──────────────────────────────────────────────────────────────


async def open_conversation(record: TurnRecord) -> None:
    """Create the conversation and record the question, before answering it."""
    if not database_enabled():
        return
    if not record.question.strip():
        # An interaction turn -- a widget moved, an upload resumed -- continues a conversation.
        record.opened = True
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
                # Recorded on creation only: the first turn settles ownership for good.
                owner_id=record.owner_id,
                title=provisional_title(record.question),
            )
            await append_turn(
                db, record.thread_id, role="user", content=record.question
            )
        # Only past both writes.
        record.opened = True
    except Exception:
        logger.warning(
            "Could not open conversation %s; the turn was still served.",
            record.thread_id,
            exc_info=True,
        )


async def persist_turn(record: TurnRecord) -> None:
    """Write the exchange to Postgres, whole."""
    if not database_enabled():
        return

    content = history_content(record)
    if not content.strip():
        # Nothing said and no card opened -- an interrupted turn waiting on an upload, say.
        return

    try:
        async with session() as db:
            if db is None:
                return
            # `open_conversation` already made the row and recorded the question.
            if not record.opened:
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
LESSON_AGENTS: frozenset[str] = frozenset(
    {"learn_agent", "learning_preview", "learning_sample"}
)

#: Agents whose reply is a POSITION IN A FLOW, not an answer to a question.
#:
#: A registration turn only means anything in sequence. "And how are you related
#: to the child?" is step two of a form; served to somebody who asked something
#: else, it is not a partial answer but a non-sequitur that also looks like the
#: assistant has started collecting their details.
#:
#: This is not hypothetical. On 23 August 2026 the classifier routed the bare
#: question "What is your name?" to `register_agent_step1`, the reply was cached
#: against that question, and it was then served from cache to FIVE of the seven
#: persona/band pairs -- Skye at 5-8 among them. A five-year-old asking the
#: guide's name was shown "And how are you related to the child?" over chips
#: reading Mother, Father, Grandmother, Grandfather. Reproduced 3/3 on fresh
#: sessions against production.
#:
#: One misroute is a bug. A CACHED misroute is that bug made permanent for
#: everybody who ever asks the same thing, and it survives fixing the router.
#: Lessons and stories are already excluded for the weaker version of this
#: reason -- they were written for the reader who asked. A form step was not
#: written for a reader at all.
REGISTRATION_AGENTS: frozenset[str] = frozenset(
    {"register_agent", "register_agent_step1"}
)


def cacheable(record: TurnRecord) -> bool:
    """Whether this turn may be served to somebody else later."""
    if record.card or not record.reply.strip():
        return False
    if record.agent in LESSON_AGENTS:
        return False
    if record.agent in REGISTRATION_AGENTS:
        return False
    # A story was written for the reader who asked for it, about the topic they
    # chose. Replaying it to the next person who happens to type the same topic
    # is the same mistake as replaying a lesson, and it would also serve a
    # story to somebody who never asked for one.
    if record.story:
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
    simple_mode: bool = False,
) -> CachedTurn | None:
    """Layer 1: this exact question, from this exact audience, asked before."""
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
            simple_mode=simple_mode,
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
            simple_mode=record.simple_mode,
        )
    except Exception:
        logger.warning("The response cache could not be written.", exc_info=True)


# ── the rolling summary ──────────────────────────────────────────────────────

#: Messages kept verbatim in the checkpoint before older ones are compressed.


def summarisation_wanted() -> bool:
    """Whether this deployment folds older turns into a summary at all."""
    settings = get_settings()
    return settings.memory_window_enabled and database_enabled()


async def summarise_thread(graph: Any, config: dict[str, Any]) -> bool:
    """Compress a long thread's older turns, AFTER the answer has gone out."""
    if not summarisation_wanted():
        return False

    from app.context.session_context import RECENT_TURNS
    from app.graph.main_graph import SUMMARY_AFTER_MESSAGES

    # A graph compiled without a checkpointer has no state to read back, and that is supported.
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

    # Everything the verbatim window does NOT carry, which is not the same
    # boundary as the trigger above.
    #
    # `SUMMARY_AFTER_MESSAGES` was doing both jobs: deciding WHEN to summarise
    # (12 messages) and WHERE the summary ends (also 12). But the prompt carries
    # the last `RECENT_TURNS` messages verbatim, which is 6 -- so messages 7 to
    # 12 back were in neither the summary nor the window. Six messages, three
    # exchanges, silently absent from what the model could see.
    #
    # The trigger stays at 12: summarising a four-message thread costs a model
    # call to compress nothing.
    older = messages[:-RECENT_TURNS]
    redacted = [
        pii.redact_for_summary(text_of(message))
        for message in older
        if text_of(message).strip()
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

