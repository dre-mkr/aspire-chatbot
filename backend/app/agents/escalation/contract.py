"""Five reasons a turn may reach a person, and the rule that one is required."""

from __future__ import annotations

from enum import Enum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EscalationReason(str, Enum):
    """Why a person is being fetched."""

    USER_REQUESTED_HUMAN = "user_requested_human"
    SAFETY_OR_DISTRESS = "safety_or_distress"
    ACCOUNT_ACTION_NEEDED = "account_action_needed"
    REPEATED_FAILURE = "repeated_failure"
    COMPLAINT = "complaint"


class SafetyKind(str, Enum):
    """The two shapes of `SAFETY_OR_DISTRESS`, kept apart for triage."""

    SAFEGUARDING = "safeguarding"
    DISTRESS = "distress"


#: Reasons that must reach a person on the turn they are raised.
IMMEDIATE: Final[frozenset[EscalationReason]] = frozenset(
    {
        EscalationReason.USER_REQUESTED_HUMAN,
        EscalationReason.SAFETY_OR_DISTRESS,
        EscalationReason.ACCOUNT_ACTION_NEEDED,
        EscalationReason.COMPLAINT,
    }
)

#: How urgently each reason should be seen, and which queue it lands in.
TRIAGE: Final[dict[EscalationReason, tuple[str, str]]] = {
    EscalationReason.USER_REQUESTED_HUMAN: ("normal", "general"),
    EscalationReason.ACCOUNT_ACTION_NEEDED: ("high", "servicing"),
    EscalationReason.REPEATED_FAILURE: ("normal", "comprehension"),
    EscalationReason.COMPLAINT: ("high", "complaint"),
}

#: The safety rows, by kind.
SAFETY_TRIAGE: Final[dict[SafetyKind, tuple[str, str]]] = {
    SafetyKind.SAFEGUARDING: ("high", "safeguarding"),
    SafetyKind.DISTRESS: ("high", "wellbeing"),
}

#: Three failed clarifications in a row is an escalation trigger in its own right.
CLARIFICATION_LIMIT = 3

#: Longest summary a ticket carries.
SUMMARY_MAX = 600


class EscalationRequest(BaseModel):
    """A permitted escalation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reason: EscalationReason
    #: What a member of staff needs to know, already PII-redacted by the caller.
    summary: str = Field(min_length=1, max_length=SUMMARY_MAX)
    #: Only meaningful for `SAFETY_OR_DISTRESS`.
    safety_kind: SafetyKind | None = None
    #: The intent the counter was tracking, when this came from `REPEATED_FAILURE`.
    intent: str | None = None

    @model_validator(mode="after")
    def _safety_kind_is_coherent(self) -> "EscalationRequest":
        """A safety escalation always resolves to a kind; nothing else may carry one."""
        if self.reason is EscalationReason.SAFETY_OR_DISTRESS:
            if self.safety_kind is None:
                object.__setattr__(self, "safety_kind", SafetyKind.SAFEGUARDING)
        elif self.safety_kind is not None:
            raise ValueError("safety_kind is only valid for SAFETY_OR_DISTRESS")
        return self

    @property
    def is_immediate(self) -> bool:
        """Whether this bypasses the repeated-failure counter entirely."""
        return self.reason in IMMEDIATE

    def triage(self) -> tuple[str, str]:
        """`(priority, category)` for this request."""
        if self.reason is EscalationReason.SAFETY_OR_DISTRESS:
            kind = self.safety_kind or SafetyKind.SAFEGUARDING
            return SAFETY_TRIAGE[kind]
        return TRIAGE[self.reason]


#: The old string reasons, mapped to the new enum where one exists.
LEGACY_REASONS: Final[dict[str, EscalationReason | None]] = {
    "safeguarding": EscalationReason.SAFETY_OR_DISTRESS,
    "distress": EscalationReason.SAFETY_OR_DISTRESS,
    "user_request": EscalationReason.USER_REQUESTED_HUMAN,
    "complaint": EscalationReason.COMPLAINT,
    "repeated_clarification": EscalationReason.REPEATED_FAILURE,
    "no_context": None,
    "below_relevance_floor": None,
    "unattributed_figure": None,
    "uncited_policy_claim": None,
}


def from_legacy(reason: str | None) -> EscalationReason | None:
    """Translate a pre-contract reason string, or None if it is no longer one."""
    if not reason:
        return None
    return LEGACY_REASONS.get(reason)
