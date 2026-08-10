"""The nine concept-widget primitives, as a closed discriminated union."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ── the string rule ──────────────────────────────────────────────────────────

#: Anything that looks like markup, a scheme, or a literal colour.
_FORBIDDEN = re.compile(
    r"""
      [<>]                      # any angle bracket at all
    | \b(?:javascript|data|vbscript)\s*:
    | https?://
    | \#[0-9a-fA-F]{3,8}\b      # #fff, #a1b2c3, #a1b2c3ff
    | \b(?:rgb|rgba|hsl|hsla|oklch|color-mix)\s*\(
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _reject_unsafe(value: str) -> str:
    if _FORBIDDEN.search(value):
        raise ValueError(
            "widget text may not contain markup, a URL scheme or a literal colour"
        )
    return value


#: Every user-visible string in a widget.
SafeText = Annotated[str, Field(max_length=160)]

#: A caption or body, which is allowed to be a sentence rather than a label.
SafeBody = Annotated[str, Field(max_length=400)]


class _WidgetModel(BaseModel):
    """Shared configuration and the string rule, applied to every variant."""

    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def _strings_are_safe(cls, value: Any) -> Any:
        if isinstance(value, str):
            return _reject_unsafe(value)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    _reject_unsafe(item)
        return value


# ── the shared vocabularies ──────────────────────────────────────────────────

#: The only colours a widget may name.
ColourToken = Literal["neutral", "accent", "positive", "caution", "muted"]

#: What a number means, so the renderer can format it and the validator can bound it.
Unit = Literal["xcd_cents", "years", "months", "weeks", "rate", "count", "share"]

#: How a simulator draws its output.
Visual = Literal["stacked_bars", "line", "coin_stack", "number_only"]

#: Icons a `proportion` widget may repeat.
UnitIcon = Literal["coin", "person", "star", "block", "cup", "book"]


class Control(BaseModel):
    """One thing a learner can move."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,23}$")
    label: SafeText
    kind: Literal["slider", "stepper", "choice"] = "slider"
    unit: Unit = "count"
    min: float
    max: float
    default: float
    #: Granularity. For `xcd_cents` this is cents, so 100 means "whole dollars".
    step: float = Field(default=1.0, gt=0)


class Panel(BaseModel):
    """One side of a `compare`."""

    model_config = ConfigDict(extra="forbid")

    label: SafeText
    #: What is visible before the tap.
    summary: SafeBody
    #: What the tap reveals.
    detail: SafeBody
    colour: ColourToken = "neutral"


class Card(BaseModel):
    """One card in a `reveal_cards`."""

    model_config = ConfigDict(extra="forbid")

    front: SafeText
    back: SafeBody


class Bucket(BaseModel):
    """One destination in a `sort_buckets` or one slice of an `allocator`."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,23}$")
    label: SafeText
    hint: SafeText = ""
    colour: ColourToken = "neutral"
    #: `allocator` only: the starting share, in whole percent of the total.
    default_share: int = Field(default=0, ge=0, le=100)


class SortItem(BaseModel):
    """One thing to be placed. Tapped into a bucket, never dragged."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,23}$")
    label: SafeText
    #: The bucket this belongs in, when there is a right answer.
    belongs_to: str | None = None


class FlowStep(BaseModel):
    """One node of a `flow_diagram`."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,23}$")
    label: SafeText
    detail: SafeBody = ""
    colour: ColourToken = "neutral"


class TimelinePoint(BaseModel):
    """One moment on a `timeline`."""

    model_config = ConfigDict(extra="forbid")

    label: SafeText
    caption: SafeBody = ""
    #: Position along the line, 0-100.
    at: int = Field(ge=0, le=100)
    colour: ColourToken = "neutral"


# ── the base every variant shares ────────────────────────────────────────────


class _BaseWidget(_WidgetModel):
    """What every widget carries regardless of kind."""

    v: int = Field(default=1, ge=1, le=1)
    #: Which curriculum concept this teaches.
    #:
    #: Lower-cased before the pattern is applied. The concept store seeds ids as
    #: `CON-0019` and this pattern demands a lowercase leading letter, so a
    #: composer that copied the id it was given failed the schema while one that
    #: lowercased it used to fail the band gate -- there was no spelling that
    #: passed both, and the feature was dropped on every lesson turn as a result.
    #: Case is not meaningful in an identifier; the case-insensitive lookup in
    #: `safety.vocab.is_allowed_concept` is the other half of this.
    concept_id: str = Field(pattern=r"^[a-z][a-z0-9_.\-]{0,63}$")

    @field_validator("concept_id", mode="before")
    @classmethod
    def _fold_case(cls, value: Any) -> Any:
        return value.strip().lower() if isinstance(value, str) else value
    title: SafeText
    caption: SafeBody = ""
    #: The same lesson, in words, for a screen reader. See above.
    a11y_text: SafeBody


# ── the nine ─────────────────────────────────────────────────────────────────


class SimulatorWidget(_BaseWidget):
    """Sliders driving a number that recomputes as they move."""

    kind: Literal["simulator"] = "simulator"
    controls: list[Control] = Field(min_length=1, max_length=4)
    formula: str | None = None
    expression: str | None = Field(default=None, max_length=200)
    output_label: SafeText
    output_unit: Unit = "xcd_cents"
    visual: Visual = "number_only"

    @model_validator(mode="after")
    def _exactly_one_source_of_truth(self) -> SimulatorWidget:
        if bool(self.formula) == bool(self.expression):
            raise ValueError(
                "a simulator needs exactly one of `formula` or `expression`"
            )
        return self

    @model_validator(mode="after")
    def _control_ids_are_unique(self) -> SimulatorWidget:
        ids = [control.id for control in self.controls]
        if len(ids) != len(set(ids)):
            raise ValueError("control ids must be unique")
        return self


class GrowthStackWidget(_BaseWidget):
    """Two coin stacks and a button that advances one period at a time."""

    kind: Literal["growth_stack"] = "growth_stack"
    principal_cents: int = Field(ge=0, le=100_000_000)
    contribution_cents: int = Field(default=0, ge=0, le=100_000_000)
    rate: float = Field(ge=0.0, le=0.20)
    periods: int = Field(ge=1, le=50)
    period_label: SafeText = "year"
    saved_label: SafeText = "What you saved"
    earned_label: SafeText = "What the bank added"
    #: Shown once the final period has been reached, never before.
    reveal_line: SafeBody = ""


class CompareWidget(_BaseWidget):
    """Two or three panels, each hiding its answer until tapped."""

    kind: Literal["compare"] = "compare"
    panels: list[Panel] = Field(min_length=2, max_length=3)
    #: Which panel the lesson is pointing at, by index.
    highlight: int | None = None
    prompt: SafeBody = ""

    @model_validator(mode="after")
    def _highlight_exists(self) -> CompareWidget:
        if self.highlight is not None and not 0 <= self.highlight < len(self.panels):
            raise ValueError("highlight must index one of the panels")
        return self


class SortBucketsWidget(_BaseWidget):
    """Items tapped into categories."""

    kind: Literal["sort_buckets"] = "sort_buckets"
    items: list[SortItem] = Field(min_length=2, max_length=8)
    buckets: list[Bucket] = Field(min_length=2, max_length=4)
    prompt: SafeBody = ""

    @model_validator(mode="after")
    def _answers_point_at_real_buckets(self) -> SortBucketsWidget:
        known = {bucket.id for bucket in self.buckets}
        for item in self.items:
            if item.belongs_to is not None and item.belongs_to not in known:
                raise ValueError(f"item {item.id!r} belongs to an unknown bucket")
        return self


class AllocatorWidget(_BaseWidget):
    """A fixed sum split across buckets."""

    kind: Literal["allocator"] = "allocator"
    total_cents: int = Field(ge=0, le=100_000_000)
    buckets: list[Bucket] = Field(min_length=2, max_length=4)
    prompt: SafeBody = ""
    no_wrong_answer: Literal[True] = True

    @model_validator(mode="after")
    def _shares_reconcile(self) -> AllocatorWidget:
        # Gate 4 checks this too, and that is not redundancy: this catches a malformed generation at parse time, gate 4…
        total = sum(bucket.default_share for bucket in self.buckets)
        if total != 100:
            raise ValueError(f"bucket default shares must total 100, got {total}")
        return self


class FlowDiagramWidget(_BaseWidget):
    """Where money goes, as a sequence of labelled steps."""

    kind: Literal["flow_diagram"] = "flow_diagram"
    steps: list[FlowStep] = Field(min_length=2, max_length=6)
    #: The arrow labels, one fewer than there are steps.
    edge_labels: list[SafeText] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def _edges_fit_between_the_steps(self) -> FlowDiagramWidget:
        if self.edge_labels and len(self.edge_labels) != len(self.steps) - 1:
            raise ValueError("edge_labels must be empty or one shorter than steps")
        return self


class TimelineWidget(_BaseWidget):
    """A sequence in time: saving up, a goal reached, what happens when."""

    kind: Literal["timeline"] = "timeline"
    points: list[TimelinePoint] = Field(min_length=2, max_length=6)
    start_label: SafeText = ""
    end_label: SafeText = ""


class RevealCardsWidget(_BaseWidget):
    """Cards that flip on tap."""

    kind: Literal["reveal_cards"] = "reveal_cards"
    cards: list[Card] = Field(min_length=2, max_length=6)
    prompt: SafeBody = ""


class ProportionWidget(_BaseWidget):
    """N icons, M of them highlighted."""

    kind: Literal["proportion"] = "proportion"
    total: int = Field(ge=2, le=100)
    highlighted: int = Field(ge=0, le=100)
    icon: UnitIcon = "coin"
    highlighted_label: SafeText = ""
    remainder_label: SafeText = ""

    @model_validator(mode="after")
    def _highlighted_fits(self) -> ProportionWidget:
        if self.highlighted > self.total:
            raise ValueError("highlighted cannot exceed total")
        return self


#: The union the interceptor parses into and the frontend registry mirrors.
ConceptWidget = Annotated[
    Union[
        SimulatorWidget,
        GrowthStackWidget,
        CompareWidget,
        SortBucketsWidget,
        AllocatorWidget,
        FlowDiagramWidget,
        TimelineWidget,
        RevealCardsWidget,
        ProportionWidget,
    ],
    Field(discriminator="kind"),
]

#: Every kind name, for gate 1 and for the planner prompt.
WIDGET_KINDS: frozenset[str] = frozenset(
    {
        "simulator",
        "growth_stack",
        "compare",
        "sort_buckets",
        "allocator",
        "flow_diagram",
        "timeline",
        "reveal_cards",
        "proportion",
    }
)

#: Versions this build can render.
WIDGET_VERSIONS: frozenset[int] = frozenset({1})

_BY_KIND: dict[str, type[_BaseWidget]] = {
    "simulator": SimulatorWidget,
    "growth_stack": GrowthStackWidget,
    "compare": CompareWidget,
    "sort_buckets": SortBucketsWidget,
    "allocator": AllocatorWidget,
    "flow_diagram": FlowDiagramWidget,
    "timeline": TimelineWidget,
    "reveal_cards": RevealCardsWidget,
    "proportion": ProportionWidget,
}


def model_for(kind: str) -> type[_BaseWidget] | None:
    """The pydantic model for a kind name, or None if it is not one of ours."""
    return _BY_KIND.get(kind)
