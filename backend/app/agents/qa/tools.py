"""The Q&A agent's tools."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from langgraph.types import Command

from app.schemas.directives import ChartDirective, ChartSeries, directive_payload
from app.widgets.formulas import registry

logger = logging.getLogger(__name__)


# ── eligibility ──────────────────────────────────────────────────────────────

#: The programme's age window.
MIN_AGE = 5
MAX_AGE = 18


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    eligible: bool
    #: Every criterion, with its verdict.
    criteria: dict[str, bool]
    reasons: list[str]
    age: int | None = None


def _age_on(dob: date, on: date) -> int:
    """Completed years. The birthday-not-yet-had case is the one that bites."""
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def check_eligibility(
    dob: date,
    residency: str,
    guardian_status: str,
    *,
    on: date | None = None,
) -> EligibilityResult:
    """Whether this child qualifies."""
    today = on or date.today()
    age = _age_on(dob, today)

    criteria = {
        "age_in_range": MIN_AGE <= age <= MAX_AGE,
        "resident": residency.strip().lower() in {"citizen", "resident", "national"},
        "has_guardian": guardian_status.strip().lower()
        in {"parent", "guardian", "legal_guardian", "caregiver"},
    }

    reasons: list[str] = []
    if age < MIN_AGE:
        reasons.append(
            f"Not yet -- the programme starts at {MIN_AGE}, and this child is {age}."
        )
    elif age > MAX_AGE:
        reasons.append(f"Over {MAX_AGE}: the programme is for children up to {MAX_AGE}.")
    if not criteria["resident"]:
        reasons.append("Residency or citizenship has not been established.")
    if not criteria["has_guardian"]:
        reasons.append("A parent or legal guardian must open the account.")

    return EligibilityResult(
        eligible=all(criteria.values()),
        criteria=criteria,
        reasons=reasons,
        age=age,
    )


# ── projections ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Projection:
    """A savings projection, plus the chart directive that draws it."""

    final_cents: int
    contributed_cents: int
    earned_cents: int
    display: str
    #: Year-end balances, in cents.
    series: list[int]
    directive: dict[str, Any]


def project_savings(
    principal: int, monthly: int, rate: float, years: int
) -> Projection:
    """What regular saving becomes, year by year."""
    series: list[int] = []
    for year in range(1, max(1, years) + 1):
        step = registry.compound_interest(principal, monthly, rate, year, 12)
        series.append(int(step.value))

    final = registry.compound_interest(principal, monthly, rate, max(1, years), 12)
    directive = ChartDirective(
        kind="line",
        series=[
            ChartSeries(
                label="What you would have",
                points=[cents / 100 for cents in series],
            )
        ],
        x_labels=[f"Year {year}" for year in range(1, len(series) + 1)],
        y_unit="xcd_cents",
    )
    return Projection(
        final_cents=int(final.value),
        contributed_cents=int(final.breakdown["contributed"]),
        earned_cents=int(final.breakdown["earned"]),
        display=final.display,
        series=series,
        directive=directive_payload(directive),
    )


# ── documents ────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Document:
    slot: str
    label: str
    required: bool = True
    note: str = ""


#: What each application type needs.
_CHECKLISTS: dict[str, tuple[Document, ...]] = {
    "new_child_account": (
        Document("guardian.id_document", "Guardian's photo ID"),
        Document("guardian.proof_of_address", "Proof of the guardian's address"),
        Document("child.birth_certificate", "The child's birth certificate"),
        Document(
            "child.photo",
            "A recent photo of the child",
            required=False,
            note="Optional -- it goes on the passbook.",
        ),
    ),
    "additional_child": (
        Document("child.birth_certificate", "The child's birth certificate"),
        Document(
            "child.photo",
            "A recent photo of the child",
            required=False,
            note="Optional -- it goes on the passbook.",
        ),
    ),
    "guardian_change": (
        Document("guardian.id_document", "The new guardian's photo ID"),
        Document("guardian.proof_of_address", "Proof of the new guardian's address"),
        Document(
            "guardian.court_order",
            "The court order or letter of guardianship",
            note="Only where guardianship was granted rather than by birth.",
        ),
    ),
}


def document_checklist(application_type: str) -> list[Document]:
    """The documents this application needs."""
    checklist = _CHECKLISTS.get(application_type)
    if checklist is None:
        logger.warning(
            "Unknown application type %r; returning the standard checklist.",
            application_type,
        )
        checklist = _CHECKLISTS["new_child_account"]
    return list(checklist)


# ── branches ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Branch:
    name: str
    parish: str
    address: str
    hours: str
    phone: str = ""


#: The branch table.
_BRANCHES: tuple[Branch, ...] = (
    Branch(
        "Basseterre Main",
        "Saint George Basseterre",
        "Central Street, Basseterre",
        "Mon-Fri 8am-3pm, Sat 9am-12pm",
    ),
    Branch(
        "Sandy Point",
        "Saint Anne Sandy Point",
        "Main Street, Sandy Point Town",
        "Mon-Fri 8am-2pm",
    ),
    Branch(
        "Cayon",
        "Saint Mary Cayon",
        "Main Road, Cayon",
        "Mon, Wed, Fri 9am-2pm",
    ),
    Branch(
        "Charlestown",
        "Saint Paul Charlestown",
        "Main Street, Charlestown, Nevis",
        "Mon-Fri 8am-3pm",
    ),
    Branch(
        "Gingerland",
        "Saint George Gingerland",
        "Market Shop, Gingerland, Nevis",
        "Tue, Thu 9am-1pm",
    ),
)


def find_branch(parish: str) -> list[Branch]:
    """Branches in or near a parish."""
    needle = parish.strip().lower()
    if not needle:
        return list(_BRANCHES)
    matches = [
        branch
        for branch in _BRANCHES
        if needle in branch.parish.lower() or needle in branch.name.lower()
    ]
    return matches or list(_BRANCHES)


# ── handoffs ─────────────────────────────────────────────────────────────────


def handoff_to_registration() -> Command:
    """Move this conversation to the registration agent."""
    return Command(goto="register_agent", update={"active_agent": "register_agent"})


@dataclass(frozen=True, slots=True)
class Ticket:
    id: str
    reason: str
    summary: str
    priority: Literal["low", "normal", "high"] = "normal"
    category: str = "general"
    eta: str = "one working day"
    fields: dict[str, Any] = field(default_factory=dict)


def escalate_to_human(reason: str, summary: str) -> Command:
    """Hand the question to a person, with a redacted summary."""
    from app.safety import pii

    ticket = Ticket(
        id=f"ASP-{uuid.uuid4().hex[:8].upper()}",
        reason=reason,
        summary=pii.redact_for_summary(summary),
    )
    return Command(
        goto="escalate_agent",
        update={"active_agent": "escalate_agent", "escalation": ticket},
    )
