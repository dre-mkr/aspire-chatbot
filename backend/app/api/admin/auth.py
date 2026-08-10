"""Staff identity."""

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

#: Shorter than a chat session's seven days.
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
            # An unknown role satisfies nothing.
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
    """Verify a staff token."""
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
        # A chat session token presented at the admin door.
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
    """A dependency asserting at least `role`."""

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
        # Rightmost only: everything left of the edge's own entry is client-controlled, and an audit row recording a sp…
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
    """Append one audit row."""
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
    """A document access."""
    await audit(
        staff,
        action="document.access",
        subject_type="document",
        subject_id=document_id,
        detail={"application_id": application_id},
        ip=ip,
    )
