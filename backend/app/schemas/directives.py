"""What the server may tell the client to render, as a closed typed union."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from app.widgets.schemas import ConceptWidget


class _Directive(BaseModel):
    """`extra="forbid"` for the same reason the widget schemas use it."""

    model_config = ConfigDict(extra="forbid")


# ── quick replies ────────────────────────────────────────────────────────────


class QuickReplyOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: What the child reads.
    label: str = Field(min_length=1, max_length=60)
    #: What is actually sent when they tap.
    value: str = Field(min_length=1, max_length=280)


class QuickRepliesDirective(_Directive):
    """The tap-not-type surface."""

    t: Literal["quick_replies"] = "quick_replies"
    options: list[QuickReplyOption] = Field(min_length=1, max_length=4)


# ── game ─────────────────────────────────────────────────────────────────────


class GameDirective(_Directive):
    """Launch one of the real game components."""

    t: Literal["game"] = "game"
    game: Literal["scramble", "true_false", "millionaire"]
    concept: str
    difficulty: Literal[1, 2, 3] = 1


# ── eligibility ──────────────────────────────────────────────────────────────


class EligibilityDirective(_Directive):
    """Open the guided eligibility check."""

    t: Literal["eligibility"] = "eligibility"
    check: Literal["aspire_eligibility"] = "aspire_eligibility"
    language: Literal["en", "es", "fr"] = "en"


# ── sign-up ──────────────────────────────────────────────────────────────────


class SignupDirective(_Directive):
    """Open the account sign-up wizard, optionally on a particular role."""

    t: Literal["signup"] = "signup"
    role: Literal["participant", "guardian", "educator"] | None = None


# ── upload ───────────────────────────────────────────────────────────────────


class UploadDirective(_Directive):
    """Ask for a document."""

    t: Literal["upload"] = "upload"
    slot: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=160)
    accepts: list[str] = Field(min_length=1, max_length=8)
    max_mb: int = Field(default=10, ge=1, le=50)
    help: str = Field(default="", max_length=300)
    #: Which application the document belongs to, so the object lands in the prefix the database row will point at.
    application_id: str = Field(default="", max_length=64)
    #: Whether the card may offer a skip control.
    optional: bool = False


# ── review card ──────────────────────────────────────────────────────────────


class ReviewSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=120)
    #: `(slot, label, display_value)`.
    fields: list[tuple[str, str, str]] = Field(default_factory=list)
    #: Document ids only.
    documents: list[str] = Field(default_factory=list)


class ReviewCardDirective(_Directive):
    """The whole application, grouped and editable, before it is submitted."""

    t: Literal["review_card"] = "review_card"
    sections: list[ReviewSection] = Field(min_length=1, max_length=12)


# ── chart ────────────────────────────────────────────────────────────────────


class ChartSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(max_length=80)
    #: Already computed, in Python, deterministically.
    points: list[float] = Field(max_length=200)


class ChartDirective(_Directive):
    """A projection the QA tools computed. Adults and 16-18 only in practice."""

    t: Literal["chart"] = "chart"
    kind: Literal["line", "bar", "stacked_bar"] = "line"
    series: list[ChartSeries] = Field(min_length=1, max_length=4)
    x_labels: list[str] = Field(default_factory=list, max_length=200)
    y_unit: Literal["xcd_cents", "count", "rate"] = "xcd_cents"


# ── progress ─────────────────────────────────────────────────────────────────


class ProgressDirective(_Directive):
    """End-of-session summary: streak, badge, what moved."""

    t: Literal["progress"] = "progress"
    badge: str | None = None
    streak: int = Field(default=0, ge=0)
    mastery_delta: int = Field(default=0)


# ── citations ────────────────────────────────────────────────────────────────


class CitationRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kb_id: str
    title: str = ""


class CitationsDirective(_Directive):
    """Where an answer came from."""

    t: Literal["citations"] = "citations"
    refs: list[CitationRef] = Field(min_length=1, max_length=8)


# ── escalated ────────────────────────────────────────────────────────────────


class EscalatedDirective(_Directive):
    """A human has the question now. Says who, and when to expect them."""

    t: Literal["escalated"] = "escalated"
    ticket_id: str
    eta: str = Field(default="", max_length=120)


# ── widget ───────────────────────────────────────────────────────────────────


class WidgetDirective(_Directive):
    """A concept widget, already validated through every gate."""

    t: Literal["widget"] = "widget"
    payload: ConceptWidget


#: The union carried on the wire and stored in `AspireState.ui_directives`.
UIDirective = Annotated[
    Union[
        QuickRepliesDirective,
        GameDirective,
        EligibilityDirective,
        SignupDirective,
        UploadDirective,
        ReviewCardDirective,
        ChartDirective,
        ProgressDirective,
        CitationsDirective,
        EscalatedDirective,
        WidgetDirective,
    ],
    Field(discriminator="t"),
]

#: Every `t` the server can emit.
DIRECTIVE_TYPES: frozenset[str] = frozenset(
    {
        "quick_replies",
        "game",
        "eligibility",
        "signup",
        "upload",
        "review_card",
        "chart",
        "progress",
        "citations",
        "escalated",
        "widget",
    }
)


def directive_payload(directive: Any) -> dict[str, Any]:
    """A directive as the JSON that goes on the wire."""
    return directive.model_dump(mode="json")
