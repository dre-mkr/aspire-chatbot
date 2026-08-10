"""Turning an account record into the claims a session token carries."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from app.graph.access import allowed_agents

logger = logging.getLogger(__name__)

#: The youngest band ASPIRE serves.
YOUNGEST_BAND = "5-8"


@dataclass(frozen=True, slots=True)
class DerivedClaims:
    persona: str
    age_band: str
    account_status: str
    #: True when the request asked for a persona that was not granted.
    persona_request_refused: bool = False


def band_for(born: date | None, *, is_minor: bool, today: date | None = None) -> str:
    """Which band a date of birth falls in."""
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
DEFAULT_PERSONA: dict[str, str] = {
    "5-8": "stella",
    "9-12": "stella",
    "13-15": "orion",
    "16-18": "orion",
    "adult": "aurora",
}

#: The persona each ROLE prefers -- offered to the band, never imposed on it.
ROLE_PERSONA: dict[str, str] = {
    "guardian": "aurora",
    "educator": "nova",
}


def _narrowing(
    requested: str, derived: str, *, age_band: str, account_status: str
) -> bool:
    """Whether `requested` grants no more than `derived` does."""
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
    """The persona this band and role resolve to, before any client request."""
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
    """The claims for one session, from the account record and nothing else."""
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

#: Application status → what the holder is to the chat.
_STATUS_FROM_APPLICATION: dict[str, str] = {
    "submitted": "applicant",
    "under_review": "applicant",
    "info_requested": "applicant",
    "approved": "beneficiary",
}


#: The reading band each persona implies for an ANONYMOUS session.
_ANONYMOUS_BANDS: dict[str, str] = {
    "stella": YOUNGEST_BAND,
    "orion": "13-15",
    "aurora": "adult",
    "nova": "adult",
}

#: What an anonymous visitor gets with no persona picked.
_ANONYMOUS_DEFAULT = "aurora"


def anonymous_claims(requested_persona: str | None = None) -> DerivedClaims:
    """The claims for a caller with no account. Persona sets voice and band only."""
    persona = (requested_persona or "").strip().lower()
    if persona not in _ANONYMOUS_BANDS:
        persona = _ANONYMOUS_DEFAULT
    return DerivedClaims(
        persona=persona,
        age_band=_ANONYMOUS_BANDS[persona],
        account_status="prospect",
    )


async def claims_for(
    user_id: str | None, *, requested_persona: str | None = None
) -> DerivedClaims:
    """Read the account and derive its claims."""
    if not user_id:
        return anonymous_claims(requested_persona)

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

    # Somebody with an application in flight who is not themselves the child is a guardian applying, not an applica…
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
