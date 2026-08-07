"""Building the SessionContext: one node, one round trip, one cache.

Runs between `safety_in` and `cards`, which is before routing -- so the router
and every agent after it read the same object, and nothing downstream needs to
ask the database who this is.

## One round trip, and why it is one

The four reads this needs -- the user row, the mastery rows, the open
application, the last ticket -- are four queries against one database in one
session. They are issued together in a single `session()` block rather than by
four nodes at four points in the turn, which is the shape the diagnosis found:
`resume_or_place` fetched mastery (`learn/graph.py:112`), the registration
subgraph walked the draft, and nothing shared either.

## The cache is keyed on the session and is deliberately short

`SESSION_TTL` is 90 seconds. Long enough that a reader typing three messages in
a row pays for one resolve; short enough that a mastery row written by turn two
is visible on turn four. It is NOT a correctness mechanism -- every field here is
re-read on a miss -- so the failure mode of a stale entry is a slightly old
mastery figure in a prompt, not a wrong answer.

Two things are deliberately excluded from the cached payload and recomputed on
every turn: `now`, because a cached clock is a wrong clock, and `recent_turns`,
because those come from graph state rather than the database and change every
turn by definition.

## Identity is copied, not looked up

`persona`, `age_band`, `account_status` and `locale` come off state, which
`hydrate` filled from the signed token after discarding anything the body tried
to set (`graph/nodes/hydrate.py:122`). This module never reads the body and never
re-derives identity from the account -- if the token and the account disagree,
the token is the authority and `account.derive` is where that is settled.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.context.session_context import (
    RECENT_TURNS,
    ApplicationRef,
    SessionContext,
    TicketRef,
    Turn,
    now_local,
)
from app.graph.state import AspireState

logger = logging.getLogger(__name__)

#: How long a resolved context stays warm, in seconds.
SESSION_TTL = 90

_CACHE_PREFIX = "ctx:"


def _recent_turns(state: AspireState) -> list[Turn]:
    """The last few exchanges, verbatim, oldest first.

    From `messages` rather than from the database: the graph's own message list
    is the authority for what was said this session, and it is already in memory.
    """
    turns: list[Turn] = []
    for message in list(state.get("messages") or [])[-RECENT_TURNS:]:
        kind = getattr(message, "type", None)
        if kind not in ("human", "ai"):
            continue
        content = getattr(message, "content", "")
        if isinstance(content, list):
            content = "".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        text = str(content or "").strip()
        if text:
            turns.append(Turn(role="user" if kind == "human" else "assistant", text=text))
    return turns


def _normalise_mastery(rows: list[Any]) -> dict[str, float]:
    """The integer mastery scale as 0.0-1.0.

    Normalised here so that no reader of `SessionContext` needs to know the
    ceiling is 3 (`learning/mastery.py:50`). A consumer comparing against a
    threshold should be comparing fractions.
    """
    from app.learning.mastery import MAX_SCORE

    return {
        row.concept_id: min(1.0, max(0.0, row.score / MAX_SCORE))
        for row in rows
        if getattr(row, "concept_id", None)
    }


def _seen_today(rows: list[Any]) -> list[str]:
    today = now_local().date()
    return sorted(
        row.concept_id
        for row in rows
        if getattr(row, "last_seen", None) and row.last_seen.astimezone(
            now_local().tzinfo
        ).date() == today
    )


async def _from_database(user_id: str | None) -> dict[str, Any]:
    """The four reads, in one session. Returns plain JSON-able values.

    Every read is individually optional. A learner with no mastery rows, no
    application and no ticket is the normal case for a first session, and none of
    those absences is an error -- so each failure degrades to its own empty value
    rather than failing the turn. A context that is missing `display_name` still
    routes correctly; a turn that raised here would not run at all.
    """
    empty: dict[str, Any] = {
        "display_name": None,
        "mastery": {},
        "concepts_seen_today": [],
        "last_game": None,
        "open_application": None,
        "last_escalation": None,
    }
    if not user_id:
        return empty

    from sqlalchemy import text as sql

    from app.db import session

    out = dict(empty)
    try:
        async with session() as db:
            if db is None:
                return out

            name = (
                await db.execute(
                    sql("SELECT display_name FROM users WHERE id = :uid"), {"uid": user_id}
                )
            ).scalar()
            out["display_name"] = name

            application = (
                await db.execute(
                    sql(
                        # `owner_user_id`, not `owner_id`. The column has been
                        # `owner_user_id` since migration 0014 created the table;
                        # `conversations` is the one with `owner_id`, and the two
                        # got crossed here. Postgres raised UndefinedColumnError on
                        # every signed-in turn, this whole function fell to its
                        # except branch, and the agent lost the learner's display
                        # name and any draft application alongside the one lookup
                        # that was actually wrong.
                        "SELECT id, status FROM applications "
                        "WHERE owner_user_id = :uid AND status = 'draft' "
                        "ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"uid": user_id},
                )
            ).first()
            if application:
                out["open_application"] = {"application_id": str(application[0])}

            ticket = (
                await db.execute(
                    sql(
                        "SELECT id, category, created_at FROM tickets "
                        "WHERE user_id = :uid ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"uid": user_id},
                )
            ).first()
            if ticket:
                out["last_escalation"] = {
                    "ticket_id": str(ticket[0]),
                    "reason": str(ticket[1] or "general"),
                    "opened_at": ticket[2].isoformat() if ticket[2] else None,
                }
    except Exception:
        logger.warning("Could not resolve session context from the database.", exc_info=True)
        return out

    try:
        from app.learning.mastery import PostgresMasteryStore

        rows = await PostgresMasteryStore().all_for(user_id)
        out["mastery"] = _normalise_mastery(rows)
        out["concepts_seen_today"] = _seen_today(rows)
    except Exception:
        logger.warning("Could not resolve mastery for the session context.", exc_info=True)

    return out


async def _cached(user_id: str | None, session_id: str) -> dict[str, Any] | None:
    from app import cache as response_cache

    client = response_cache.get_client()
    if client is None:
        return None
    try:
        raw = await client.get(f"{_CACHE_PREFIX}{session_id}")
        return json.loads(raw) if raw else None
    except Exception:
        # A cache outage costs a round trip, never a turn.
        return None


async def _store(session_id: str, payload: dict[str, Any]) -> None:
    from app import cache as response_cache

    client = response_cache.get_client()
    if client is None:
        return
    try:
        await client.set(
            f"{_CACHE_PREFIX}{session_id}", json.dumps(payload), ex=SESSION_TTL
        )
    except Exception:
        return


def make_resolve_context(loader=None):
    """The node. `loader` is `async (user_id) -> dict`, injected for tests.

    Writes `state["context"]`. Runs before routing so that `classify` and every
    agent read one object rather than each deriving its own view.
    """

    async def resolve_context(state: AspireState) -> dict[str, Any]:
        from app.cache import corpus_fingerprint

        session_id = str(state.get("session_id") or "")
        user_id = state.get("user_id")
        user_id = str(user_id) if user_id else None

        payload = await _cached(user_id, session_id) if session_id else None
        if payload is None:
            payload = await (loader or _from_database)(user_id)
            if session_id:
                await _store(session_id, payload)

        application = payload.get("open_application")
        ticket = payload.get("last_escalation")

        # The registration draft's own step pointer wins over the database row:
        # it is this turn's state and the row is one turn behind. Only the
        # pointer is taken -- never `values`, which is FINDINGS.md F1.
        registration = state.get("registration")
        if isinstance(registration, dict) and registration.get("application_id"):
            application = {
                "application_id": str(registration["application_id"]),
                "current_step": registration.get("awaiting"),
                "active_child_index": int(registration.get("child_index") or 0),
            }

        learning = state.get("learning")
        last_game = payload.get("last_game")
        if isinstance(learning, dict):
            last_game = learning.get("last_game") or last_game

        context = SessionContext(
            persona=str(state.get("persona") or ""),
            age_band=str(state.get("age_band") or ""),
            locale=str(state.get("locale") or "en"),
            account_status=str(state.get("account_status") or ""),
            display_name=payload.get("display_name"),
            recent_turns=_recent_turns(state),
            running_summary=str(state.get("summary") or ""),
            mastery=dict(payload.get("mastery") or {}),
            concepts_seen_today=list(payload.get("concepts_seen_today") or []),
            last_game=last_game,
            open_application=ApplicationRef(**application) if application else None,
            last_escalation=TicketRef(**ticket) if ticket else None,
            kb_version=corpus_fingerprint(),
            now=now_local(),
        )
        return {"context": context}

    return resolve_context
