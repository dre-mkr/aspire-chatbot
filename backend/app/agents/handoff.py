"""What one agent must hand the next, and the slot it may no longer ask for."""

from __future__ import annotations

import logging
from typing import Any, Final, Iterable

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)

#: Key fragments that may never appear in `facts_established`.
FORBIDDEN_FACT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "national_id",
        "nationalid",
        "date_of_birth",
        "dob",
        "birth_certificate",
        "passport",
        "full_name",
        "surname",
        "address",
        "address_line1",
        "address_line2",
        "phone",
        "email",
        "document",
        "upload",
    }
)


class Handoff(BaseModel):
    """Required on every inter-agent transfer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    from_agent: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    #: The reader's intent, rewritten to stand alone.
    user_intent: str = Field(min_length=1)
    #: What is already known. Non-PII only -- see `FORBIDDEN_FACT_KEYS`.
    facts_established: dict[str, Any] = Field(default_factory=dict)
    #: Slot paths the receiver must not ask for. Enforced by `filter_slots`.
    do_not_reask: list[str] = Field(default_factory=list)

    @field_validator("facts_established")
    @classmethod
    def _no_pii_in_facts(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Refuse a handoff carrying identity data."""
        for key in value:
            fragment = key.lower().replace("-", "_").split(".")[-1]
            if fragment in FORBIDDEN_FACT_KEYS:
                raise ValueError(
                    f"facts_established[{key!r}] looks like PII. A handoff is "
                    "checkpointed; collected values belong in the registration "
                    "tables, not in graph state."
                )
        return value

    def forbids(self, slot_path: str) -> bool:
        """Whether the receiver is barred from asking for this slot."""
        return slot_path in set(self.do_not_reask)


def filter_slots(candidates: Iterable[Any], handoff: Handoff | None) -> list[Any]:
    """The candidate slots a receiving agent may still ask for."""
    if handoff is None or not handoff.do_not_reask:
        return list(candidates)

    barred = set(handoff.do_not_reask)
    kept: list[Any] = []
    for candidate in candidates:
        path = getattr(candidate, "path", None)
        if path is not None and path in barred:
            logger.info(
                "Slot %s withheld: %s established it before handing over.",
                path,
                handoff.from_agent,
            )
            continue
        kept.append(candidate)
    return kept


def from_state(state: Any) -> Handoff | None:
    """The handoff attached to this turn, or None."""
    raw = (state.get("safety_flags") or {}).get("handoff")
    if not isinstance(raw, dict):
        return None
    try:
        return Handoff(**raw)
    except Exception:
        logger.warning("Discarding an unusable handoff payload.", exc_info=True)
        return None


def to_state(handoff: Handoff, state: Any) -> dict[str, Any]:
    """The state update that attaches `handoff` to the turn."""
    return {
        "safety_flags": {
            **(state.get("safety_flags") or {}),
            "handoff": handoff.model_dump(mode="json"),
        }
    }
