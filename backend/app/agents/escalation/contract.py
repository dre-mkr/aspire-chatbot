"""Five reasons a turn may reach a person, and the rule that one is required.

Before this module, "escalate" was a string. Nine of them
(`agents/escalate/graph.py:73-84`), four of which were retrieval failures --
`no_context`, `below_relevance_floor`, `unattributed_figure`,
`uncited_policy_claim`. Those four accounted for 23 of 58 live tickets, which is
the measurement behind "the escalation agent fires far too readily": two in five
handoffs were a cosine score, not a person asking for a person.

The enum below has no member for any of them, and that absence is the design.
A retrieval failure is not a reason to fetch a human; it is a reason to say what
we do know and offer something answerable. `GRACEFUL_DECLINE` (see
`agents/qa/nodes.py`) is where those four went.

## Immediate versus earned

    USER_REQUESTED_HUMAN   immediate -- they asked; asking again is not required
    SAFETY_OR_DISTRESS     immediate -- and never gated by anything, see below
    COMPLAINT              immediate -- a complaint routed to a FAQ is a worse complaint
    ACCOUNT_ACTION_NEEDED  immediate -- the assistant cannot move money
    REPEATED_FAILURE       earned    -- three unresolved turns on one intent

`IMMEDIATE` is the set that must never be counted, delayed, thresholded or
retried. `REPEATED_FAILURE` is the only member a counter may produce.

## Why `SAFETY_OR_DISTRESS` keeps a sub-kind

The specification asks for one member. The system it replaces distinguished
`safeguarding` from `distress`, and the distinction is load-bearing rather than
cosmetic: both are high priority, but they route to different queues
(`safeguarding` vs `wellbeing`) and only the safeguarding category pages
somebody. Collapsing them into one enum member and throwing the distinction away
would quietly downgrade child-protection cases into a wellbeing inbox.

So the member is one and `SafetyKind` rides alongside it, defaulting to the more
urgent of the two when unspecified. Failing towards `SAFEGUARDING` is the
correct direction to be wrong in.

## No reason, no escalation

`EscalationRequest` requires both fields and forbids extras. There is no
constructor that produces a valid request without a reason, so "escalate with no
stated cause" is not a thing a caller can express -- which is the point, and is
why this is a model rather than a convention.
"""

from __future__ import annotations

from enum import Enum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EscalationReason(str, Enum):
    """Why a person is being fetched. `str` so it serialises into a ticket as
    itself rather than as `EscalationReason.COMPLAINT`."""

    USER_REQUESTED_HUMAN = "user_requested_human"
    SAFETY_OR_DISTRESS = "safety_or_distress"
    ACCOUNT_ACTION_NEEDED = "account_action_needed"
    REPEATED_FAILURE = "repeated_failure"
    COMPLAINT = "complaint"


class SafetyKind(str, Enum):
    """The two shapes of `SAFETY_OR_DISTRESS`, kept apart for triage.

    `SAFEGUARDING` is a child at risk. `DISTRESS` is a child who is upset. Both
    are urgent; only the first pages somebody and notifies a guardian record.
    """

    SAFEGUARDING = "safeguarding"
    DISTRESS = "distress"


#: Reasons that must reach a person on the turn they are raised.
#:
#: Read by the counter in `agents/escalation/counter.py`, which refuses to
#: increment for any of these -- a child asking for help does not have to ask
#: three times.
IMMEDIATE: Final[frozenset[EscalationReason]] = frozenset(
    {
        EscalationReason.USER_REQUESTED_HUMAN,
        EscalationReason.SAFETY_OR_DISTRESS,
        EscalationReason.ACCOUNT_ACTION_NEEDED,
        EscalationReason.COMPLAINT,
    }
)

#: How urgently each reason should be seen, and which queue it lands in.
#:
#: Preserves the priorities the string-keyed table carried
#: (`agents/escalate/graph.py:73-84`) so this is a re-typing rather than a
#: re-tuning. The safety row is resolved through `SafetyKind` instead.
TRIAGE: Final[dict[EscalationReason, tuple[str, str]]] = {
    EscalationReason.USER_REQUESTED_HUMAN: ("normal", "general"),
    EscalationReason.ACCOUNT_ACTION_NEEDED: ("high", "servicing"),
    EscalationReason.REPEATED_FAILURE: ("normal", "comprehension"),
    EscalationReason.COMPLAINT: ("high", "complaint"),
}

#: The safety rows, by kind. Not in `TRIAGE` because they are selected by
#: `SafetyKind` rather than by the reason, and because keeping them here makes
#: it obvious that both are high and neither is optional.
SAFETY_TRIAGE: Final[dict[SafetyKind, tuple[str, str]]] = {
    SafetyKind.SAFEGUARDING: ("high", "safeguarding"),
    SafetyKind.DISTRESS: ("high", "wellbeing"),
}

#: Longest summary a ticket carries. Staff read these in a queue; past a couple
#: of sentences they stop being read at all.
SUMMARY_MAX = 600


class EscalationRequest(BaseModel):
    """A permitted escalation. Constructing one is the only way to ask for a person.

    `extra="forbid"` and `frozen=True` for the same reason the widget schemas
    use them: a request that arrived with an unexpected field is a caller that
    thinks it is talking to a different contract, and a request that can be
    mutated after validation is a request whose validation means nothing.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    reason: EscalationReason
    #: What a member of staff needs to know, already PII-redacted by the caller.
    #: Required and non-empty: a ticket with no summary is a ticket somebody has
    #: to reopen the transcript to understand.
    summary: str = Field(min_length=1, max_length=SUMMARY_MAX)
    #: Only meaningful for `SAFETY_OR_DISTRESS`.
    safety_kind: SafetyKind | None = None
    #: The intent the counter was tracking, when this came from `REPEATED_FAILURE`.
    intent: str | None = None

    @model_validator(mode="after")
    def _safety_kind_is_coherent(self) -> "EscalationRequest":
        """A safety escalation always resolves to a kind; nothing else may carry one.

        The default is `SAFEGUARDING` rather than `DISTRESS`. A caller who
        detected a safety signal but did not say which kind has told us
        something is wrong and not what -- and the cost of treating an upset
        child as a safeguarding case is a queue misroute, while the cost of the
        reverse is the case that mattered sitting in a wellbeing inbox.
        """
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
#:
#: Exists for one turn of the migration: a checkpoint written before this change
#: carries `escalation_reason` as a bare string, and a conversation resumed
#: across the deploy must not crash on it. The four retrieval failures map to
#: None deliberately -- they are no longer escalations, and a resumed turn
#: carrying one should decline rather than fetch a person.
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
