"""The escalation contract: a reason is required, and four old reasons are gone.

The measurement this exists to change: 23 of 58 live tickets were retrieval
failures -- `no_context`, `below_relevance_floor`, `unattributed_figure`,
`uncited_policy_claim`. None of the four has a member in the new enum, and
`from_legacy` maps each to None. That is the whole point of the type.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agents.escalation.contract import (
    IMMEDIATE,
    EscalationReason,
    EscalationRequest,
    SafetyKind,
    from_legacy,
)


class TestAReasonIsRequired:
    def test_there_is_no_way_to_ask_without_one(self):
        with pytest.raises(ValidationError):
            EscalationRequest(summary="something went wrong")  # type: ignore[call-arg]

    def test_an_empty_summary_is_refused(self):
        """A ticket with no summary is one somebody must reopen the transcript
        to understand."""
        with pytest.raises(ValidationError):
            EscalationRequest(reason=EscalationReason.COMPLAINT, summary="   ".strip())

    def test_an_unknown_reason_is_refused(self):
        with pytest.raises(ValidationError):
            EscalationRequest(reason="because_i_said_so", summary="x")  # type: ignore[arg-type]

    def test_extras_are_refused(self):
        with pytest.raises(ValidationError):
            EscalationRequest(
                reason=EscalationReason.COMPLAINT, summary="x", priority="high"
            )  # type: ignore[call-arg]

    def test_a_validated_request_cannot_be_mutated(self):
        request = EscalationRequest(reason=EscalationReason.COMPLAINT, summary="x")
        with pytest.raises(ValidationError):
            request.reason = EscalationReason.USER_REQUESTED_HUMAN  # type: ignore[misc]


class TestTheEnumHasExactlyFiveMembers:
    def test_membership(self):
        assert {member.value for member in EscalationReason} == {
            "user_requested_human",
            "safety_or_distress",
            "account_action_needed",
            "repeated_failure",
            "complaint",
        }

    @pytest.mark.parametrize(
        "retrieval_failure",
        ["no_context", "below_relevance_floor", "unattributed_figure", "uncited_policy_claim"],
    )
    def test_no_retrieval_failure_is_an_escalation_reason(self, retrieval_failure):
        """The four that produced 23 of 58 tickets. They become declines."""
        assert from_legacy(retrieval_failure) is None
        assert retrieval_failure not in {member.value for member in EscalationReason}


class TestImmediacy:
    @pytest.mark.parametrize(
        "reason",
        [
            EscalationReason.USER_REQUESTED_HUMAN,
            EscalationReason.SAFETY_OR_DISTRESS,
            EscalationReason.ACCOUNT_ACTION_NEEDED,
            EscalationReason.COMPLAINT,
        ],
    )
    def test_these_never_wait_for_a_counter(self, reason):
        kind = (
            SafetyKind.DISTRESS
            if reason is EscalationReason.SAFETY_OR_DISTRESS
            else None
        )
        assert EscalationRequest(reason=reason, summary="x", safety_kind=kind).is_immediate

    def test_repeated_failure_is_the_only_earned_one(self):
        request = EscalationRequest(reason=EscalationReason.REPEATED_FAILURE, summary="x")
        assert not request.is_immediate
        assert IMMEDIATE == set(EscalationReason) - {EscalationReason.REPEATED_FAILURE}


class TestSafetyKeepsItsSubKind:
    def test_safeguarding_and_distress_triage_differently(self):
        """Both high, different queues. Only safeguarding pages somebody, so
        collapsing them would downgrade child protection into a wellbeing inbox.
        """
        safeguarding = EscalationRequest(
            reason=EscalationReason.SAFETY_OR_DISTRESS,
            summary="x",
            safety_kind=SafetyKind.SAFEGUARDING,
        )
        distress = EscalationRequest(
            reason=EscalationReason.SAFETY_OR_DISTRESS,
            summary="x",
            safety_kind=SafetyKind.DISTRESS,
        )
        assert safeguarding.triage() == ("high", "safeguarding")
        assert distress.triage() == ("high", "wellbeing")

    def test_an_unspecified_kind_fails_towards_safeguarding(self):
        """A caller that detected a safety signal but not which kind has told us
        something is wrong and not what. Misrouting an upset child to the
        safeguarding queue is recoverable; the reverse is not."""
        request = EscalationRequest(reason=EscalationReason.SAFETY_OR_DISTRESS, summary="x")
        assert request.safety_kind is SafetyKind.SAFEGUARDING
        assert request.triage() == ("high", "safeguarding")

    def test_nothing_else_may_carry_a_safety_kind(self):
        with pytest.raises(ValidationError):
            EscalationRequest(
                reason=EscalationReason.REPEATED_FAILURE,
                summary="x",
                safety_kind=SafetyKind.DISTRESS,
            )

    def test_every_reason_triages(self):
        """No reason may fall through to a default, because a default is how a
        complaint ends up in the general queue."""
        for reason in EscalationReason:
            kind = (
                SafetyKind.DISTRESS
                if reason is EscalationReason.SAFETY_OR_DISTRESS
                else None
            )
            priority, category = EscalationRequest(
                reason=reason, summary="x", safety_kind=kind
            ).triage()
            assert priority in ("high", "normal", "low")
            assert category


class TestLegacyMigration:
    """A conversation resumed across the deploy carries a bare string."""

    @pytest.mark.parametrize(
        ("old", "new"),
        [
            ("safeguarding", EscalationReason.SAFETY_OR_DISTRESS),
            ("distress", EscalationReason.SAFETY_OR_DISTRESS),
            ("user_request", EscalationReason.USER_REQUESTED_HUMAN),
            ("complaint", EscalationReason.COMPLAINT),
            ("repeated_clarification", EscalationReason.REPEATED_FAILURE),
        ],
    )
    def test_reasons_that_survive(self, old, new):
        assert from_legacy(old) is new

    def test_none_and_unknown_are_not_escalations(self):
        assert from_legacy(None) is None
        assert from_legacy("") is None
        assert from_legacy("something_invented") is None
