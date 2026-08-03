"""Registering, signing in, and getting back in when the password is gone.

Everything here accepts the caller's current anonymous token alongside the
credentials, so the work done before signing up follows them into the account.
That is `claim.py`, and it runs inside the same transaction as the sign-up or
sign-in that triggered it.

## Not saying which addresses exist

`/forgot`, `/signin-link` and `/register` are all careful not to become a way to
test whether an address has an account. The first two answer identically whether
or not they found one; `/register` cannot, because "this email is already
registered" is genuinely what the person needs to be told — so it says so and
accepts the disclosure, which is the same trade every product with a sign-up
form makes.

Sign-in failures never distinguish "no such account" from "wrong password", and
`verify_password` burns a hash even when there is no password to check, so the
timing does not answer the question the message refuses to.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AfterValidator, BaseModel, Field
from sqlalchemy import func, select

from app import mail
from app.auth import (
    ACCOUNT_ANONYMOUS,
    ACCOUNT_REGISTERED,
    Principal,
    client_ip,
    hash_ip,
    hash_password,
    mint_token,
    optional_principal,
    password_problem,
    require_principal,
    verify_password,
)
from app.claim import ClaimRefused, claim_anonymous, claimable
from app.db import database_enabled, session
from app.db.models import AuthToken, User
from app.sessions import SessionResponse, to_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

#: A practical address check, not a proof of deliverability.
#:
#: Pydantic's `EmailStr` needs `email-validator`, a dependency this service does
#: not otherwise want, and the strictest regex in the world still cannot tell
#: you whether an address receives mail. The confirmation link does that. This
#: only has to reject what is obviously not an address, so that a typo is caught
#: at the form rather than an hour later when no email has arrived.
_EMAIL_RE = re.compile(r"^[^@\s,;:<>\\\"]{1,64}@[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$")


def _check_email(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) > 254 or not _EMAIL_RE.match(cleaned):
        raise ValueError("That does not look like an email address.")
    return cleaned


Email = Annotated[str, AfterValidator(_check_email)]

TOKEN_LIFETIMES = {
    "reset": timedelta(hours=1),
    "verify": timedelta(days=1),
    "signin_link": timedelta(minutes=15),
}

#: Old enough to hold an account alone. Below it the account belongs to the
#: guardian named during sign-up, and their email and password are the ones on
#: it — the child's details ride along on the same row.
MINOR_AGE = 13


def _normalise_email(email: str) -> str:
    return email.strip().lower()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def age_on(born: date, today: date | None = None) -> int:
    today = today or datetime.now(timezone.utc).date()
    years = today.year - born.year
    if (today.month, today.day) < (born.month, born.day):
        years -= 1
    return years


class SignUpRequest(BaseModel):
    """Everything the four steps collect, submitted once at the end.

    The steps are a client-side wizard rather than four round trips: a
    half-finished account is not a useful thing to have in the table, and a
    person who abandons at step 3 should leave nothing behind.
    """

    email: Email
    password: str = Field(min_length=1, max_length=200)
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    date_of_birth: date
    island: str | None = Field(default=None, max_length=80)
    school: str | None = Field(default=None, max_length=160)
    guardian_name: str | None = Field(default=None, max_length=160)
    guardian_email: Email | None = None
    guardian_phone: str | None = Field(default=None, max_length=40)


class SignInRequest(BaseModel):
    email: Email
    password: str = Field(min_length=1, max_length=200)


class EmailOnlyRequest(BaseModel):
    email: Email


class ResetRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class TokenOnlyRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class ClaimOutcome(BaseModel):
    """What happened to the anonymous session, so the client can say so."""

    attempted: bool = False
    conversations: int = 0
    reason: str | None = None


class AuthResponse(SessionResponse):
    claim: ClaimOutcome = ClaimOutcome()


async def _issue(db, user: User, purpose: str) -> str:
    """A fresh one-time token, with only its hash written down."""
    token = secrets.token_urlsafe(32)
    db.add(
        AuthToken(
            id=uuid.uuid4(),
            user_id=user.id,
            purpose=purpose,
            token_hash=_hash_token(token),
            expires_at=datetime.now(timezone.utc) + TOKEN_LIFETIMES[purpose],
        )
    )
    return token


async def _redeem(db, token: str, purpose: str) -> User | None:
    """Spend a one-time token, or return None.

    `used_at` is set before anything else happens, inside the caller's
    transaction, so two requests racing the same link cannot both succeed.
    """
    row = (
        await db.execute(
            select(AuthToken)
            .where(AuthToken.token_hash == _hash_token(token), AuthToken.purpose == purpose)
            .with_for_update()
        )
    ).scalar_one_or_none()

    if row is None or row.used_at is not None:
        return None
    if row.expires_at < datetime.now(timezone.utc):
        return None

    row.used_at = datetime.now(timezone.utc)
    return await db.get(User, row.user_id)


async def _run_claim(db, principal: Principal | None, account: User) -> ClaimOutcome:
    """Carry an anonymous session into this account, if there is one to carry."""
    if principal is None or principal.user_id == account.id:
        return ClaimOutcome()
    if not await claimable(db, principal.user_id):
        # A token for an account, or one already spent. Not an error: signing in
        # twice from the same browser is ordinary.
        return ClaimOutcome(attempted=False)
    try:
        moved = await claim_anonymous(db, anonymous_id=principal.user_id, account_id=account.id)
        return ClaimOutcome(attempted=True, conversations=moved)
    except ClaimRefused as refusal:
        logger.info("Claim refused: %s", refusal)
        return ClaimOutcome(attempted=True, reason=str(refusal))


def _unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="Accounts are unavailable right now.")


@router.post("/register", response_model=AuthResponse)
async def register(
    body: SignUpRequest,
    request: Request,
    principal: Principal | None = Depends(optional_principal),
) -> AuthResponse:
    if not database_enabled():
        raise _unavailable()

    problem = password_problem(body.password)
    if problem:
        raise HTTPException(status_code=422, detail=problem)

    email = _normalise_email(str(body.email))
    age = age_on(body.date_of_birth)
    if age < 0 or age > 120:
        raise HTTPException(status_code=422, detail="Check that date of birth.")

    is_minor = age < MINOR_AGE
    if is_minor and not (body.guardian_name and body.guardian_email):
        # The under-13 account belongs to the adult named here. Refusing rather
        # than quietly creating a child-held account is the whole point of
        # asking for the date of birth first.
        raise HTTPException(
            status_code=422,
            detail="An adult needs to be named for an account for someone under 13.",
        )

    async with session() as db:
        if db is None:
            raise _unavailable()

        taken = await db.scalar(
            select(func.count()).select_from(User).where(func.lower(User.email) == email)
        )
        if taken:
            raise HTTPException(
                status_code=409, detail="That email already has an account. Try signing in."
            )

        account = User(
            id=uuid.uuid4(),
            account_type=ACCOUNT_REGISTERED,
            email=email,
            display_name=f"{body.first_name} {body.last_name}".strip(),
            password_hash=hash_password(body.password),
            first_name=body.first_name,
            last_name=body.last_name,
            date_of_birth=body.date_of_birth,
            is_minor=is_minor,
            island=body.island,
            school=body.school,
            guardian_name=body.guardian_name,
            guardian_email=_normalise_email(str(body.guardian_email))
            if body.guardian_email
            else None,
            guardian_phone=body.guardian_phone,
            session_epoch=1,
            created_ip_hash=hash_ip(client_ip(request)),
        )
        db.add(account)
        await db.flush()

        outcome = await _run_claim(db, principal, account)
        verify_token = await _issue(db, account, "verify")

    # After the transaction: an email that fails to send must not roll back an
    # account that was created successfully.
    await mail.send(mail.verify_email(email, verify_token))

    logger.info("account registered user=%s minor=%s", account.id, is_minor)
    response = to_session(account, mint_token(account.id, account.account_type, account.session_epoch))
    return AuthResponse(**response.model_dump(), claim=outcome)


@router.post("/login", response_model=AuthResponse)
async def login(
    body: SignInRequest, principal: Principal | None = Depends(optional_principal)
) -> AuthResponse:
    if not database_enabled():
        raise _unavailable()

    email = _normalise_email(str(body.email))
    async with session() as db:
        if db is None:
            raise _unavailable()

        account = (
            await db.execute(select(User).where(func.lower(User.email) == email))
        ).scalar_one_or_none()

        # One message for both failures, and `verify_password` burns a hash even
        # when there is no account, so neither the wording nor the timing says
        # whether the address exists.
        if account is None or not verify_password(body.password, account.password_hash):
            if account is None:
                verify_password(body.password, None)
            raise HTTPException(
                status_code=401, detail="That email and password do not match."
            )

        outcome = await _run_claim(db, principal, account)
        account.last_seen_at = datetime.now(timezone.utc)
        token = mint_token(account.id, account.account_type, account.session_epoch)
        response = to_session(account, token)

    return AuthResponse(**response.model_dump(), claim=outcome)


@router.post("/logout", status_code=204)
async def logout(principal: Principal = Depends(require_principal)) -> None:
    """Retire every token for this identity.

    The client asks for a brand-new anonymous session immediately afterwards. It
    is deliberately not given the previous one back: signing out on a shared
    device should not leave a thread back to who was there before.
    """
    if not database_enabled():
        return
    async with session() as db:
        if db is None:
            return
        user = await db.get(User, principal.user_id)
        if user is not None:
            user.session_epoch = user.session_epoch + 1


@router.post("/forgot", status_code=202)
async def forgot(body: EmailOnlyRequest) -> dict:
    """Send a reset link, and say the same thing either way."""
    if not database_enabled():
        raise _unavailable()

    email = _normalise_email(str(body.email))
    token: str | None = None
    async with session() as db:
        if db is None:
            raise _unavailable()
        account = (
            await db.execute(select(User).where(func.lower(User.email) == email))
        ).scalar_one_or_none()
        if account is not None:
            token = await _issue(db, account, "reset")

    if token:
        await mail.send(mail.reset_email(email, token))

    # Identical response whether or not the address is known.
    return {"sent": True}


@router.post("/reset", response_model=AuthResponse)
async def reset(body: ResetRequest) -> AuthResponse:
    if not database_enabled():
        raise _unavailable()

    problem = password_problem(body.password)
    if problem:
        raise HTTPException(status_code=422, detail=problem)

    async with session() as db:
        if db is None:
            raise _unavailable()
        account = await _redeem(db, body.token, "reset")
        if account is None:
            raise HTTPException(
                status_code=400, detail="That link has expired or has already been used."
            )
        account.password_hash = hash_password(body.password)
        # Everything signed in with the old password is signed out. A reset is
        # usually somebody taking an account back.
        account.session_epoch = account.session_epoch + 1
        token = mint_token(account.id, account.account_type, account.session_epoch)
        response = to_session(account, token)

    return AuthResponse(**response.model_dump())


@router.post("/signin-link", status_code=202)
async def signin_link(body: EmailOnlyRequest) -> dict:
    """A link that signs you in, for people who have no password to remember."""
    if not database_enabled():
        raise _unavailable()

    email = _normalise_email(str(body.email))
    token: str | None = None
    async with session() as db:
        if db is None:
            raise _unavailable()
        account = (
            await db.execute(select(User).where(func.lower(User.email) == email))
        ).scalar_one_or_none()
        if account is not None:
            token = await _issue(db, account, "signin_link")

    if token:
        await mail.send(mail.signin_link_email(email, token))
    return {"sent": True}


@router.post("/signin-link/redeem", response_model=AuthResponse)
async def redeem_signin_link(
    body: TokenOnlyRequest, principal: Principal | None = Depends(optional_principal)
) -> AuthResponse:
    if not database_enabled():
        raise _unavailable()
    async with session() as db:
        if db is None:
            raise _unavailable()
        account = await _redeem(db, body.token, "signin_link")
        if account is None:
            raise HTTPException(
                status_code=400, detail="That link has expired or has already been used."
            )
        outcome = await _run_claim(db, principal, account)
        token = mint_token(account.id, account.account_type, account.session_epoch)
        response = to_session(account, token)
    return AuthResponse(**response.model_dump(), claim=outcome)


@router.post("/verify", response_model=AuthResponse)
async def verify(body: TokenOnlyRequest) -> AuthResponse:
    if not database_enabled():
        raise _unavailable()
    async with session() as db:
        if db is None:
            raise _unavailable()
        account = await _redeem(db, body.token, "verify")
        if account is None:
            raise HTTPException(
                status_code=400, detail="That link has expired or has already been used."
            )
        account.email_verified_at = datetime.now(timezone.utc)
        token = mint_token(account.id, account.account_type, account.session_epoch)
        response = to_session(account, token)
    return AuthResponse(**response.model_dump())


__all__ = ["router", "ACCOUNT_ANONYMOUS", "age_on", "MINOR_AGE"]
