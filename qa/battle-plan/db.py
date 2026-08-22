"""One read (or one write) against the app's own database, per call.

The app's engine is bound to the loop that created it, so a second
`asyncio.run` finds it closed. Every call here opens its own connection and
closes it, which is slower and correct.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


def _dsn() -> str:
    from app.config import get_settings
    raw = str(get_settings().database_url)
    # asyncpg speaks its own dialect of the URL: no SQLAlchemy driver suffix, and
    # `sslmode`/`channel_binding` are libpq spellings it does not accept.
    raw = raw.replace("postgresql+asyncpg://", "postgresql://")
    raw = re.sub(r"[?&](sslmode|channel_binding)=[^&]*", "", raw)
    return raw.rstrip("?&")


async def _run(query: str, params: list[Any], fetch: bool) -> list[dict]:
    import asyncpg
    conn = await asyncpg.connect(_dsn(), ssl="require", timeout=30)
    try:
        if fetch:
            rows = await conn.fetch(query, *params)
            return [dict(r) for r in rows]
        await conn.execute(query, *params)
        return []
    finally:
        await conn.close()


def query(sql: str, *params: Any) -> list[dict]:
    """A read. `$1`-style placeholders, because this is asyncpg."""
    try:
        return asyncio.run(_run(sql, list(params), True))
    except Exception as exc:  # noqa: BLE001
        print(f"    (db read failed: {type(exc).__name__}: {str(exc)[:160]})")
        return []


def execute(sql: str, *params: Any) -> bool:
    try:
        asyncio.run(_run(sql, list(params), False))
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"    (db write failed: {type(exc).__name__}: {str(exc)[:160]})")
        return False


def user_id(email: str) -> str | None:
    rows = query("select id::text as id from users where lower(email)=lower($1)", email)
    return rows[0]["id"] if rows else None


def mint_auth_token(email: str, purpose: str, *, expired: bool = False) -> str | None:
    """An `auth_tokens` row written the way `accounts._issue` writes one."""
    uid = user_id(email)
    if uid is None:
        return None
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    expires = datetime.now(timezone.utc) + (timedelta(hours=-1) if expired else timedelta(hours=6))
    ok = execute(
        "insert into auth_tokens (id, user_id, purpose, token_hash, expires_at) "
        "values (gen_random_uuid(), $1::uuid, $2, $3, $4)",
        uid, purpose, digest, expires)
    return token if ok else None


def count_users(email: str) -> int:
    rows = query("select count(*)::int as n from users where lower(email)=lower($1)", email)
    return rows[0]["n"] if rows else -1
