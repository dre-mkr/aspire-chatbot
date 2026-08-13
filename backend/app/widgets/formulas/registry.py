"""Every number a learner sees, computed here."""

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

#: Absolute ceilings.
MAX_MONEY_CENTS = 100_000_000_000  # EC$1bn
MAX_PERIODS = 600  # fifty years of months


def money_display(cents: int, currency: str = "XCD") -> str:
    """`EC$1,234.56`. Grouped, two decimals, never a bare float."""
    sign = "-" if cents < 0 else ""
    whole, part = divmod(abs(int(cents)), 100)
    return f"{sign}{_SYMBOL.get(currency, currency + ' ')}{whole:,}.{part:02d}"


@dataclass(frozen=True, slots=True)
class Result:
    """A computed number and the string a reader should see."""

    value: int | float
    display: str
    unit: str
    #: The parts the answer is made of, when showing them is the lesson.
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
    """A Decimal amount to whole cents, half up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def simple_interest(principal: int, rate: float, years: float) -> Result:
    """Interest that does not itself earn interest."""
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
    """Principal plus a regular contribution, compounding."""
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
    """How many periods of saving `per_period` reach `goal`."""
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
    """How much per period reaches `goal` in `periods`."""
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
    """Split `total` cents by whole-percent shares that must add to 100."""
    total = int(total)
    shares = {name: int(share) for name, share in allocations.items()}
    if sum(shares.values()) != 100:
        raise ValueError(f"allocations must total 100 percent, got {sum(shares.values())}")

    exact = {name: Decimal(total) * share / 100 for name, share in shares.items()}
    floors = {name: int(value) for name, value in exact.items()}
    remainder = total - sum(floors.values())

    # Biggest fractional part first, ties broken by name, so the result is deterministic.
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
    """What `amount` will buy after `years` of `rate` inflation, in today's money."""
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
    """The level monthly payment that clears `principal` over `months`."""
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
    """`pct` percent of `amount` cents."""
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
    """The gap between two savings paths, period by period."""
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
    """Evaluate the formula across the control box."""
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

#: Which parameters must be whole numbers.
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
