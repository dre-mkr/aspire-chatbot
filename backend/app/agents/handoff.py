"""What one agent must hand the next, and the slot it may no longer ask for.

The diagnosis found the QA-to-registration handoff passing `active_agent` and
nothing else (`agents/qa/tools.py:308`), so the receiving agent began its slot
walk from the top with no knowledge of anything the reader had already said.

## `do_not_reask` is enforced in the loop, not in the prompt

This is the part worth being careful about. The instruction "do not ask for the
guardian's name again" placed in a system prompt is a request, and the slot loop
that picks the next question does not read prompts -- it reads `pick_slot`. So the
enforcement lives in `filter_slots` below, which is applied to the candidate list
BEFORE anything is chosen.

The difference is structural rather than stylistic: with the prompt approach an
agent that ignores the instruction asks again and the reader repeats themselves;
with this approach there is no code path that offers the slot, so the question
cannot be produced whether the model would have liked to or not.

## `facts_established` carries values, so it is not for PII

A handoff is passed in graph state, and graph state is checkpointed. The same
rule as everywhere else in this codebase applies -- `SLOT_SAFE` names the only
keys permitted, and `EscalationRequest`-style validation rejects the rest at
construction. A guardian's date of birth belongs in the registration tables
(Track R.2), never here.
"""

from __future__ import annotations

import logging
from typing import Any, Final, Iterable

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)

#: Key fragments that may never appear in `facts_established`.
#:
#: A denylist rather than an allowlist, and the choice is deliberate: an
#: allowlist of safe fact names would have to be extended every time an agent
#: learns something new, and the failure mode of forgetting is that a legitimate
#: fact is dropped silently. Here the failure mode of forgetting is loud -- a new
#: PII-shaped key raises at construction.
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
    """Required on every inter-agent transfer.

    `frozen` and `extra="forbid"` for the same reasons `EscalationRequest` is: a
    handoff that can be edited after validation is a handoff whose validation
    means nothing, and an unexpected field means the sender is talking to a
    different contract than the receiver.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    from_agent: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    #: The reader's intent, rewritten to stand alone. The receiving agent gets a
    #: question it can act on rather than "and what about her?", which is the
    #: same problem `qa.rewrite_query` solves for retrieval.
    user_intent: str = Field(min_length=1)
    #: What is already known. Non-PII only -- see `FORBIDDEN_FACT_KEYS`.
    facts_established: dict[str, Any] = Field(default_factory=dict)
    #: Slot paths the receiver must not ask for. Enforced by `filter_slots`.
    do_not_reask: list[str] = Field(default_factory=list)

    @field_validator("facts_established")
    @classmethod
    def _no_pii_in_facts(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Refuse a handoff carrying identity data.

        Checked on the KEY rather than the value, because a value check would be
        a PII detector and this is a schema. The keys are ours -- an agent writing
        `facts_established["guardian.date_of_birth"]` is making a mistake with a
        name we control, and naming it here is cheaper and more certain than
        inspecting what it holds.
        """
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
    """The candidate slots a receiving agent may still ask for.

    The enforcement point. Applied to the list BEFORE a slot is chosen, so a
    barred slot is not something the agent declines to ask about -- it is
    something the agent is never offered.

    Slots are matched on `.path`, which is what `register/schema.py` keys them
    by. Anything without a `path` is passed through untouched rather than
    dropped: this function's job is to remove named slots, not to filter
    arbitrary objects, and silently discarding something it did not understand
    would be a worse bug than the one it prevents.
    """
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
    """The handoff attached to this turn, or None.

    Stored under `safety_flags["handoff"]` as a plain dict so it survives the
    checkpoint's JSON round trip, and revalidated on the way out -- a dict that
    has been through a checkpoint has not been through the validator.
    """
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
