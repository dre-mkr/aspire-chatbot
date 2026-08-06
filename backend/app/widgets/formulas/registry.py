"""Every number a learner sees, computed here. The model never calculates.

Ten named functions, each tested against hand-verified values. A widget names
one of them; the planner cannot invent a new one; the LLM cannot do the
arithmetic itself. That is the entire arrangement, and it exists because a
language model doing compound interest in its head is a language model that is
right most of the time on a government product teaching children about money.

## Money is integer cents. Always.

Not "usually", not "except in intermediate steps". `0.1 + 0.2 != 0.3` in binary
floating point, and a savings projection is thousands of additions -- the error
compounds exactly as the interest does. Every amount in and out of this module
is an integer count of cents.

Where a calculation genuinely needs fractions -- an exponent, a rate -- it goes
through `Decimal` at 28 significant digits and comes back to an integer at the
boundary, once, with an explicit rounding mode. `ROUND_HALF_UP` rather than
Python's default banker's rounding, because a child comparing our number to the
one on the bank slip should find them equal, and the bank rounds half up.

## Every function carries a band

`band_min` is the youngest band the formula may serve, and gate 5 enforces it.
`compound_interest` is 13-15 and up not because a nine-year-old cannot benefit
from the idea -- `growth_stack` exists precisely to give them the idea -- but
because a *formula with a rate in it* is the wrong representation for them.

## Currency

XCD is pegged at 2.70 to the US dollar and has been since 1976. It is a
constant, not a rate to fetch: a conversion that silently changed between two
turns of the same lesson would be worse than one that is occasionally out of
date, and this one is not out of date.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP, getcontext
from typing import Any, Callable, Mapping, Sequence

#: Enough for fifty periods of compounding without the last cent moving.
getcontext().prec = 28

#: The peg. One US dollar is 2.70 East Caribbean dollars.
XCD_PER_USD = Decimal("2.70")

CURRENCIES: frozenset[str] = frozenset({"XCD", "USD"})

_SYMBOL = {"XCD": "EC$", "USD": "US$"}

#: Absolute ceilings. Anything beyond these is not a lesson, it is a bug that
#: rendered -- and gate 5's domain probe uses them to decide that.
MAX_MONEY_CENTS = 100_000_000_000  # EC$1bn
MAX_PERIODS = 600  # fifty years of months


def money_display(cents: int, currency: str = "XCD") -> str:
    """`EC$1,234.56`. Grouped, two decimals, never a bare float."""
    sign = "-" if cents < 0 else ""
    whole, part = divmod(abs(int(cents)), 100)
    return f"{sign}{_SYMBOL.get(currency, currency + ' ')}{whole:,}.{part:02d}"


@dataclass(frozen=True, slots=True)
class Result:
    """A computed number and the string a reader should see.

    Both, always. Handing a renderer a bare integer means the renderer formats
    it, which means every renderer formats it, which means they disagree -- and
    a lesson where the chart says EC$1,234.5 and the caption says EC$1234.50 is
    a lesson about our formatting.
    """

    value: int | float
    display: str
    unit: str
    #: The parts the answer is made of, when showing them is the lesson.
    #: `compound_interest` puts `contributed` and `earned` here, which is what
    #: `growth_stack` colours differently.
    breakdown: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FormulaSpec:
    """One registry entry: what it is called, what it needs, who may have it."""

    name: str
    fn: Callable[..., Result]
    parameters: tuple[str, ...]
    band_min: str
    unit: str
    summary: str


# ── the ten ──────────────────────────────────────────────────────────────────


def _cents(value: Decimal) -> int:
    """A Decimal amount to whole cents, half up.

    The single place rounding happens. Every function below computes in Decimal
    and calls this once, at the end -- rounding in the middle of a projection is
    how a fifty-period sum drifts by a dollar.
    """
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def simple_interest(principal: int, rate: float, years: float) -> Result:
    """Interest that does not itself earn interest. `P x r x t`.

    The 9-12 formula, and the one worth teaching first: it is the baseline that
    makes compounding visible when the two are put side by side.
    """
    interest = Decimal(int(principal)) * Decimal(str(rate)) * Decimal(str(years))
    total = int(principal) + _cents(interest)
    return Result(
        value=total,
        display=money_display(total),
        unit="xcd_cents",
        breakdown={
            "principal": int(principal),
            "earned": _cents(interest),
            "earned_display": money_display(_cents(interest)),
        },
    )


def compound_interest(
    principal: int,
    contribution: int,
    rate: float,
    years: float,
    compounds_per_year: int = 1,
) -> Result:
    """Principal plus a regular contribution, compounding.

    `contribution` is paid once per compounding period, at the END of it --
    an ordinary annuity. That is the conservative convention and it matches how
    a standing order into a savings account actually behaves; assuming payment
    at the start would overstate every projection by one period of growth.

    The zero-rate case is handled separately rather than by letting the general
    formula divide by `r`. It is not an edge case to tolerate -- a savings
    account paying nothing is the comparison the whole lesson turns on.
    """
    n = max(1, int(compounds_per_year))
    periods = int(Decimal(str(years)) * n)
    per_period = Decimal(str(rate)) / n

    p = Decimal(int(principal))
    c = Decimal(int(contribution))

    if per_period == 0:
        total = p + c * periods
    else:
        growth = (Decimal(1) + per_period) ** periods
        total = p * growth + c * (growth - Decimal(1)) / per_period

    total_cents = _cents(total)
    contributed = int(principal) + int(contribution) * periods
    earned = total_cents - contributed
    return Result(
        value=total_cents,
        display=money_display(total_cents),
        unit="xcd_cents",
        breakdown={
            "contributed": contributed,
            "contributed_display": money_display(contributed),
            "earned": earned,
            "earned_display": money_display(earned),
            "periods": periods,
        },
    )


def savings_goal_time(goal: int, per_period: int, rate: float = 0.0) -> Result:
    """How many periods of saving `per_period` reach `goal`.

    Computed by *simulating* the periods rather than by solving a logarithm, and
    that is a deliberate choice. The closed form needs `ln`, which needs floats,
    on a quantity denominated in cents -- and the answer a child checks is
    "after how many weeks does the counter pass EC$100?", which is exactly what
    the simulation answers. The two disagree at the boundary; the simulation is
    the one that matches the passbook.

    Returns `MAX_PERIODS` and marks `reached=False` when the goal is
    unreachable, rather than looping. Saving nothing forever is a legitimate
    thing for a slider to be set to.
    """
    goal = int(goal)
    per_period = int(per_period)
    if goal <= 0:
        return Result(value=0, display="0", unit="count", breakdown={"reached": True})

    balance = Decimal(0)
    step = Decimal(per_period)
    factor = Decimal(1) + Decimal(str(rate))
    for period in range(1, MAX_PERIODS + 1):
        balance = balance * factor + step
        if _cents(balance) >= goal:
            return Result(
                value=period,
                display=f"{period}",
                unit="count",
                breakdown={"reached": True, "balance": _cents(balance)},
            )

    return Result(
        value=MAX_PERIODS,
        display=f"more than {MAX_PERIODS}",
        unit="count",
        breakdown={"reached": False, "balance": _cents(balance)},
    )


def savings_goal_amount(goal: int, periods: int, rate: float = 0.0) -> Result:
    """How much per period reaches `goal` in `periods`.

    Rounded UP, always. Rounding to nearest would produce an amount that lands
    a cent short of the goal, and "save this much and you will *almost* have
    your bicycle" is not the lesson.
    """
    goal = int(goal)
    periods = max(1, int(periods))
    r = Decimal(str(rate))

    if r == 0:
        per = Decimal(goal) / periods
    else:
        per = Decimal(goal) * r / ((Decimal(1) + r) ** periods - Decimal(1))

    amount = int(per.quantize(Decimal("1"), rounding=ROUND_CEILING))
    return Result(
        value=amount,
        display=money_display(amount),
        unit="xcd_cents",
        breakdown={"periods": periods, "goal": goal},
    )


def budget_split(total: int, allocations: Mapping[str, int]) -> Result:
    """Split `total` cents by whole-percent shares that must add to 100.

    Uses largest-remainder, so the parts add EXACTLY to the total. Rounding each
    share independently loses or gains a cent or two, and an allocator widget
    whose buckets do not sum to the money on screen is a widget a child will
    notice before an adult does.
    """
    total = int(total)
    shares = {name: int(share) for name, share in allocations.items()}
    if sum(shares.values()) != 100:
        raise ValueError(f"allocations must total 100 percent, got {sum(shares.values())}")

    exact = {name: Decimal(total) * share / 100 for name, share in shares.items()}
    floors = {name: int(value) for name, value in exact.items()}
    remainder = total - sum(floors.values())

    # Biggest fractional part first; ties broken by name so the result is
    # deterministic rather than dict-order dependent.
    order = sorted(
        exact,
        key=lambda name: (-(exact[name] - floors[name]), name),
    )
    for name in order[:remainder]:
        floors[name] += 1

    return Result(
        value=total,
        display=money_display(total),
        unit="xcd_cents",
        breakdown={
            "parts": floors,
            "display": {name: money_display(cents) for name, cents in floors.items()},
        },
    )


def inflation_erosion(amount: int, rate: float, years: float) -> Result:
    """What `amount` will buy after `years` of `rate` inflation, in today's money.

    The number that makes "money under the mattress" concrete. 13-15 and up:
    below that the idea that a dollar can shrink without anybody taking it is
    genuinely hard, and `compare` teaches it better than a number does.
    """
    factor = (Decimal(1) + Decimal(str(rate))) ** Decimal(str(years))
    real = Decimal(int(amount)) / factor
    real_cents = _cents(real)
    lost = int(amount) - real_cents
    return Result(
        value=real_cents,
        display=money_display(real_cents),
        unit="xcd_cents",
        breakdown={
            "nominal": int(amount),
            "lost": lost,
            "lost_display": money_display(lost),
        },
    )


def currency_convert(amount: int, from_ccy: str, to_ccy: str) -> Result:
    """Between XCD and USD at the peg. Cents in, cents out."""
    source = from_ccy.upper()
    target = to_ccy.upper()
    if source not in CURRENCIES or target not in CURRENCIES:
        raise ValueError(f"unsupported currency pair {from_ccy}->{to_ccy}")

    value = Decimal(int(amount))
    if source == target:
        converted = value
    elif source == "USD":
        converted = value * XCD_PER_USD
    else:
        converted = value / XCD_PER_USD

    cents = _cents(converted)
    return Result(
        value=cents,
        display=money_display(cents, target),
        unit="xcd_cents",
        breakdown={"rate": str(XCD_PER_USD), "from": source, "to": target},
    )


def loan_payment(principal: int, rate: float, months: int) -> Result:
    """The level monthly payment that clears `principal` over `months`.

    16-18 only. Borrowing is not on a younger band's ladder at all -- "loan" is
    a banned term below 13-15 -- and this exists so that a seventeen-year-old
    being offered credit can see what it costs.
    """
    principal = int(principal)
    months = max(1, int(months))
    monthly = Decimal(str(rate)) / 12

    if monthly == 0:
        payment = Decimal(principal) / months
    else:
        growth = (Decimal(1) + monthly) ** months
        payment = Decimal(principal) * monthly * growth / (growth - Decimal(1))

    cents = _cents(payment)
    total = cents * months
    return Result(
        value=cents,
        display=money_display(cents),
        unit="xcd_cents",
        breakdown={
            "total_repaid": total,
            "total_repaid_display": money_display(total),
            "cost_of_credit": total - principal,
            "cost_of_credit_display": money_display(total - principal),
            "months": months,
        },
    )


def percentage_of(amount: int, pct: float) -> Result:
    """`pct` percent of `amount` cents.

    13-15 and up, because "percent" is a banned term below it. The idea is
    taught at 9-12 as `proportion` -- three coins out of ten -- which is the
    same fact in equipment a nine-year-old already has.
    """
    value = Decimal(int(amount)) * Decimal(str(pct)) / 100
    cents = _cents(value)
    return Result(
        value=cents,
        display=money_display(cents),
        unit="xcd_cents",
        breakdown={"of": int(amount), "pct": pct},
    )


def difference_over_time(
    path_a: Sequence[int], path_b: Sequence[int], periods: int
) -> Result:
    """The gap between two savings paths, period by period.

    The comparison primitive: "saving EC$5 a week" against "saving EC$5 a week
    somewhere it earns", drawn as the widening space between two lines. Shorter
    paths are padded with their own last value rather than with zero -- a path
    that stopped being recorded did not stop existing.
    """
    periods = max(0, min(int(periods), MAX_PERIODS))

    def at(path: Sequence[int], index: int) -> int:
        if not path:
            return 0
        return int(path[min(index, len(path) - 1)])

    gaps = [at(path_b, index) - at(path_a, index) for index in range(periods)]
    final = gaps[-1] if gaps else 0
    return Result(
        value=final,
        display=money_display(final),
        unit="xcd_cents",
        breakdown={"gaps": gaps, "periods": periods},
    )


# ── the registry ─────────────────────────────────────────────────────────────

_SPECS: tuple[FormulaSpec, ...] = (
    FormulaSpec(
        "simple_interest",
        simple_interest,
        ("principal", "rate", "years"),
        "9-12",
        "xcd_cents",
        "Interest that does not itself earn interest.",
    ),
    FormulaSpec(
        "compound_interest",
        compound_interest,
        ("principal", "contribution", "rate", "years", "compounds_per_year"),
        "13-15",
        "xcd_cents",
        "Savings that grow on what they have already grown.",
    ),
    FormulaSpec(
        "savings_goal_time",
        savings_goal_time,
        ("goal", "per_period", "rate"),
        "9-12",
        "count",
        "How long until you reach a goal.",
    ),
    FormulaSpec(
        "savings_goal_amount",
        savings_goal_amount,
        ("goal", "periods", "rate"),
        "9-12",
        "xcd_cents",
        "How much to put away each time to reach a goal.",
    ),
    FormulaSpec(
        "budget_split",
        budget_split,
        ("total", "allocations"),
        "9-12",
        "xcd_cents",
        "Divide an amount into named parts.",
    ),
    FormulaSpec(
        "inflation_erosion",
        inflation_erosion,
        ("amount", "rate", "years"),
        "13-15",
        "xcd_cents",
        "What money will buy later.",
    ),
    FormulaSpec(
        "currency_convert",
        currency_convert,
        ("amount", "from_ccy", "to_ccy"),
        "9-12",
        "xcd_cents",
        "Between EC dollars and US dollars.",
    ),
    FormulaSpec(
        "loan_payment",
        loan_payment,
        ("principal", "rate", "months"),
        "16-18",
        "xcd_cents",
        "The monthly payment on a loan, and what it costs in total.",
    ),
    FormulaSpec(
        "percentage_of",
        percentage_of,
        ("amount", "pct"),
        "13-15",
        "xcd_cents",
        "A percentage of an amount.",
    ),
    FormulaSpec(
        "difference_over_time",
        difference_over_time,
        ("path_a", "path_b", "periods"),
        "9-12",
        "xcd_cents",
        "The widening gap between two paths.",
    ),
)

REGISTRY: dict[str, FormulaSpec] = {spec.name: spec for spec in _SPECS}


def get(name: str) -> FormulaSpec | None:
    return REGISTRY.get(name)


def names() -> tuple[str, ...]:
    return tuple(REGISTRY)


# ── domain probing, for gate 5 ───────────────────────────────────────────────

#: Anything above this is not a savings lesson.
_ABSURD = MAX_MONEY_CENTS


def probe_domain(spec: FormulaSpec, controls: Mapping[str, Any]) -> str | None:
    """Evaluate the formula across the control box. Returns a problem or None.

    Every corner plus every midpoint -- 3^k points for k controls, so at most 81
    evaluations for a four-control simulator. Cheap, and it is the check that
    catches the widget which is fine until a child drags one slider to its end,
    which is the first thing a child does.

    Parameters the controls do not supply are filled from a conservative
    default, so a formula that takes five arguments can be driven by two
    sliders. Those defaults are chosen to be *inert* -- zero contribution, one
    compounding period a year -- so the probe is testing the sliders rather than
    a scenario nobody configured.
    """
    axes: list[list[Any]] = []
    ordered: list[str] = []
    for name in spec.parameters:
        control = controls.get(name)
        if control is None:
            continue
        ordered.append(name)
        low, high = float(control.min), float(control.max)
        axes.append([low, (low + high) / 2, high])

    if not axes:
        return None

    for point in itertools.product(*axes):
        kwargs = dict(_DEFAULTS)
        kwargs.update(dict(zip(ordered, point)))
        call = {name: kwargs[name] for name in spec.parameters if name in kwargs}
        missing = set(spec.parameters) - set(call)
        if missing:
            return f"{spec.name} has no value for {sorted(missing)}"
        try:
            result = spec.fn(**_coerced(spec, call))
        except (ArithmeticError, ValueError, TypeError, OverflowError) as error:
            return f"{spec.name} failed at {call}: {error}"

        value = result.value
        if value != value:  # NaN
            return f"{spec.name} produced NaN at {call}"
        if abs(float(value)) == float("inf"):
            return f"{spec.name} produced infinity at {call}"
        if spec.unit == "xcd_cents" and abs(float(value)) > _ABSURD:
            return f"{spec.name} produced an implausible amount at {call}"
        if spec.unit == "xcd_cents" and value < 0 and spec.name != "difference_over_time":
            return f"{spec.name} produced a negative amount at {call}"
    return None


#: Inert stand-ins for parameters no slider drives.
_DEFAULTS: dict[str, Any] = {
    "principal": 10_000,
    "contribution": 0,
    "rate": 0.0,
    "years": 1,
    "compounds_per_year": 1,
    "goal": 10_000,
    "per_period": 500,
    "periods": 12,
    "total": 10_000,
    "allocations": {"save": 50, "spend": 50},
    "amount": 10_000,
    "from_ccy": "XCD",
    "to_ccy": "USD",
    "months": 12,
    "pct": 10.0,
    "path_a": [0],
    "path_b": [0],
}

#: Which parameters must be whole numbers. A slider hands back a float even when
#: its step is 1, and `range()` does not take a float.
_INTEGER_PARAMS = frozenset(
    {
        "principal",
        "contribution",
        "goal",
        "per_period",
        "periods",
        "total",
        "amount",
        "months",
        "compounds_per_year",
    }
)


def _coerced(spec: FormulaSpec, call: dict[str, Any]) -> dict[str, Any]:
    return {
        name: int(value) if name in _INTEGER_PARAMS and isinstance(value, (int, float)) else value
        for name, value in call.items()
    }
