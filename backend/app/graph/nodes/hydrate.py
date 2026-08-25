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
    """The identity fields, as a state update.

    THE PERSONA IS MIGRATED HERE, ONCE, and this is the only place it can be.

    `TOKEN_TTL` is seven days, so for a week after `kaleb.9-12.md` took the 9-12
    band there are live sessions whose token still says `stella` at that band.
    `allowed_agents` migrates them for routing and always did -- but it migrates
    a local copy, and state kept the raw claim. Everything downstream reads
    state.

    Measured on the tree, 23 August 2026, for a legacy `stella/9-12` token:

      agents    correct -- access normalises its own copy
      CARD      Skye's 5-8 card, to a reader in secondary school. This is the
                exact defect the split existed to fix, arriving through the one
                door nobody had shut
      GAMES     Skye's 5-8 bank -- MONEY, COIN, SAVE -- not Kaleb's
      VOICE     resolved as `stella`, marked native, and PLAYED. Kaleb's whole
                never-borrow rule was bypassed by the token saying stella
      identity  correct, but only because it had been patched separately

    Patching each site would have meant six fixes and a seventh waiting for the
    next reader of `state["persona"]`. Migrating at the seam means state is
    never wrong, and `normalise_persona_band` is idempotent, so access doing it
    again downstream costs nothing.
    """
    from app.domain import normalise_persona_band

    return {
        "session_id": claims.session_id,
        "user_id": claims.user_id,
        "identity_proven": claims.identity_proven,
        "device_id": claims.device_id,
        "persona": normalise_persona_band(claims.persona, claims.age_band),
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
        # Lives for exactly the turn that tells the story. Left set, every
        # later question would be answered as another story.
        update["story_topic"] = None
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
        # The personality overlay: a preference like simple_mode, validated
        # against the known set so the body cannot inject prompt text.
        from app.prompting.overlays import KNOWN_OVERLAYS

        raw_overlay = str((body or {}).get("overlay") or "").strip().lower()
        update["overlay"] = raw_overlay if raw_overlay in KNOWN_OVERLAYS else ""

        # Guest rotation: a signed-out reader who chose nothing meets a little
        # personality anyway -- Classic, the Limer or the Hustler, decided by
        # their session id so one conversation keeps one flavour throughout.
        if not update["overlay"] and claims.persona == "guest":
            import zlib

            rotation = ("", "limer", "hustler")
            # crc32, not hash(): hash() is salted per process, and a flavour
            # that changed on a server restart would read as a mood swing.
            stable = zlib.crc32(claims.session_id.encode())
            update["overlay"] = rotation[stable % 3]

        # Same shape, same reason. Absent means Automatic: every client that
        # predates the selector, and every deep link without the parameter,
        # keeps the behaviour it already had.
        raw_auto = (body or {}).get("auto_language")
        update["auto_language"] = True if raw_auto is None else bool(raw_auto)

        # THE PINNED LANGUAGE ITSELF, which nothing read until now.
        #
        # `locale` above comes from the signed token, and the selector's choice
        # arrives in the body -- so pressing Espanol sent `auto_language: false`,
        # which switched the detector OFF, alongside a `language` field that no
        # code path consumed. The conversation therefore stayed in English AND
        # stopped following the reader: strictly worse than never touching the
        # control. The greeting changed because that is client-side, which is
        # exactly why the two looked inconsistent.
        #
        # Only when the reader has pinned. Automatic sessions keep taking their
        # locale from the token and letting `detect_language` move it, which is
        # the behaviour every client that predates the selector relies on.
        if not update["auto_language"]:
            pinned = (body or {}).get("language")
            if pinned in ("en", "es", "fr"):
                update["locale"] = pinned
            elif pinned is not None:
                logger.warning(
                    "session %s asked for locale %r, which the product has no "
                    "copy for; keeping %s",
                    claims.session_id,
                    pinned,
                    update.get("locale"),
                )

        # ── the turn's inputs, put back after the clear ──
        # A widget interaction or a game result arrives as a body field, not as a message.
        for field in CONTINUATION_FIELDS:
            value = (body or {}).get(f"__{field}")
            if value:
                update["safety_flags"] = {**update["safety_flags"], field: value}

        return update

    return hydrate
