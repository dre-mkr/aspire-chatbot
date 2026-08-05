"""Staff identity. A separate realm from the public chat, deliberately.

## The two token types cannot be interchanged

A chat session token has `typ: "aspire.session"`; a staff token has
`typ: "aspire.staff"`. `decode_staff` requires the latter and `hydrate`
requires the former, so neither will accept the other even though both are
signed with `SESSION_SECRET`.

That is the whole point of F1's "do not share session tokens with the public
chat". The risk being closed is not that a child would guess an admin password
-- it is that a single XSS on the chat surface, or one leaked bearer token from
a shared device, would otherwise reach a queue of children's identity documents.

## Roles are a ladder, not a set

    reviewer < supervisor < admin

`requires(role)` checks the ladder position, so a supervisor satisfies a
reviewer requirement without being granted it explicitly. A set of independent
permissions would be more flexible and would also mean somebody has to remember
to add `documents:read` to the supervisor role, which is exactly the kind of
thing that gets forgotten in the direction of too much access.

## Every read is audited, and document reads are audited separately

`audit` writes a row for a record view. `audit_document` writes one for a
document access, with its own index. They are separated because they answer
different questions and only one of them is "who looked at this child's
papers?".
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Header, HTTPException, Request

from app.auth import ALGORITHM, _secret

logger = logging.getLogger(__name__)

TOKEN_TYPE = "aspire.staff"

#: Shorter than a chat session's seven days. A staff token opens a queue of
#: identity documents, and the refresh path is a person signing in at a desk
#: rather than a background call on a child's phone.
TOKEN_TTL = timedelta(hours=12)

#: Lowest to highest. `requires` compares by index.
ROLES: tuple[str, ...] = ("reviewer", "supervisor", "admin")


@dataclass(frozen=True, slots=True)
class Staff:
    """A verified staff member. Only ever produced by `decode_staff`."""

    staff_id: str
    email: str
    role: str

    def at_least(self, role: str) -> bool:
        try:
            return ROLES.index(self.role) >= ROLES.index(role)
        except ValueError:
            # An unknown role satisfies nothing. Fail closed: a typo in a role
            # string must not grant admin.
            return False


def mint_staff_token(
    *, staff_id: str, email: str, role: str, ttl: timedelta = TOKEN_TTL
) -> str:
    if role not in ROLES:
        raise ValueError(f"{role!r} is not a role")
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "typ": TOKEN_TYPE,
            "sub": staff_id,
            "eml": email,
            "rol": role,
            "iat": int(now.timestamp()),
            "exp": int((now + ttl).timestamp()),
            "jti": uuid.uuid4().hex,
        },
        _secret(),
        algorithm=ALGORITHM,
    )


def decode_staff(token: str | None) -> Staff | None:
    """Verify a staff token. None for every failure.

    No grace window, unlike the chat token. A chat token expiring mid-reply is
    our problem to absorb; a staff token expiring mid-review is a person who
    signs in again, and the alternative is a longer effective lifetime on the
    credential that reaches the documents.
    """
    if not token:
        return None
    try:
        claims = jwt.decode(
            token,
            _secret(),
            algorithms=[ALGORITHM],
            options={"require": ["typ", "sub", "rol", "exp"]},
        )
    except Exception:
        return None
    if claims.get("typ") != TOKEN_TYPE:
        # A chat session token presented at the admin door. Refused rather than
        # coerced -- it carries no role, and inventing one is unthinkable here.
        return None
    role = str(claims.get("rol") or "")
    if role not in ROLES:
        return None
    return Staff(
        staff_id=str(claims["sub"]),
        email=str(claims.get("eml") or ""),
        role=role,
    )


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


async def current_staff(authorization: str | None = Header(default=None)) -> Staff:
    """The signed-in staff member, or 401."""
    staff = decode_staff(_bearer(authorization))
    if staff is None:
        raise HTTPException(status_code=401, detail="Staff sign-in is required.")
    return staff


def requires(role: str):
    """A dependency asserting at least `role`.

    Used as `Depends(requires("supervisor"))`. The 403 message names the role
    required rather than the role held, because telling somebody what they are
    is fine and telling them what the boundary is helps them ask the right
    person for it.
    """

    async def dependency(authorization: str | None = Header(default=None)) -> Staff:
        staff = await current_staff(authorization)
        if not staff.at_least(role):
            raise HTTPException(
                status_code=403, detail=f"This needs the {role} role."
            )
        return staff

    return dependency


# ── audit ────────────────────────────────────────────────────────────────────


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Rightmost only: everything left of the edge's own entry is
        # client-controlled, and an audit row recording a spoofed address is
        # worse than one recording none.
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else None


async def audit(
    staff: Staff,
    *,
    action: str,
    subject_type: str,
    subject_id: str,
    detail: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """Append one audit row.

    Never raises. An audit write that failed must not turn a reviewer's page
    load into a 500 -- but it is logged at ERROR, because a gap in this table
    is a gap in the only record of who saw what.
    """
    import json

    from sqlalchemy import text as sql

    from app.db import session

    try:
        async with session() as db:
            if db is None:
                logger.error(
                    "No database: audit row for %s on %s %s was NOT recorded.",
                    action,
                    subject_type,
                    subject_id,
                )
                return
            await db.execute(
                sql(
                    """
                    INSERT INTO audit_log (actor, actor_role, action,
                                           subject_type, subject_id, detail, ip)
                    VALUES (:actor, :role, :action, :subject_type, :subject_id,
                            CAST(:detail AS jsonb), :ip)
                    """
                ),
                {
                    "actor": staff.staff_id,
                    "role": staff.role,
                    "action": action,
                    "subject_type": subject_type,
                    "subject_id": subject_id,
                    "detail": json.dumps(detail or {}),
                    "ip": ip,
                },
            )
            await db.commit()
    except Exception:
        logger.exception(
            "Could not write an audit row for %s on %s %s.",
            action,
            subject_type,
            subject_id,
        )


async def audit_document(
    staff: Staff, *, document_id: str, application_id: str, ip: str | None = None
) -> None:
    """A document access. Its own action and its own partial index.

    Separated from a record view because "who read this application?" and "who
    downloaded this child's birth certificate?" are different questions, and
    the second one is asked under different circumstances.
    """
    await audit(
        staff,
        action="document.access",
        subject_type="document",
        subject_id=document_id,
        detail={"application_id": application_id},
        ip=ip,
    )
