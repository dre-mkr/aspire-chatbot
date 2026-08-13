"""What every node is given, so that no node has to work it out."""

from __future__ import annotations

from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: The programme's own timezone.
ST_KITTS: Final[ZoneInfo] = ZoneInfo("America/St_Kitts")

#: How many turns of history go into a prompt verbatim.
RECENT_TURNS = 6


def now_local() -> datetime:
    """The current moment in St Kitts."""
    return datetime.now(ST_KITTS)


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
    #: `users.display_name`, or None for an anonymous visitor.
    display_name: str | None = None

    # ── conversation ─────────────────────────────────────────────────────────
    recent_turns: list[Turn] = Field(default_factory=list, max_length=RECENT_TURNS)
    #: The rolling summary `persist` has been writing all along.
    running_summary: str = ""

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
