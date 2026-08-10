"""Signing a staff member in, and creating the first one."""

from __future__ import annotations

import argparse
import asyncio
import logging
import secrets
import sys
from dataclasses import dataclass

import bcrypt

from app.api.admin.auth import ROLES, Staff, mint_staff_token

logger = logging.getLogger(__name__)

#: A generated password.
GENERATED_PASSWORD_BYTES = 12

MIN_PASSWORD_LENGTH = 12


@dataclass(frozen=True, slots=True)
class SignInResult:
    token: str
    staff: Staff
    must_change_password: bool


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def password_problem(password: str) -> str | None:
    """Why this password is not acceptable, or None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."
    if len(password.encode("utf-8")) > 72:
        # bcrypt truncates silently at 72 bytes, which would make two different long passwords equivalent.
        return "That password is too long. Use 72 characters or fewer."
    return None


async def sign_in(email: str, password: str) -> SignInResult | None:
    """Verify a staff credential."""
    from sqlalchemy import text as sql

    from app.db import session

    async with session() as db:
        if db is None:
            logger.error("No database, so staff sign-in cannot be verified.")
            return None
        row = (
            await db.execute(
                sql(
                    """
                    SELECT id, email, full_name, password_hash, role, active,
                           must_change_password
                      FROM staff
                     WHERE lower(email) = lower(:email)
                    """
                ),
                {"email": email},
            )
        ).first()

    if row is None:
        # A bcrypt round against a throwaway hash, so a missing account costs the same as a wrong password.
        bcrypt.checkpw(b"x", bcrypt.gensalt())
        return None

    if not bcrypt.checkpw(password.encode("utf-8"), row[3].encode("ascii")):
        return None
    if not row[5]:
        # Checked AFTER the password, so a disabled account is indistinguishable from a wrong one -- otherwise disablin…
        logger.warning("Sign-in refused for disabled staff account %s.", row[1])
        return None

    staff = Staff(staff_id=str(row[0]), email=row[1], role=row[4])
    logger.info("staff sign-in: %s (%s)", staff.email, staff.role)
    return SignInResult(
        token=mint_staff_token(
            staff_id=staff.staff_id, email=staff.email, role=staff.role
        ),
        staff=staff,
        must_change_password=bool(row[6]),
    )


async def change_password(staff_id: str, current: str, new: str) -> str | None:
    """Rotate a password."""
    problem = password_problem(new)
    if problem:
        return problem

    from sqlalchemy import text as sql

    from app.db import session

    async with session() as db:
        if db is None:
            return "Passwords cannot be changed right now."
        row = (
            await db.execute(
                sql("SELECT password_hash FROM staff WHERE id = CAST(:id AS uuid)"),
                {"id": staff_id},
            )
        ).first()
        if row is None or not bcrypt.checkpw(
            current.encode("utf-8"), row[0].encode("ascii")
        ):
            return "That is not your current password."

        await db.execute(
            sql(
                """
                UPDATE staff
                   SET password_hash = :hash,
                       must_change_password = false,
                       -- Every token issued under the old password stops
                       -- working. A password change that leaves old sessions
                       -- alive is a password change that does not help the
                       -- person whose laptop was taken.
                       session_epoch = session_epoch + 1
                 WHERE id = CAST(:id AS uuid)
                """
            ),
            {"id": staff_id, "hash": hash_password(new)},
        )
        await db.commit()

    logger.info("staff password changed for %s", staff_id)
    return None


async def create_staff(email: str, role: str, full_name: str = "") -> tuple[str, str]:
    """Create an account with a generated password."""
    if role not in ROLES:
        raise ValueError(f"{role!r} is not a role. Use one of: {', '.join(ROLES)}")

    from sqlalchemy import text as sql

    from app.db import session

    password = secrets.token_urlsafe(GENERATED_PASSWORD_BYTES)

    async with session() as db:
        if db is None:
            raise RuntimeError("No database is configured.")
        row = (
            await db.execute(
                sql(
                    """
                    INSERT INTO staff (email, full_name, password_hash, role)
                    VALUES (:email, :full_name, :hash, :role)
                    ON CONFLICT DO NOTHING
                    RETURNING id
                    """
                ),
                {
                    "email": email,
                    "full_name": full_name,
                    "hash": hash_password(password),
                    "role": role,
                },
            )
        ).first()
        await db.commit()

    if row is None:
        raise ValueError(f"A staff account already exists for {email}.")
    return str(row[0]), password


def main() -> int:
    """`python -m app.api.admin.staff create <email> --role reviewer`."""
    parser = argparse.ArgumentParser(description="Manage ASPIRE staff accounts.")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="create a staff account")
    create.add_argument("email")
    create.add_argument("--role", default="reviewer", choices=list(ROLES))
    create.add_argument("--name", default="")

    args = parser.parse_args()

    if args.command == "create":
        try:
            staff_id, password = asyncio.run(
                create_staff(args.email, args.role, args.name)
            )
        except (ValueError, RuntimeError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1

        print(f"Created {args.email} ({args.role})")
        print(f"  id:       {staff_id}")
        print(f"  password: {password}")
        print()
        # Said out loud, because the alternative is one password everybody in the office knows.
        print("Give this password to them directly. They must change it on first")
        print("sign-in; the portal will not let them past until they do.")
        return 0

    return 1  # pragma: no cover - argparse requires a subcommand


if __name__ == "__main__":
    sys.exit(main())
