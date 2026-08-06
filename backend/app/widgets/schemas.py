"""The nine concept-widget primitives, as a closed discriminated union.

A widget is a small interactive explanation the learning agent emits inline in
its prose. The model chooses a *kind* and fills in *parameters*; it never emits
markup, never emits colours, and never computes a number a child will read --
those come from `formulas/registry.py`, deterministically, in Python.

## Why all nine exist today

Only some of these render this session. All nine are defined now because the
schema is the contract between the model prompt, the validator, and the
frontend registry, and adding a variant later means touching a prompt, a gate
and a renderer at once. Defining them together means the *shape* is settled --
`v`, `kind`, the a11y text, the colour vocabulary -- and later work is a
renderer plus a few-shot file.

## The three things a widget may never contain

Enforced here, at parse time, on every string field, by `SafeText`:

  1. **Markup.** No `<`, no `>`. A widget is data rendered by a React component,
     not a fragment injected into one. The frontend does not use
     `dangerouslySetInnerHTML` and this makes sure it never has a reason to.
  2. **URLs and schemes.** No `javascript:`, no `data:`, no `http`. A widget is
     not a navigation surface, and the youngest bands must not be handed links
     at all (`safety_out` strips them from prose for the same reason).
  3. **Literal colours.** No `#a1b2c3`, no `rgb(...)`. Colour is a semantic
     token resolved by the theme -- see `ColourToken`. A model that picks its
     own colours picks them inconsistently across turns, picks them without
     regard to contrast, and picks them without regard to dark mode.

`SafeText` rejects rather than sanitises. A widget that had to be cleaned is a
widget whose generation went wrong somewhere, and the correct response is gate
2 failing and prose being served instead -- silently, with a log line -- not a
scrubbed widget nobody reviewed.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ── the string rule ──────────────────────────────────────────────────────────

#: Anything that looks like markup, a scheme, or a literal colour.
#:
#: Deliberately broad and deliberately dumb. It is a gate, not a parser: a
#: false positive costs one widget and produces a log line naming the field,
#: while a false negative costs the property this whole module rests on.
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


#: Every user-visible string in a widget. Length-capped as well as filtered:
#: gate 6 enforces per-field copy limits against the age band, and this is the
#: absolute ceiling underneath it that applies regardless of band.
SafeText = Annotated[str, Field(max_length=160)]

#: A caption or body, which is allowed to be a sentence rather than a label.
SafeBody = Annotated[str, Field(max_length=400)]


class _WidgetModel(BaseModel):
    """Shared configuration and the string rule, applied to every variant.

    `extra="forbid"` is doing real work: it is what makes an unknown field a
    gate-2 failure rather than a silently ignored one. A model that invents
    `"color": "#ff0000"` must fail, and the whole point of forbidding literal
    colours is defeated if an unrecognised field is dropped on the floor.
    """

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
#:
#: Semantic rather than literal, so the theme decides what "accent" looks like
#: in light mode, in dark mode, and at whatever contrast the accessibility pass
#: settles on. `accent` has a specific job in the growth widgets: it marks the
#: money the bank added, which is the entire lesson made visible.
ColourToken = Literal["neutral", "accent", "positive", "caution", "muted"]

#: What a number means, so the renderer can format it and the validator can
#: bound it.
#:
#: `xcd_cents` is East Caribbean dollars in MINOR UNITS -- integer cents,
#: everywhere, always. See `formulas/registry.py` for why money never touches a
#: float in this codebase.
Unit = Literal["xcd_cents", "years", "months", "weeks", "rate", "count", "share"]

#: How a simulator draws its output. `number_only` is a first-class choice and
#: often the right one for 13-15: a single number that moves when you move a
#: slider is a clearer causal statement than a chart.
Visual = Literal["stacked_bars", "line", "coin_stack", "number_only"]

#: Icons a `proportion` widget may repeat. A closed set because these ship as
#: components; a free string would be an open door to an emoji nobody reviewed
#: rendering at 4x scale on a six-year-old's screen.
UnitIcon = Literal["coin", "person", "star", "block", "cup", "book"]


class Control(BaseModel):
    """One thing a learner can move.

    `id` is the variable name the formula or expression sees, so it is
    constrained to something that can be a Python identifier -- gate 5
    evaluates the expression with these as the declared variables, and a
    control called `"my rate"` would make that impossible.

    `min < default < max` is checked by gate 4 rather than here, on purpose: a
    schema failure and a numeric-sanity failure are different gates with
    different log lines, and collapsing them would hide which one a bad
    generation actually tripped.
    """

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
    #: What the tap reveals. The point of the primitive: a prediction, then the
    #: answer.
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
    #: Ignored by `sort_buckets`.
    default_share: int = Field(default=0, ge=0, le=100)


class SortItem(BaseModel):
    """One thing to be placed. Tapped into a bucket, never dragged."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,23}$")
    label: SafeText
    #: The bucket this belongs in, when there is a right answer. None means the
    #: item is a judgement call and the widget will not grade it.
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
    #: Position along the line, 0-100. Not a date: the primitive teaches
    #: sequence and spacing, and real dates would put a calendar on screen for
    #: a nine-year-old.
    at: int = Field(ge=0, le=100)
    colour: ColourToken = "neutral"


# ── the base every variant shares ────────────────────────────────────────────


class _BaseWidget(_WidgetModel):
    """What every widget carries regardless of kind.

    `a11y_text` is required and has no default, which is the single most
    consequential decision in this file. A widget is a visual explanation, and
    a visual explanation with no text equivalent is a lesson a blind child
    cannot receive. Making it required means a model that forgets it produces a
    gate-2 failure and the child gets prose -- which is worse than a widget and
    far better than a widget they cannot use.
    """

    v: int = Field(default=1, ge=1, le=1)
    #: Which curriculum concept this teaches. The cache key includes it, the
    #: mastery update reads it, and gate 3 checks it against the band's ladder.
    concept_id: str = Field(pattern=r"^[a-z][a-z0-9_.\-]{0,63}$")
    title: SafeText
    caption: SafeBody = ""
    #: The same lesson, in words, for a screen reader. See above.
    a11y_text: SafeBody


# ── the nine ─────────────────────────────────────────────────────────────────


class SimulatorWidget(_BaseWidget):
    """Sliders driving a number that recomputes as they move.

    The causal primitive: the learner changes an input and watches an output
    respond. Everything else here explains; this one lets them poke.

    Exactly one of `formula` and `expression` must be set. `formula` names a
    function in the registry and is strongly preferred -- it is tested, it
    carries a `band_min`, and its domain is known. `expression` is the escape
    hatch for a shape the registry does not cover, and it pays for that
    flexibility by going through the AST allowlist in `formulas/expression.py`
    and being evaluated at every corner of its input domain before it is
    allowed out.
    """

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
    """Two coin stacks and a button that advances one period at a time.

    Purpose-built for compound interest at 9-12, where the concept is real and
    the arithmetic is not yet. The learner taps "Next year", coins drop into
    both stacks, and the `earned` stack -- rendered in the accent token -- grows
    faster than the one they are putting money into. That difference *is* the
    lesson, and it is delivered without a single percentage appearing on screen.

    Every money field is integer cents. `rate` is a decimal fraction (0.05 for
    five percent) and is never shown to a 9-12 learner; gate 3 enforces that.
    """

    kind: Literal["growth_stack"] = "growth_stack"
    principal_cents: int = Field(ge=0, le=100_000_000)
    contribution_cents: int = Field(default=0, ge=0, le=100_000_000)
    rate: float = Field(ge=0.0, le=0.20)
    periods: int = Field(ge=1, le=50)
    period_label: SafeText = "year"
    saved_label: SafeText = "What you saved"
    earned_label: SafeText = "What the bank added"
    #: Shown once the final period has been reached, never before. The sentence
    #: that names what just happened.
    reveal_line: SafeBody = ""


class CompareWidget(_BaseWidget):
    """Two or three panels, each hiding its answer until tapped.

    A prediction device. The learner is asked which panel they think wins
    before anything is revealed, which is what makes the reveal land.
    """

    kind: Literal["compare"] = "compare"
    panels: list[Panel] = Field(min_length=2, max_length=3)
    #: Which panel the lesson is pointing at, by index. None means neither --
    #: legitimate for a genuine trade-off with no right answer.
    highlight: int | None = None
    prompt: SafeBody = ""

    @model_validator(mode="after")
    def _highlight_exists(self) -> CompareWidget:
        if self.highlight is not None and not 0 <= self.highlight < len(self.panels):
            raise ValueError("highlight must index one of the panels")
        return self


class SortBucketsWidget(_BaseWidget):
    """Items tapped into categories. Explicitly not drag-and-drop.

    Drag-and-drop is excluded product-wide for bands 5-8 and 9-12 -- it is a
    fine-motor task, it is hostile on a phone, and it fails outright for anyone
    using a switch or a keyboard. Tap the item, tap the bucket.
    """

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
    """A fixed sum split across buckets. There is no wrong answer.

    `no_wrong_answer` is fixed True and is not a parameter, because the agent's
    behaviour depends on it: `widget_result` responds to an allocator by naming
    the trade-off the learner chose, never by grading it. Making it settable
    would let a generation turn a values exercise into a test.
    """

    kind: Literal["allocator"] = "allocator"
    total_cents: int = Field(ge=0, le=100_000_000)
    buckets: list[Bucket] = Field(min_length=2, max_length=4)
    prompt: SafeBody = ""
    no_wrong_answer: Literal[True] = True

    @model_validator(mode="after")
    def _shares_reconcile(self) -> AllocatorWidget:
        # Gate 4 checks this too, and that is not redundancy: this catches a
        # malformed generation at parse time, gate 4 catches it with a log line
        # naming the numeric gate. Both matter, because a set of defaults that
        # does not add to the total renders a widget that starts wrong.
        total = sum(bucket.default_share for bucket in self.buckets)
        if total != 100:
            raise ValueError(f"bucket default shares must total 100, got {total}")
        return self


class FlowDiagramWidget(_BaseWidget):
    """Where money goes, as a sequence of labelled steps.

    Linear on purpose. A general graph would need edge routing, and a
    seven-year-old reading "wages → bank → saving" needs a line, not a diagram.
    """

    kind: Literal["flow_diagram"] = "flow_diagram"
    steps: list[FlowStep] = Field(min_length=2, max_length=6)
    #: The arrow labels, one fewer than there are steps. Empty means unlabelled
    #: arrows, which is the common case.
    edge_labels: list[SafeText] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def _edges_fit_between_the_steps(self) -> FlowDiagramWidget:
        if self.edge_labels and len(self.edge_labels) != len(self.steps) - 1:
            raise ValueError("edge_labels must be empty or one shorter than steps")
        return self


class TimelineWidget(_BaseWidget):
    """A sequence in time: saving up, a goal reached, what happens when.

    Positions are 0-100 along an abstract line rather than dates. The lesson is
    "these things happen in this order, this far apart", and a real calendar
    would add reading load without adding meaning.
    """

    kind: Literal["timeline"] = "timeline"
    points: list[TimelinePoint] = Field(min_length=2, max_length=6)
    start_label: SafeText = ""
    end_label: SafeText = ""


class RevealCardsWidget(_BaseWidget):
    """Cards that flip on tap. Question on the front, answer on the back.

    The cheapest primitive to render and often the right one: it costs no
    formula, no numbers and no domain checks, so it is what the planner should
    reach for when the concept is vocabulary rather than arithmetic.
    """

    kind: Literal["reveal_cards"] = "reveal_cards"
    cards: list[Card] = Field(min_length=2, max_length=6)
    prompt: SafeBody = ""


class ProportionWidget(_BaseWidget):
    """N icons, M of them highlighted. A fraction you can count.

    The word "percent" never appears in this widget's copy for bands 5-8 and
    9-12; gate 6 enforces that against the vocabulary allowlist. "Three out of
    ten coins" is the same fact and is a fact a nine-year-old already has the
    equipment to hold.
    """

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
#:
#: Discriminated on `kind`, which means pydantic dispatches on one string rather
#: than trying every variant and reporting nine errors for one typo. That is not
#: only faster: gate 1's job is to say "unknown kind" distinctly from gate 2's
#: "known kind, bad fields", and a non-discriminated union cannot tell them
#: apart.
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

#: Versions this build can render. Gate 1 rejects anything else rather than
#: attempting a best-effort parse: a v2 widget from a newer backend has fields
#: this renderer does not know about, and rendering it half-right is worse than
#: not rendering it.
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
