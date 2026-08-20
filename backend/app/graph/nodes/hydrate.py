"""The first node."""

from __future__ import annotations

import logging
from typing import Any

from app.graph.identity import CLIENT_FORBIDDEN_FIELDS, SessionClaims, decode_session_token
from app.graph.state import RESET, AspireState

logger = logging.getLogger(__name__)


class Unauthenticated(Exception):
    """No usable session token."""


def spoof_attempt(body: dict[str, Any] | None) -> list[str]:
    """Which identity fields the request body tried to set."""
    if not body:
        return []
    return [field for field in CLIENT_FORBIDDEN_FIELDS if field in body]


def identity_from(claims: SessionClaims) -> dict[str, Any]:
    """The identity fields, as a state update."""
    return {
        "session_id": claims.session_id,
        "user_id": claims.user_id,
        "identity_proven": claims.identity_proven,
        "device_id": claims.device_id,
        "persona": claims.persona,
        "age_band": claims.age_band,
        "account_status": claims.account_status,
        "locale": claims.locale,
        # Speech defaults on for the two bands where reading is the barrier.
        "speak": claims.age_band in ("5-8", "9-12"),
    }


#: Request fields carrying something the child DID rather than said.
CONTINUATION_FIELDS: tuple[str, ...] = ("widget_interaction", "game_result")


def make_hydrate(token: str | None, body: dict[str, Any] | None = None):
    """Build the node for one request."""

    def hydrate(state: AspireState) -> dict[str, Any]:
        claims = decode_session_token(token)
        if claims is None:
            raise Unauthenticated("A valid session token is required.")

        ignored = spoof_attempt(body)
        if ignored:
            # WARNING rather than INFO: this is the line an operator alerts on.
            logger.warning(
                "Request body for session %s tried to set identity field(s) %s; "
                "ignored. Identity comes from the session token only.",
                claims.session_id,
                ", ".join(ignored),
            )

        update: dict[str, Any] = dict(identity_from(claims))
        # Cleared on every turn.
        update["quick_replies"] = []
        update["safety_flags"] = {}
        update["halt_reason"] = None
        update["retrieved"] = []
        update["qa_related"] = []
        update["groundedness"] = 0.0
        # RESET rather than `[]`: these accumulate, so `[]` would leave last turn's values in place.
        update["ui_directives"] = RESET
        update["citations"] = RESET
        if ignored:
            # Carried into state as well as logged, so `persist` can record it against the session.
            update["safety_flags"] = {"identity_spoof_attempt": ignored}

        # An answer-shaping request from the reader, not a claim about who they
        # are, so it rides in the body rather than in the signed token. Written
        # every turn -- the reader can turn it off between two questions.
        update["simple_mode"] = bool((body or {}).get("simple_mode"))

        # Same shape, same reason. Absent means Automatic: every client that
        # predates the selector, and every deep link without the parameter,
        # keeps the behaviour it already had.
        raw_auto = (body or {}).get("auto_language")
        update["auto_language"] = True if raw_auto is None else bool(raw_auto)

        # ── the turn's inputs, put back after the clear ──
        # A widget interaction or a game result arrives as a body field, not as a message.
        for field in CONTINUATION_FIELDS:
            value = (body or {}).get(f"__{field}")
            if value:
                update["safety_flags"] = {**update["safety_flags"], field: value}

        return update

    return hydrate
