"""The signed session token the graph trusts, and nothing else.

`app/auth.py` already mints a token proving *who* somebody is. This one adds
*what they are for routing purposes*: persona, age band, account status, locale
and the session id the checkpointer threads on.

They are separate tokens on purpose, and the reason is the whole point of this
module. `auth.Principal` is used by the existing REST endpoints, where the only
question is "may this caller read this row?". The graph asks a different and
much sharper question -- "how old is the person on the other end of this?" --
and the answer decides which agents may run, how long the reply may be, and
which words it may contain. That claim has to be *minted by the server* from a
record, and it must be impossible for a client to influence.

## The one rule

Identity comes from this token. It does not come from the request body, and a
request body that tries is a security event, logged as one and then ignored.
`hydrate` enforces that; this module makes it cheap by giving `hydrate` a
single trustworthy source to read.

Signed with the same `SESSION_SECRET` as `auth.py`, so there is one signing key
in the deployment and one thing to rotate. The claim set is disjoint, so a token
of one kind cannot be presented as the other: `typ` here is always
`"aspire.session"`, and `_decode` requires it.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt

from app.auth import ALGORITHM, GRACE, _secret

logger = logging.getLogger(__name__)

#: Distinguishes this from the account token minted by `auth.mint_token`.
TOKEN_TYPE = "aspire.session"

#: Matches `auth.TOKEN_TTL`. A graph session outliving an account session would
#: mean a signed-out user's conversation could still be resumed.
TOKEN_TTL = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class SessionClaims:
    """A verified session. Only ever produced by `decode_session_token`.

    Frozen, because these values are read by the access matrix and by every
    safety gate, and a mutable identity object is an identity somebody will
    mutate mid-turn to "fix" a routing problem.
    """

    session_id: str
    user_id: str | None
    device_id: str
    persona: str
    age_band: str
    account_status: str
    locale: str

    @property
    def is_anonymous(self) -> bool:
        return self.user_id is None


def mint_session_token(
    *,
    session_id: str,
    user_id: str | None,
    device_id: str,
    persona: str,
    age_band: str,
    account_status: str,
    locale: str = "en",
    ttl: timedelta = TOKEN_TTL,
) -> str:
    """Sign a session's identity.

    Every argument is keyword-only. Five of the seven are short lowercase
    strings from overlapping vocabularies -- `persona`, `age_band`,
    `account_status`, `locale` -- and a positional call site that transposed two
    of them would compile, run, and hand a fourteen-year-old an adult's agent
    set.

    Values are NOT validated here. That is deliberate: this is the minting side
    and its caller is the server, which read them from a database row. Rejecting
    on the *reading* side (`access.allowed_agents` returns `[]` for anything
    outside the closed vocabularies) means an invalid claim fails closed at the
    point where failing closed is meaningful.
    """
    now = datetime.now(timezone.utc)
    claims = {
        "typ": TOKEN_TYPE,
        "sid": session_id,
        "did": device_id,
        "per": persona,
        "band": age_band,
        "acc": account_status,
        "loc": locale,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    # OMITTED rather than set to null for an anonymous session. `sub` is a
    # registered JWT claim and RFC 7519 requires a StringOrURI; PyJWT enforces
    # that on decode and raises `InvalidSubjectError` for a null.
    #
    # This was not a theoretical standards point. `"sub": None` minted cleanly
    # and then failed to decode, so every anonymous session -- which is the
    # default path, and the one a child on a school tablet takes -- was issued a
    # token the next request rejected as unauthenticated. Silent, because both
    # halves individually looked fine.
    if user_id:
        claims["sub"] = str(user_id)

    return jwt.encode(claims, _secret(), algorithm=ALGORITHM)


def decode_session_token(token: str | None, *, grace: timedelta = GRACE) -> SessionClaims | None:
    """Verify a token and return its claims, or None.

    None for every failure -- absent, malformed, wrong signature, wrong
    algorithm, wrong token type, expired past the grace window. The caller turns
    that into a 401 and must never be told which failure it was: the difference
    is only useful to somebody probing.

    `grace` defaults to `auth.GRACE` for the same reason it exists there. A turn
    can take a minute, and a session expiring mid-reply is our problem to
    absorb, not an error to show somebody halfway through an answer.
    """
    if not token:
        return None
    try:
        claims = jwt.decode(
            token,
            _secret(),
            algorithms=[ALGORITHM],
            leeway=grace,
            options={"require": ["typ", "sid", "did", "per", "band", "acc", "exp"]},
        )
    except Exception:
        return None

    if claims.get("typ") != TOKEN_TYPE:
        # An account token presented where a session token belongs. Refused
        # rather than coerced: it carries no band, so coercing it would mean
        # inventing one, and inventing an age band is the single worst thing
        # this file could do.
        return None

    user_id = claims.get("sub")
    return SessionClaims(
        session_id=str(claims["sid"]),
        user_id=str(user_id) if user_id else None,
        device_id=str(claims["did"]),
        persona=str(claims["per"]),
        age_band=str(claims["band"]),
        account_status=str(claims["acc"]),
        locale=str(claims.get("loc") or "en"),
    )


#: Body fields a client is never allowed to set, because each of them is an
#: identity claim the server mints.
#:
#: Checked by `hydrate` against the raw request body. Named here so the list has
#: one home: the API layer, the test suite and the eval harness all assert
#: against the same tuple, and adding a claim to the token without adding it
#: here would leave a new field silently spoofable.
CLIENT_FORBIDDEN_FIELDS: tuple[str, ...] = (
    "persona",
    "age_band",
    "account_status",
    "user_id",
    "session_id",
    "device_id",
    "allowed_agents",
)
