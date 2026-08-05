"""The first node. Turns a token into an identity, and refuses without one.

Three jobs, in order:

  1. Decode the signed session token. No token, or a bad one, is a 401 and the
     graph does not run.
  2. Write the identity fields into state -- from the token's claims and from
     nowhere else.
  3. Note, loudly, if the request body tried to set any of them.

Step 3 is the one worth reading twice.

## Why a spoofed field is logged and ignored rather than rejected

A request body carrying `persona: "aurora"` on a Stella token is one of two
things: a bug in a client that is merging its UI state into the payload, or
somebody testing whether the age band is client-controlled. Both are worth a log
line. Only the second is worth a 403, and we cannot tell them apart from here.

Rejecting outright would mean a client bug takes the product down for a child
mid-lesson. Silently ignoring means the attempt is invisible. So: ignore the
value, serve the turn from the token's claims, and emit a WARNING naming the
fields -- which is a signal an operator can alert on and a bug a developer can
find.

What is *never* done is merging. There is no branch in this file where a body
field reaches `state`. The whole class of "well, we take the body value if the
token doesn't have one" is absent, because "the token doesn't have one" is a
condition that must produce a 401 rather than a fallback.

## Checkpoint state

`hydrate` does not load the checkpoint itself. LangGraph does that, before any
node runs, from the `thread_id` in the invocation config -- so by the time this
node executes, prior state is already present and this node's job is to
OVERWRITE the identity fields with today's claims rather than to inherit
yesterday's. That matters: a child who has had a birthday, or a guardian whose
application was approved, must be routed on the token in front of us and not on
the band that was true last week.
"""

from __future__ import annotations

import logging
from typing import Any

from app.graph.identity import CLIENT_FORBIDDEN_FIELDS, SessionClaims, decode_session_token
from app.graph.state import RESET, AspireState

logger = logging.getLogger(__name__)


class Unauthenticated(Exception):
    """No usable session token. The API turns this into a 401.

    A distinct exception rather than a state flag, because there is no turn to
    serve: nothing downstream has an identity to be safe about, and a graph that
    continued would be a graph choosing an age band for somebody.
    """


def spoof_attempt(body: dict[str, Any] | None) -> list[str]:
    """Which identity fields the request body tried to set.

    Split out from the node so the API layer can check a body before building a
    state at all, and so the test suite can assert on the detection separately
    from the ignoring.
    """
    if not body:
        return []
    return [field for field in CLIENT_FORBIDDEN_FIELDS if field in body]


def identity_from(claims: SessionClaims) -> dict[str, Any]:
    """The identity fields, as a state update.

    Every one of them comes off `claims`. That is the entire contract of this
    module and it is short enough to verify by reading.
    """
    return {
        "session_id": claims.session_id,
        "user_id": claims.user_id,
        "device_id": claims.device_id,
        "persona": claims.persona,
        "age_band": claims.age_band,
        "account_status": claims.account_status,
        "locale": claims.locale,
        # Speech defaults on for the two bands where reading is the barrier.
        # A per-user preference overrides this later, in the client; the server
        # decides the default because the server is what knows the band.
        "speak": claims.age_band in ("5-8", "9-12"),
    }


#: Request fields carrying something the child DID rather than said. Read off
#: the body as `__widget_interaction` / `__game_result` and placed on
#: `safety_flags`, where `classify` routes on them without a model call.
CONTINUATION_FIELDS: tuple[str, ...] = ("widget_interaction", "game_result")


def make_hydrate(token: str | None, body: dict[str, Any] | None = None):
    """Build the node for one request.

    A factory rather than a plain node because the token is per-request and a
    LangGraph node signature is `(state) -> update`. Passing the token through
    `configurable` was the alternative and is worse: `configurable` is visible
    to tools, and a bearer token visible to tools is a bearer token one prompt
    injection away from being exfiltrated.
    """

    def hydrate(state: AspireState) -> dict[str, Any]:
        claims = decode_session_token(token)
        if claims is None:
            raise Unauthenticated("A valid session token is required.")

        ignored = spoof_attempt(body)
        if ignored:
            # WARNING rather than INFO: this is the line an operator alerts on.
            # It names the fields and the session, and deliberately not the
            # values -- logging the attempted persona would put attacker-chosen
            # text in the log, and logs get read by tools.
            logger.warning(
                "Request body for session %s tried to set identity field(s) %s; "
                "ignored. Identity comes from the session token only.",
                claims.session_id,
                ", ".join(ignored),
            )

        update: dict[str, Any] = dict(identity_from(claims))
        # Cleared on every turn. These are per-turn outputs, and a checkpoint
        # restores the previous turn's values -- so without this, last turn's
        # quick replies render under this turn's answer and last turn's
        # citations are attributed to it.
        update["quick_replies"] = []
        update["safety_flags"] = {}
        update["halt_reason"] = None
        update["retrieved"] = []
        update["groundedness"] = 0.0
        # RESET rather than `[]`: both of these accumulate, so an empty list
        # would append nothing and last turn's chips and references would
        # render under this turn's answer. See `state.RESET`.
        update["ui_directives"] = RESET
        update["citations"] = RESET
        if ignored:
            # Carried into state as well as logged, so `persist` can record it
            # against the session and the admin queue can see a pattern rather
            # than one line in a log file nobody is tailing.
            update["safety_flags"] = {"identity_spoof_attempt": ignored}

        # ── the turn's INPUTS, put back after the clear ─────────────────────
        #
        # A widget interaction and a game result are things the child DID, not
        # things they said, so they arrive on their own request field rather
        # than in `messages` -- putting them in the transcript would have the
        # model read `widget_interaction {...}` back as dialogue forever.
        #
        # They have to be applied HERE, below the reset above, and that is the
        # whole reason this block exists. The transport used to pass them in the
        # graph's initial state, which `safety_flags = {}` then wiped before
        # `classify` ever saw them. Measured: an interaction turn had nothing to
        # route on and escalated -- the child got a ticket for using the widget
        # they had just been handed.
        for field in CONTINUATION_FIELDS:
            value = (body or {}).get(f"__{field}")
            if value:
                update["safety_flags"] = {**update["safety_flags"], field: value}

        return update

    return hydrate
