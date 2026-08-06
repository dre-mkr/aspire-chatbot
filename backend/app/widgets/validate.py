"""Seven gates a generated widget passes before a child sees it.

    1 PARSE          valid JSON, known kind, known version
    2 SCHEMA         pydantic validation for that kind
    3 BAND           kind allowed for the band; concept on the ladder; controls
                     within the band's cap
    4 NUMERIC        min < default < max; rate, principal and period bounds;
                     allocator shares reconcile
    5 FORMULA DOMAIN the formula exists and the band may have it, or the
                     expression passes the AST allowlist -- evaluated at every
                     corner and midpoint
    6 COPY           every label and caption passes the band's vocabulary rules,
                     within per-field length caps
    7 BUDGET         at most one widget per turn (two at 16-18), at most one
                     simulator

An ordered list of predicates rather than one function, and the ordering is
cheapest-first: a malformed JSON blob should not cost an AST walk. It also
means the *name* of the failing gate is available to the log line and to the
counters, which is the whole feedback loop -- "gate 6 fired 40 times this week"
is a prompt to fix, and "the widget was rejected" is not.

## Failing is the normal case and it is silent

A widget that fails is not an error. The child gets prose, which was always a
complete answer; the widget was the bonus. Nothing is shown, nothing is
retried, and one line is logged.

The one thing a gate must never do is *repair*. A gate that clamps a rate from
0.9 to 0.2 has invented a lesson nobody wrote. Reject and move on.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import TypeAdapter, ValidationError

from app.safety import vocab
from app.widgets.schemas import (
    ConceptWidget,
    WIDGET_KINDS,
    WIDGET_VERSIONS,
    model_for,
)

logger = logging.getLogger(__name__)

_ADAPTER: TypeAdapter[Any] = TypeAdapter(ConceptWidget)


@dataclass(frozen=True, slots=True)
class GateResult:
    """Whether a widget survived, and if not, which gate stopped it."""

    ok: bool
    widget: Any = None
    gate: str | None = None
    reason: str = ""

    @classmethod
    def fail(cls, gate: str, reason: str) -> "GateResult":
        return cls(ok=False, gate=gate, reason=reason)

    @classmethod
    def pass_(cls, widget: Any) -> "GateResult":
        return cls(ok=True, widget=widget)


@dataclass(frozen=True, slots=True)
class GateContext:
    """Everything a gate is allowed to know about the reader.

    Deliberately small. A gate that could see the conversation would start
    making editorial judgements, and these are meant to be mechanical checks
    that a reviewer can re-derive by reading the widget and the band.
    """

    age_band: str
    locale: str = "en"
    #: How many widgets this turn has already emitted, for gate 7.
    widgets_this_turn: int = 0
    simulators_this_turn: int = 0


# ── band policy ──────────────────────────────────────────────────────────────

#: Which primitives each band may receive.
#:
#: The two consequential entries: 5-8 gets NO simulator (a slider driving a
#: formula is an abstraction a six-year-old is not being taught yet, and the
#: planner is instructed to redirect to the saving concept instead), and 9-12
#: gets `growth_stack` rather than `simulator` for the same reason -- coins you
#: can count beat a number that changes.
#:
#: `timeline` IS offered at 5-8 and that is a considered call: it carries no
#: arithmetic and no numbers a child has to hold -- "one coin each week until
#: the football" is a sequence, and sequence is something a six-year-old
#: already reasons about fluently. What they are not ready for is a rate.
BAND_KINDS: dict[str, frozenset[str]] = {
    "5-8": frozenset(
        {"compare", "reveal_cards", "proportion", "sort_buckets", "flow_diagram", "timeline"}
    ),
    "9-12": frozenset(
        {
            "compare",
            "reveal_cards",
            "proportion",
            "sort_buckets",
            "flow_diagram",
            "timeline",
            "allocator",
            "growth_stack",
        }
    ),
    "13-15": frozenset(WIDGET_KINDS),
    "16-18": frozenset(WIDGET_KINDS),
    "adult": frozenset(WIDGET_KINDS),
}

#: How many controls a simulator may have, by band. Gate 4 enforces it.
BAND_CONTROL_CAP: dict[str, int] = {
    "5-8": 0,
    "9-12": 2,
    "13-15": 2,
    "16-18": 4,
    "adult": 4,
}

#: How many widgets one turn may emit. Two only from 16-18 upward: below that,
#: a second widget in one turn is two things to do and a lesson that has stopped
#: being a conversation.
BAND_WIDGET_BUDGET: dict[str, int] = {
    "5-8": 1,
    "9-12": 1,
    "13-15": 1,
    "16-18": 2,
    "adult": 2,
}

#: Per-field copy caps, by band. Gate 6.
BAND_LABEL_WORDS: dict[str, int] = {
    "5-8": 4,
    "9-12": 6,
    "13-15": 8,
    "16-18": 10,
    "adult": 12,
}
BAND_CAPTION_WORDS: dict[str, int] = {
    "5-8": 12,
    "9-12": 20,
    "13-15": 30,
    "16-18": 45,
    "adult": 60,
}

#: `a11y_text` has its own, much larger cap.
#:
#: It is NOT on-screen copy. It is the whole lesson in words, for a child using
#: a screen reader, and it has to convey what the widget conveys visually --
#: which for a growth stack is two stacks, what each represents, and how they
#: differ. Holding it to the caption cap was the first thing the eval harness
#: caught, and it was right to: every shipped example failed, because twelve
#: words cannot describe a widget.
#:
#: The vocabulary rules still apply in full. A screen-reader equivalent that
#: uses words the band has not met is the same failure with a smaller audience.
BAND_A11Y_WORDS: dict[str, int] = {
    "5-8": 45,
    "9-12": 60,
    "13-15": 80,
    "16-18": 100,
    "adult": 120,
}


# ── gate 1: parse ────────────────────────────────────────────────────────────


def gate_parse(raw: str, context: GateContext) -> GateResult:
    """Valid JSON, a kind we know, a version we can render.

    Version is checked HERE rather than left to pydantic, because "v2 widget
    from a newer backend" and "malformed v1 widget" need different log lines and
    different responses. A v2 widget is a deployment-skew problem; a malformed
    v1 is a prompt problem.
    """
    text = raw.strip()
    if not text:
        return GateResult.fail("parse", "empty widget block")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        return GateResult.fail("parse", f"invalid JSON: {error.msg}")
    if not isinstance(data, dict):
        return GateResult.fail("parse", f"expected an object, got {type(data).__name__}")

    kind = data.get("kind")
    if kind not in WIDGET_KINDS:
        return GateResult.fail("parse", f"unknown kind {kind!r}")
    version = data.get("v", 1)
    if version not in WIDGET_VERSIONS:
        return GateResult.fail("parse", f"unknown version {version!r} for {kind}")

    return GateResult.pass_(data)


# ── gate 2: schema ───────────────────────────────────────────────────────────


def gate_schema(data: dict[str, Any], context: GateContext) -> GateResult:
    """Pydantic validation for that kind, including the string safety rules.

    This is where markup, URLs and literal colours are rejected -- see
    `schemas.SafeText`. Rejected rather than sanitised: a widget that had to be
    cleaned is a widget whose generation went wrong, and prose is the right
    answer to that.
    """
    if model_for(str(data.get("kind"))) is None:  # pragma: no cover - gate 1 covers it
        return GateResult.fail("schema", "no model for kind")
    try:
        return GateResult.pass_(_ADAPTER.validate_python(data))
    except ValidationError as error:
        first = error.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ()))
        return GateResult.fail("schema", f"{location or 'widget'}: {first.get('msg')}")


# ── gate 3: band ─────────────────────────────────────────────────────────────


def gate_band(widget: Any, context: GateContext) -> GateResult:
    """The kind, the concept and the control count, against the reader's band."""
    permitted = BAND_KINDS.get(context.age_band)
    if permitted is None:
        # An unknown band has no permitted kinds. Fail closed: a malformed
        # identity must not be the widest permission in the system.
        return GateResult.fail("band", f"unknown age band {context.age_band!r}")
    if widget.kind not in permitted:
        return GateResult.fail(
            "band", f"{widget.kind} is not offered at {context.age_band}"
        )

    if not vocab.is_allowed_concept(widget.concept_id, context.age_band):
        return GateResult.fail(
            "band",
            f"concept {widget.concept_id!r} is not on the {context.age_band} ladder",
        )

    if widget.kind == "simulator":
        cap = BAND_CONTROL_CAP.get(context.age_band, 0)
        if len(widget.controls) > cap:
            return GateResult.fail(
                "band",
                f"{len(widget.controls)} controls exceeds the {context.age_band} "
                f"cap of {cap}",
            )

    return GateResult.pass_(widget)


# ── gate 4: numeric sanity ───────────────────────────────────────────────────

#: Bounds nothing on this product may exceed, whatever the band.
MAX_RATE = 0.20
MAX_PERIODS = 50
MAX_CONTROLS = 4


def gate_numeric(widget: Any, context: GateContext) -> GateResult:
    """Every number a control or a projection depends on, bounded."""
    if widget.kind == "simulator":
        if len(widget.controls) > MAX_CONTROLS:
            return GateResult.fail("numeric", "more than four controls")
        for control in widget.controls:
            if not control.min < control.default < control.max:
                return GateResult.fail(
                    "numeric",
                    f"control {control.id!r} needs min < default < max, got "
                    f"{control.min} / {control.default} / {control.max}",
                )
            if control.step <= 0 or control.step > (control.max - control.min):
                return GateResult.fail(
                    "numeric", f"control {control.id!r} has an unusable step"
                )
            problem = _bounds_problem(control.unit, control.min, control.max)
            if problem:
                return GateResult.fail("numeric", f"control {control.id!r}: {problem}")

    if widget.kind == "growth_stack":
        if not 0.0 <= widget.rate <= MAX_RATE:
            return GateResult.fail(
                "numeric", f"rate {widget.rate} is outside [0, {MAX_RATE}]"
            )
        if widget.periods > MAX_PERIODS:
            return GateResult.fail("numeric", f"{widget.periods} periods exceeds {MAX_PERIODS}")
        if widget.principal_cents < 0 or widget.contribution_cents < 0:
            return GateResult.fail("numeric", "money cannot be negative")
        if widget.principal_cents == 0 and widget.contribution_cents == 0:
            # Not a schema violation and still a broken lesson: two empty stacks
            # that never grow teach the opposite of the point.
            return GateResult.fail("numeric", "nothing is being saved")

    if widget.kind == "allocator":
        total = sum(bucket.default_share for bucket in widget.buckets)
        if total != 100:
            return GateResult.fail("numeric", f"bucket shares total {total}, not 100")
        if widget.total_cents <= 0:
            return GateResult.fail("numeric", "there is nothing to allocate")

    if widget.kind == "proportion" and widget.highlighted > widget.total:
        return GateResult.fail("numeric", "highlighted exceeds total")

    return GateResult.pass_(widget)


def _bounds_problem(unit: str, low: float, high: float) -> str | None:
    if unit == "rate" and not (0.0 <= low and high <= MAX_RATE):
        return f"a rate control must stay within [0, {MAX_RATE}]"
    if unit in ("years", "months", "weeks") and (low < 0 or high > MAX_PERIODS * 12):
        return "period bounds are implausible"
    if unit == "xcd_cents" and low < 0:
        return "money cannot be negative"
    if unit == "count" and low < 0:
        return "a count cannot be negative"
    if high <= low:
        return "max must exceed min"
    return None


# ── gate 5: formula domain ───────────────────────────────────────────────────


def gate_formula(widget: Any, context: GateContext) -> GateResult:
    """A simulator's maths must exist, suit the band, and behave on its domain.

    "Behave" is checked by evaluation rather than by inspection: the formula is
    run at every corner of the control box plus the midpoints, and any NaN,
    infinity, negative-where-impossible or absurd magnitude drops the widget.
    An expression that misbehaves only in one corner is exactly the expression a
    child will find, because a child moves every slider to its end.
    """
    if widget.kind != "simulator":
        return GateResult.pass_(widget)

    from app.widgets.formulas import expression as expr
    from app.widgets.formulas import registry

    variables = {control.id: control for control in widget.controls}

    if widget.formula:
        spec = registry.get(widget.formula)
        if spec is None:
            return GateResult.fail("formula", f"unknown formula {widget.formula!r}")
        from app.graph.state import band_index

        if band_index(context.age_band) < band_index(spec.band_min):
            return GateResult.fail(
                "formula",
                f"{widget.formula} is for {spec.band_min} and up, not "
                f"{context.age_band}",
            )
        # A parameter no control drives is fine IF the registry has an inert
        # default for it -- `savings_goal_time` takes a rate, and a two-slider
        # widget that leaves it at zero is a correct and common widget. Only a
        # parameter with neither a control nor a default is unsatisfiable.
        missing = set(spec.parameters) - set(variables) - set(registry._DEFAULTS)
        if missing:
            return GateResult.fail(
                "formula", f"{widget.formula} needs {sorted(missing)}"
            )
        problem = registry.probe_domain(spec, variables)
        if problem:
            return GateResult.fail("formula", problem)
        return GateResult.pass_(widget)

    problem = expr.check(widget.expression or "", variables)
    if problem:
        return GateResult.fail("formula", problem)
    return GateResult.pass_(widget)


# ── gate 6: copy ─────────────────────────────────────────────────────────────


def _strings(widget: Any) -> list[tuple[str, str, bool]]:
    """Every user-visible string, as `(path, text, is_label)`.

    `is_label` selects which word cap applies. Walking the dumped model rather
    than enumerating fields per kind means a new field added to a schema is
    checked automatically -- the alternative is a gate that silently stops
    covering the thing somebody just added.
    """
    #: Fields that are identifiers rather than copy. They are pattern-checked by
    #: the schema and are never rendered, so vocabulary rules do not apply.
    skip = {"id", "kind", "concept_id", "formula", "expression", "belongs_to", "colour", "icon"}
    found: list[tuple[str, str, bool]] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in skip:
                    continue
                walk(value, f"{path}.{key}" if path else key)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        elif isinstance(node, str) and node.strip():
            leaf = path.rsplit(".", 1)[-1]
            is_label = leaf in {"label", "title", "front", "output_label", "period_label"}
            found.append((path, node, is_label))

    walk(widget.model_dump(mode="python"), "")
    return found


def gate_copy(widget: Any, context: GateContext) -> GateResult:
    """Vocabulary and length, on every string a reader sees.

    `a11y_text` is checked like any other copy and that is deliberate: it is the
    version a blind child receives, and a screen-reader equivalent that uses
    words the band has not met is the same failure with a smaller audience.
    """
    label_cap = BAND_LABEL_WORDS.get(context.age_band, 12)
    caption_cap = BAND_CAPTION_WORDS.get(context.age_band, 60)
    a11y_cap = BAND_A11Y_WORDS.get(context.age_band, 120)

    for path, text, is_label in _strings(widget):
        violations = vocab.check(text, context.age_band)
        if violations:
            return GateResult.fail(
                "copy",
                f"{path} uses {sorted({v.term for v in violations})} at "
                f"{context.age_band}",
            )
        if path.endswith("a11y_text"):
            cap = a11y_cap
        else:
            cap = label_cap if is_label else caption_cap
        words = len(text.split())
        if words > cap:
            return GateResult.fail(
                "copy", f"{path} is {words} words, over the {context.age_band} cap of {cap}"
            )
    return GateResult.pass_(widget)


# ── gate 7: budget ───────────────────────────────────────────────────────────


def gate_budget(widget: Any, context: GateContext) -> GateResult:
    """One widget a turn, two from 16-18. Never two simulators."""
    budget = BAND_WIDGET_BUDGET.get(context.age_band, 1)
    if context.widgets_this_turn >= budget:
        return GateResult.fail(
            "budget", f"already emitted {context.widgets_this_turn} of {budget} this turn"
        )
    if widget.kind == "simulator" and context.simulators_this_turn >= 1:
        return GateResult.fail("budget", "one simulator per turn")
    return GateResult.pass_(widget)


# ── the pipeline ─────────────────────────────────────────────────────────────

#: Gates that take the raw string. Only gate 1.
_PARSE_GATES: tuple[Callable[[str, GateContext], GateResult], ...] = (gate_parse,)

#: Gate 2 takes the parsed dict; the rest take the validated model. Kept as one
#: ordered tuple so adding a gate is appending to a list and nothing else --
#: which is exactly how gates 3 through 7 arrived.
_MODEL_GATES: tuple[Callable[[Any, GateContext], GateResult], ...] = (
    gate_band,
    gate_numeric,
    gate_formula,
    gate_copy,
    gate_budget,
)

#: Every gate name, in order. For the metrics surface and for the tests that
#: assert the pipeline has not lost one.
GATE_NAMES: tuple[str, ...] = (
    "parse",
    "schema",
    "band",
    "numeric",
    "formula",
    "copy",
    "budget",
)


def validate_widget(
    raw: str,
    *,
    age_band: str,
    locale: str = "en",
    widgets_this_turn: int = 0,
    simulators_this_turn: int = 0,
) -> GateResult:
    """Run every gate in order. First failure wins and names itself."""
    context = GateContext(
        age_band=age_band,
        locale=locale,
        widgets_this_turn=widgets_this_turn,
        simulators_this_turn=simulators_this_turn,
    )

    for gate in _PARSE_GATES:
        result = gate(raw, context)
        if not result.ok:
            return result
    data = result.widget

    result = gate_schema(data, context)
    if not result.ok:
        return result
    widget = result.widget

    for gate in _MODEL_GATES:
        result = gate(widget, context)
        if not result.ok:
            return result

    return GateResult.pass_(widget)
