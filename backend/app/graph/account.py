"""Turning an account record into the claims a session token carries.

`persona`, `age_band` and `account_status` are the three values the access
matrix reads. Everything about their trustworthiness rests on their being
derived HERE, server-side, from a row in `users` -- and never taken from the
request that asks for a token.

That is not a general principle applied out of habit. It is the specific thing
that stops a caller writing `{"age_band": "adult"}` in a JSON body and being
handed `register_agent`, which collects a national ID and a date of birth.

## The client may narrow. It may never widen.

A persona is also a voice and a reading level, and people reasonably want to
choose one -- an adult may prefer Nova's plainer register to Aurora's. So a
requested persona IS honoured, on one condition, checked by running the matrix
both ways: the agents it grants must be a subset of the agents the derived
persona grants.

`_narrowing` is that check. It means "let me be Nova instead of Aurora" works
(Nova has no `servicing_agent`, so it is strictly narrower) and "let me be
Aurora instead of Stella" does not, without either case being special-cased.

## Age says how to talk to somebody. Role says who they are.

`users.role` -- `participant`, `guardian` or `educator` -- is read here too, and
it exists because age alone was answering a question it does not know. A teacher
and a sixteen-year-old born the same week were the same account.

It is a THIRD narrowing input and not a fourth grant. `ROLE_PERSONA` offers a
persona, `_narrowing` decides whether the band will take it, and a role that
asks for more than the band already gives is refused exactly as a client's
request is. A self-declared "guardian" in a child band therefore buys nothing;
what actually gates the guardian persona is an adult date of birth, refused at
sign-up by `accounts._role_problem` rather than negotiated here.

## Not knowing somebody's age means treating them as the youngest

`is_minor` with no `date_of_birth` resolves to `5-8`, the narrowest band in the
table. A record that has lost its date of birth is not a reason to grant more,
and a fourteen-year-old briefly offered the five-year-old's mascot is a mistake
that can be corrected by filling the field in. The reverse cannot.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from app.graph.access import allowed_agents

logger = logging.getLogger(__name__)

#: The youngest band ASPIRE serves. Someone below it is not turned away -- the
#: programme is for children, and a four-year-old sitting with a parent is a
#: real user -- they are simply served the youngest band's content.
YOUNGEST_BAND = "5-8"


@dataclass(frozen=True, slots=True)
class DerivedClaims:
    persona: str
    age_band: str
    account_status: str
    #: True when the request asked for a persona that was not granted. Logged by
    #: the caller: a client repeatedly asking to widen is worth noticing.
    persona_request_refused: bool = False


def band_for(born: date | None, *, is_minor: bool, today: date | None = None) -> str:
    """Which band a date of birth falls in.

    The bands are inclusive at both ends and there is no gap between them, so
    every age from 5 up lands somewhere. Under 5 is folded into the youngest
    band rather than rejected -- see `YOUNGEST_BAND`.
    """
    if born is None:
        return YOUNGEST_BAND if is_minor else "adult"

    today = today or date.today()
    years = today.year - born.year - ((today.month, today.day) < (born.month, born.day))

    if years <= 8:
        return YOUNGEST_BAND
    if years <= 12:
        return "9-12"
    if years <= 15:
        return "13-15"
    if years <= 18:
        return "16-18"
    return "adult"


#: The persona each band gets unless a narrower one is asked for.
#:
#: A table rather than a chain of comparisons, because "which mascot does a
#: twelve-year-old get?" should be answerable by looking rather than by
#: tracing.
#:
#: ## 9-12 is Stella, and the product's copy now says so too
#:
#: The ACCESS MATRIX grants Orion only at 13-15 and 16-18 --
#: `allowed_agents("orion", "9-12", …)` returns `[]`, which every caller must
#: treat as a hard 403.
#:
#: This table had `9-12: orion`, taken from `personas.ts`, which advertised
#: Orion as "Ages 10–18". So every nine-to-twelve-year-old was issued a token
#: the matrix denies outright: `guard` halted the turn and the band was locked
#: out of the product entirely. Found by running one, not by a test.
#:
#: Resolved towards the matrix, because the matrix is the security control and
#: the blurb is a line in a menu. SETTLED IN BOTH PLACES (P15-017): `personas.ts`
#: now reads "Ages 5–12" and "Ages 13–18", so the menu no longer offers an
#: eleven-year-old a persona the server will refuse. Widening Orion to 9-12 was
#: the other way to settle it and was NOT taken -- it enlarges what a child-band
#: token reaches, which is a security decision and not a copy fix.
#:
#: `test_account.py` asserts that every entry here resolves to a non-empty agent
#: list, so this class of mismatch cannot come back silently.
DEFAULT_PERSONA: dict[str, str] = {
    "5-8": "stella",
    "9-12": "stella",
    "13-15": "orion",
    "16-18": "orion",
    "adult": "aurora",
}

#: The persona each ROLE prefers -- offered to the band, never imposed on it.
#:
#: ## What this fixes
#:
#: The table above is keyed on age alone, which is right for a participant and
#: has nothing to say about anybody else. A teacher and a sixteen-year-old with
#: the same birthday were the same account, and the only way to be Nova was to
#: ask for it by hand on every session.
#:
#: ## What it deliberately cannot do
#:
#: Widen. The preference is put through `_narrowing` exactly as a client's
#: request is, so it is honoured only when it grants no more than the band's own
#: persona already does. Worked through, because the whole safety of a
#: self-declared role rests on it:
#:
#:   educator + adult   -> nova ⊂ aurora, honoured.
#:   educator + 13-15   -> nova has full `qa_agent`, Orion 13-15 has
#:                         `qa_agent_limited`. WIDER, so refused: a
#:                         fourteen-year-old who ticks "teacher" still gets the
#:                         band-filtered knowledge base.
#:   guardian + adult   -> aurora is already the band's default. No change.
#:   guardian + 16-18   -> aurora carries `register_agent`. WIDER, so refused.
#:
#: That last row is why `accounts._role_problem` refuses the sign-up outright
#: rather than letting it through to be quietly downgraded here. An account in
#: that state is not repairable from inside the product -- it is exactly the
#: state that produced the refusal this change came from -- so it is better not
#: to create it than to explain it afterwards.
#:
#: `participant` is absent rather than mapped to a persona: it has no preference
#: of its own, and the band decides. A `.get` miss and an explicit "no
#: preference" would be the same value, so only one of them is written down.
ROLE_PERSONA: dict[str, str] = {
    "guardian": "aurora",
    "educator": "nova",
}


def _narrowing(
    requested: str, derived: str, *, age_band: str, account_status: str
) -> bool:
    """Whether `requested` grants no more than `derived` does.

    Both are run through the real matrix with the real band and status, so this
    cannot drift away from the authorisation it is approximating -- it IS the
    authorisation, asked twice.
    """
    if requested == derived:
        return True
    mine = set(
        allowed_agents(requested, age_band, account_status, user_id="derivation")
    )
    theirs = set(
        allowed_agents(derived, age_band, account_status, user_id="derivation")
    )
    return bool(mine) and mine <= theirs


def persona_for(
    age_band: str, role: str | None, *, account_status: str = "prospect"
) -> str:
    """The persona this band and role resolve to, before any client request.

    Split out of `derive` because two callers need the answer without needing
    the rest of the claims: `sessions.to_session`, which tells the client which
    persona its account will get so the picker can be right on first paint, and
    `derive` itself.

    `account_status` is asked for and passed through to `allowed_agents` rather
    than assumed, even though no row in the matrix currently branches on it.
    Defaulting it here would put a "status does not matter" assumption in a
    second file, and it is not this function's assumption to make.
    """
    persona = DEFAULT_PERSONA.get(age_band, "aurora")
    preferred = ROLE_PERSONA.get(str(role or "participant"))
    if (
        preferred
        and preferred != persona
        and _narrowing(
            preferred, persona, age_band=age_band, account_status=account_status
        )
    ):
        return preferred
    return persona


def derive(
    *,
    born: date | None,
    is_minor: bool,
    account_status: str,
    role: str | None = None,
    requested_persona: str | None = None,
    today: date | None = None,
) -> DerivedClaims:
    """The claims for one session, from the account record and nothing else.

    Two narrowings happen here and they compose in this order: the account's
    ROLE may narrow away from the band's default, and then the client's REQUEST
    may narrow again from wherever that landed. Both go through `_narrowing`, so
    neither can widen and the second cannot undo the first's limits.
    """
    age_band = band_for(born, is_minor=is_minor, today=today)
    persona = persona_for(age_band, role, account_status=account_status)
    refused = False

    if requested_persona and requested_persona != persona:
        if _narrowing(
            requested_persona,
            persona,
            age_band=age_band,
            account_status=account_status,
        ):
            persona = requested_persona
        else:
            refused = True

    return DerivedClaims(
        persona=persona,
        age_band=age_band,
        account_status=account_status,
        persona_request_refused=refused,
    )


# ── the account read ─────────────────────────────────────────────────────────

#: Application status → what the holder is to the chat. Anything not listed --
#: `draft`, `rejected` -- leaves them a prospect, which is correct: a draft is
#: somebody who started and a rejection is somebody who may start again, and
#: neither is an account holder.
_STATUS_FROM_APPLICATION: dict[str, str] = {
    "submitted": "applicant",
    "under_review": "applicant",
    "info_requested": "applicant",
    "approved": "beneficiary",
}


async def claims_for(
    user_id: str | None, *, requested_persona: str | None = None
) -> DerivedClaims:
    """Read the account and derive its claims. Never raises.

    An anonymous caller -- or one whose record cannot be read -- gets the
    conservative default: a `5-8` prospect. That is the narrowest identity the
    matrix has, and `guard` narrows it further still because the turn is
    unauthenticated. Somebody who should have had more gets less and can be
    corrected by signing in again; somebody who gets more than they should
    cannot be.
    """
    if not user_id:
        return DerivedClaims(
            persona="stella", age_band=YOUNGEST_BAND, account_status="prospect"
        )

    from app.db import database_enabled

    if not database_enabled():
        return DerivedClaims(
            persona="stella", age_band=YOUNGEST_BAND, account_status="prospect"
        )

    from sqlalchemy import text as sql

    from app.db import session

    try:
        async with session() as db:
            if db is None:
                raise RuntimeError("no session")
            row = (
                await db.execute(
                    sql(
                        """
                        SELECT u.date_of_birth,
                               u.is_minor,
                               u.account_type,
                               u.role,
                               (
                                 SELECT a.status
                                   FROM applications a
                                  WHERE a.owner_user_id = CAST(u.id AS text)
                               ORDER BY a.created_at DESC
                                  LIMIT 1
                               ) AS application_status
                          FROM users u
                         WHERE u.id = CAST(:id AS uuid)
                        """
                    ),
                    {"id": str(user_id)},
                )
            ).first()
    except Exception:
        logger.warning(
            "Could not read the account record for %s; issuing the narrowest "
            "identity in the matrix.",
            user_id,
            exc_info=True,
        )
        return DerivedClaims(
            persona="stella", age_band=YOUNGEST_BAND, account_status="prospect"
        )

    if row is None:
        logger.warning("No account record for %s; issuing the narrowest identity.", user_id)
        return DerivedClaims(
            persona="stella", age_band=YOUNGEST_BAND, account_status="prospect"
        )

    born, is_minor, _account_type, role, application_status = row
    status = _STATUS_FROM_APPLICATION.get(str(application_status or ""), "prospect")

    # Somebody with an application in flight who is not themselves the child is
    # a guardian applying, not an applicant for themselves: the registration
    # schema collects a guardian and one or more children, and there is no
    # self-application.
    #
    # The stored role answers this directly now. The band test stays beside it
    # and is not redundant: every account created before migration 0017 was
    # backfilled to `participant`, so an existing guardian is recognisable only
    # by their adult band. Dropping it would silently demote them.
    band = band_for(born, is_minor=bool(is_minor))
    if status in ("applicant", "beneficiary") and (role == "guardian" or band == "adult"):
        status = "guardian"

    return derive(
        born=born,
        is_minor=bool(is_minor),
        account_status=status,
        role=role,
        requested_persona=requested_persona,
    )
