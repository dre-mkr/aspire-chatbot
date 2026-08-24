"""What every node is given, so that no node has to work it out."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: The programme's own timezone.
ST_KITTS: Final[ZoneInfo] = ZoneInfo("America/St_Kitts")

#: How many turns of history go into a prompt verbatim.
RECENT_TURNS = 6

#: What every ASPIRE reference is prefixed with, conversation and ticket alike.
REFERENCE_PREFIX: Final[str] = "ASP-"

#: How many digits a conversation reference carries.
#:
#: Five, which is what the persona cards ask a reader to quote and short enough
#: to be read down a phone line by a child's grandmother. Deliberately a
#: different length from the two other things wearing this prefix: knowledge-base
#: rows are `ASP-001` and escalation tickets are `ASP-` plus eight hex, so the
#: three are told apart by shape rather than by context.
REFERENCE_DIGITS: Final[int] = 5


def now_local() -> datetime:
    """The current moment in St Kitts."""
    return datetime.now(ST_KITTS)


def conversation_reference(session_id: str | None) -> str:
    """The five-digit reference a reader is asked to quote, for one conversation.

    Derived from the session id rather than drawn at random, so it is the same
    on every turn of a conversation -- a reader who is given it, hangs up and
    comes back must not be given a different one -- and so the ASPIRE team can
    recompute it from a session id instead of needing a column to store it in.

    Not an account number and not a secret: it identifies a conversation, and
    the cards say so. Empty when there is no session, which the prompt layer
    renders as a phrase rather than a dangling prefix.
    """
    if not session_id:
        return ""
    digest = hashlib.blake2s(session_id.encode("utf-8"), digest_size=8).digest()
    ceiling = 10**REFERENCE_DIGITS
    return f"{REFERENCE_PREFIX}{int.from_bytes(digest, 'big') % ceiling:0{REFERENCE_DIGITS}d}"


class Turn(BaseModel):
    """One verbatim exchange line."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str
    text: str


class ApplicationRef(BaseModel):
    """A pointer to an application in progress."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    application_id: str
    #: Which authored step the flow is on, by name, not the question text.
    current_step: str | None = None
    #: Which child in a multi-child application. An index, not an identity.
    active_child_index: int = 0


class TicketRef(BaseModel):
    """A pointer to the last time this session reached a person."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ticket_id: str
    reason: str
    opened_at: datetime | None = None


class SessionContext(BaseModel):
    """Everything a node might need about this reader and this conversation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # ── identity: from the signed token, never the body ──────────────────────
    persona: str
    age_band: str
    locale: str
    account_status: str
    #: The reader's chosen personality overlay, or "". See prompting/overlays.
    overlay: str = ""
    #: `users.display_name`, or None for an anonymous visitor.
    display_name: str | None = None

    # ── conversation ─────────────────────────────────────────────────────────
    recent_turns: list[Turn] = Field(default_factory=list, max_length=RECENT_TURNS)
    #: The rolling summary `persist` has been writing all along.
    running_summary: str = ""
    #: `ASP-#####`, the reference the persona cards ask the reader to quote.
    #:
    #: On the context rather than read from the state inside the builder, because
    #: it has to be identical on every turn of a session -- it sits in the
    #: cacheable prefix, and a value that moved would break the breakpoint once
    #: per turn as well as handing the reader a new reference each time.
    conversation_ref: str = ""

    # ── learning ──
    #: `concept_id -> 0.0-1.0`.
    mastery: dict[str, float] = Field(default_factory=dict)
    concepts_seen_today: list[str] = Field(default_factory=list)
    #: The last game played, by name.
    last_game: str | None = None

    # ── flows in progress ────────────────────────────────────────────────────
    open_application: ApplicationRef | None = None
    last_escalation: TicketRef | None = None

    # ── environment ──
    #: The corpus fingerprint from `app.cache`.
    kb_version: str = ""
    now: datetime = Field(default_factory=now_local)

    @field_validator("mastery")
    @classmethod
    def _mastery_is_a_fraction(cls, value: dict[str, float]) -> dict[str, float]:
        """0.0-1.0, enforced rather than documented."""
        for concept, score in value.items():
            if not 0.0 <= score <= 1.0:
                raise ValueError(
                    f"mastery[{concept!r}] is {score}, outside 0.0-1.0 -- pass the "
                    "normalised fraction, not the raw score (see "
                    "resolver._normalise_mastery)"
                )
        return value

    def mastery_of(self, concept_id: str) -> float:
        """This learner's mastery of one concept, or 0.0 if untouched."""
        return self.mastery.get(concept_id, 0.0)

    @property
    def is_child(self) -> bool:
        return self.age_band in ("5-8", "9-12")
