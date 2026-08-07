"""What every node is given, so that no node has to work it out.

The diagnosis found seven fields being recomputed downstream of the graph that
already knew them, and `age_band` alone had three independent defaults --
`learn/graph.py:86` fell back to `"9-12"`, `teach.py:338` fell back to `"9-12"`
separately, and `teach.py:270` fell back to a 120-word cap when the band was
unrecognised. Three fallbacks for one value means three different answers to
"what band is this?" on a malformed token, in one turn.

`SessionContext` is built once, before routing, and read everywhere after.

## Identity comes from the token and only from the token

`persona`, `age_band`, `account_status` and `locale` are copied from claims that
`hydrate` already validated against the signed token. The request body is never
consulted: `hydrate` logs and discards body-supplied identity
(`graph/nodes/hydrate.py:122`), and this object is downstream of that, so there
is no path by which a client can set them here either.

## `open_application` carries no field values, and that is enforced by shape

`ApplicationRef` has three fields and none of them is a slot value. This is the
same rule the global constraints state as "checkpoints hold IDs and step
pointers only", expressed as a type rather than as a discipline -- there is no
`values` field to fill in, so a caller cannot put a date of birth here by being
careless. `extra="forbid"` closes the other direction.

That matters because `SessionContext` goes into graph state, and graph state is
checkpointed. FINDINGS.md F1 is exactly this failure in the registration draft,
where `_persist_state` copies `draft.values` wholesale; this object is built so
the same mistake cannot be made twice.

## Frozen

Built once per turn and read by a dozen nodes. A node that could mutate it would
be a node that changes what a later node believes about the reader, which is the
class of bug this whole object exists to remove.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: The programme's own timezone. Every `now` in a prompt is this one.
#:
#: A deadline question answered in UTC is answered wrong by four hours, and the
#: diagnosis found `current_datetime` absent from every prompt in the product --
#: so "is it too late to apply?" was being answered without knowing the date at
#: all.
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
    """A pointer to an application in progress. Never its contents.

    Three fields, all of them pointers. There is deliberately nowhere to put a
    name, a date of birth or a document reference -- see the module docstring on
    why that is a type and not a convention.
    """

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
    #: `users.display_name`, or None for an anonymous visitor. Present so an
    #: agent can use somebody's name without querying for it, which is the kind
    #: of one-off read that turns into an N+1 across a dozen nodes.
    display_name: str | None = None

    # ── conversation ─────────────────────────────────────────────────────────
    recent_turns: list[Turn] = Field(default_factory=list, max_length=RECENT_TURNS)
    #: The rolling summary `persist` has been writing all along. The diagnosis
    #: found it computed, redacted, checkpointed -- and read by no prompt.
    running_summary: str = ""

    # ── learning ─────────────────────────────────────────────────────────────
    #: `concept_id -> 0.0-1.0`. Normalised from the integer mastery scale so a
    #: reader of this object does not need to know what the ceiling is.
    mastery: dict[str, float] = Field(default_factory=dict)
    concepts_seen_today: list[str] = Field(default_factory=list)
    #: The last game played, by name. None when there is no durable record --
    #: see `resolver` on why this is thinner than the other learning fields.
    last_game: str | None = None

    # ── flows in progress ────────────────────────────────────────────────────
    open_application: ApplicationRef | None = None
    last_escalation: TicketRef | None = None

    # ── environment ──────────────────────────────────────────────────────────
    #: The corpus fingerprint already used in cache keys. Changes when the
    #: knowledge base is re-ingested, which is what makes it a version.
    kb_version: str = ""
    now: datetime = Field(default_factory=now_local)

    @field_validator("mastery")
    @classmethod
    def _mastery_is_a_fraction(cls, value: dict[str, float]) -> dict[str, float]:
        """0.0-1.0, enforced rather than documented.

        The field is annotated `float` and the docstring says 0.0-1.0, and
        neither of those stops a caller passing the raw integer scale -- which is
        exactly what happened the first time this object was built with an
        injected loader: `{"save": 3}` sailed through as `3.0` and
        `mastery_of("save") >= threshold` was true for every threshold.

        Rejecting is right rather than clamping. A caller handing over raw scores
        has a normalisation bug, and clamping 3 to 1.0 would produce the same
        wrong answer silently. `resolver._normalise_mastery` is the conversion.
        """
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
