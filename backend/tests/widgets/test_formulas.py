"""Golden values, hand-verified, plus the edges every one of them has.

Every expected number below was computed independently and written down; none
was produced by running the code and pasting the output. That distinction is
the whole value of a golden test -- a test that records what the code does
proves the code is deterministic, not that it is right.

The arithmetic each case rests on is given in its docstring so a reader can
re-derive it without trusting this file either.
"""

from __future__ import annotations

import pytest

from app.widgets.formulas import expression as expr
from app.widgets.formulas import registry as reg


class TestMoneyFormatting:
    @pytest.mark.parametrize(
        ("cents", "text"),
        [
            (0, "EC$0.00"),
            (5, "EC$0.05"),
            (100, "EC$1.00"),
            (123_456, "EC$1,234.56"),
            (-2_500, "-EC$25.00"),
            (100_000_000, "EC$1,000,000.00"),
        ],
    )
    def test_display(self, cents, text):
        assert reg.money_display(cents) == text

    def test_usd_uses_its_own_symbol(self):
        assert reg.money_display(1_000, "USD") == "US$10.00"


class TestSimpleInterest:
    def test_ten_percent_on_a_hundred_for_three_years(self):
        """EC$100 x 0.10 x 3 = EC$30 interest, EC$130 total."""
        result = reg.simple_interest(10_000, 0.10, 3)
        assert result.value == 13_000
        assert result.display == "EC$130.00"
        assert result.breakdown["earned"] == 3_000

    def test_zero_rate_returns_the_principal(self):
        assert reg.simple_interest(10_000, 0.0, 10).value == 10_000

    def test_zero_years_returns_the_principal(self):
        assert reg.simple_interest(10_000, 0.10, 0).value == 10_000

    def test_rounding_is_half_up_not_bankers(self):
        """EC$1.00 at 2.5% for one year is 2.5 cents.

        Python's default rounding would give 2 (round-half-to-even); a bank
        gives 3. The child comparing our number to their passbook must find
        them equal.
        """
        assert reg.simple_interest(100, 0.025, 1).breakdown["earned"] == 3


class TestCompoundInterest:
    def test_a_hundred_at_five_percent_for_two_years(self):
        """100 x 1.05^2 = 110.25, so 11_025 cents."""
        result = reg.compound_interest(10_000, 0, 0.05, 2, 1)
        assert result.value == 11_025
        assert result.breakdown["earned"] == 1_025

    def test_contributions_are_an_ordinary_annuity(self):
        """No principal, EC$100 a year for 3 years at 10%.

        Paid at the END of each period: 100(1.1^2) + 100(1.1) + 100
        = 121 + 110 + 100 = 331. Paying at the start would give 364.10, and
        overstating every projection by one period of growth is exactly the
        error a savings product must not make.
        """
        result = reg.compound_interest(0, 10_000, 0.10, 3, 1)
        assert result.value == 33_100
        assert result.breakdown["contributed"] == 30_000
        assert result.breakdown["earned"] == 3_100

    def test_zero_rate_is_pure_addition(self):
        """The comparison the whole lesson turns on, and not an edge case."""
        result = reg.compound_interest(10_000, 5_000, 0.0, 4, 1)
        assert result.value == 10_000 + 5_000 * 4
        assert result.breakdown["earned"] == 0

    def test_monthly_compounding(self):
        """EC$1,000 at 12% compounded monthly for one year.

        1000 x (1.01)^12 = 1126.825..., so 112_683 cents at half-up.
        """
        result = reg.compound_interest(100_000, 0, 0.12, 1, 12)
        assert result.value == 112_683

    def test_one_period(self):
        assert reg.compound_interest(10_000, 0, 0.05, 1, 1).value == 10_500

    def test_zero_contribution_and_zero_principal_is_zero(self):
        assert reg.compound_interest(0, 0, 0.05, 10, 1).value == 0


class TestSavingsGoalTime:
    def test_five_dollars_a_week_towards_fifty(self):
        """EC$5 a week, no interest, EC$50 goal: ten weeks exactly."""
        result = reg.savings_goal_time(5_000, 500, 0.0)
        assert result.value == 10
        assert result.breakdown["reached"] is True

    def test_a_part_period_counts_as_a_whole_one(self):
        """EC$3 a week towards EC$10 passes the goal during week four."""
        assert reg.savings_goal_time(1_000, 300, 0.0).value == 4

    def test_interest_shortens_it(self):
        with_interest = reg.savings_goal_time(100_000, 5_000, 0.10).value
        without = reg.savings_goal_time(100_000, 5_000, 0.0).value
        assert with_interest < without

    def test_saving_nothing_never_arrives_and_does_not_hang(self):
        """A slider CAN be dragged to zero. That must terminate."""
        result = reg.savings_goal_time(10_000, 0, 0.0)
        assert result.breakdown["reached"] is False
        assert result.value == reg.MAX_PERIODS

    def test_a_zero_goal_is_already_met(self):
        assert reg.savings_goal_time(0, 500).value == 0


class TestSavingsGoalAmount:
    def test_a_hundred_over_ten_periods_with_no_interest(self):
        assert reg.savings_goal_amount(10_000, 10, 0.0).value == 1_000

    def test_it_rounds_up_so_the_goal_is_actually_reached(self):
        """EC$10 over 3 periods is 333.33 cents; 334 is the answer that works.

        Rounding to nearest gives 333, and 333 x 3 = 999 -- one cent short of
        the bicycle.
        """
        assert reg.savings_goal_amount(1_000, 3, 0.0).value == 334

    def test_interest_reduces_the_amount_needed(self):
        assert reg.savings_goal_amount(100_000, 10, 0.10).value < reg.savings_goal_amount(
            100_000, 10, 0.0
        ).value

    def test_one_period(self):
        assert reg.savings_goal_amount(10_000, 1, 0.0).value == 10_000


class TestBudgetSplit:
    def test_the_parts_add_to_the_total_exactly(self):
        """EC$100 split 33/33/34 -- the case independent rounding loses a cent on."""
        result = reg.budget_split(10_000, {"save": 33, "spend": 33, "share": 34})
        parts = result.breakdown["parts"]
        assert sum(parts.values()) == 10_000

    def test_largest_remainder_is_deterministic(self):
        """An odd cent must go to the same bucket on every run.

        Dict iteration order is stable in Python but the *fractional parts* can
        tie, and a tie broken by hash order would move the cent between runs.
        """
        first = reg.budget_split(10_001, {"a": 50, "b": 50}).breakdown["parts"]
        second = reg.budget_split(10_001, {"a": 50, "b": 50}).breakdown["parts"]
        assert first == second
        assert sum(first.values()) == 10_001

    def test_a_clean_split(self):
        parts = reg.budget_split(10_000, {"save": 50, "spend": 50}).breakdown["parts"]
        assert parts == {"save": 5_000, "spend": 5_000}

    def test_shares_that_do_not_total_a_hundred_are_refused(self):
        with pytest.raises(ValueError):
            reg.budget_split(10_000, {"save": 50, "spend": 40})


class TestInflationErosion:
    def test_a_hundred_at_ten_percent_for_one_year(self):
        """100 / 1.10 = 90.909..., so 9_091 cents at half-up."""
        result = reg.inflation_erosion(10_000, 0.10, 1)
        assert result.value == 9_091
        assert result.breakdown["lost"] == 909

    def test_zero_inflation_changes_nothing(self):
        assert reg.inflation_erosion(10_000, 0.0, 20).value == 10_000

    def test_zero_years_changes_nothing(self):
        assert reg.inflation_erosion(10_000, 0.10, 0).value == 10_000


class TestCurrencyConvert:
    def test_usd_to_xcd_at_the_peg(self):
        """US$100 x 2.70 = EC$270."""
        result = reg.currency_convert(10_000, "USD", "XCD")
        assert result.value == 27_000
        assert result.display == "EC$270.00"

    def test_xcd_to_usd_at_the_peg(self):
        """EC$270 / 2.70 = US$100."""
        assert reg.currency_convert(27_000, "XCD", "USD").value == 10_000

    def test_the_same_currency_is_the_identity(self):
        assert reg.currency_convert(1_234, "XCD", "XCD").value == 1_234

    def test_case_is_ignored(self):
        assert reg.currency_convert(10_000, "usd", "xcd").value == 27_000

    def test_an_unsupported_pair_is_refused(self):
        with pytest.raises(ValueError):
            reg.currency_convert(100, "GBP", "XCD")


class TestLoanPayment:
    def test_a_thousand_over_twelve_months_at_twelve_percent(self):
        """i = 0.01, n = 12. P x i x 1.01^12 / (1.01^12 - 1) = 88.8488...

        So 8_885 cents at half-up, and EC$106.62 repaid in total.
        """
        result = reg.loan_payment(100_000, 0.12, 12)
        assert result.value == 8_885
        assert result.breakdown["total_repaid"] == 8_885 * 12
        assert result.breakdown["cost_of_credit"] == 8_885 * 12 - 100_000

    def test_zero_interest_is_the_principal_divided_by_the_term(self):
        assert reg.loan_payment(120_000, 0.0, 12).value == 10_000

    def test_one_month(self):
        assert reg.loan_payment(10_000, 0.0, 1).value == 10_000


class TestPercentageOf:
    @pytest.mark.parametrize(
        ("amount", "pct", "expected"),
        [(10_000, 10, 1_000), (10_000, 0, 0), (10_000, 100, 10_000), (333, 50, 167)],
    )
    def test_values(self, amount, pct, expected):
        assert reg.percentage_of(amount, pct).value == expected


class TestDifferenceOverTime:
    def test_the_gap_widens(self):
        result = reg.difference_over_time([100, 200, 300], [100, 250, 450], 3)
        assert result.breakdown["gaps"] == [0, 50, 150]
        assert result.value == 150

    def test_a_short_path_holds_its_last_value(self):
        """A path that stopped being recorded did not stop existing."""
        result = reg.difference_over_time([100], [100, 200, 300], 3)
        assert result.breakdown["gaps"] == [0, 100, 200]

    def test_zero_periods(self):
        assert reg.difference_over_time([1], [2], 0).value == 0

    def test_empty_paths(self):
        assert reg.difference_over_time([], [], 3).value == 0


class TestTheRegistryItself:
    def test_all_ten_are_present(self):
        assert len(reg.names()) == 10

    def test_every_spec_names_a_real_band(self):
        from app.graph.state import AGE_BANDS

        for spec in reg.REGISTRY.values():
            assert spec.band_min in AGE_BANDS, spec.name

    def test_every_specs_parameters_match_its_function(self):
        """A spec that lists the wrong parameters passes gate 5 and then fails.

        The mismatch surfaces at call time, in production, inside a widget --
        which is the least legible place available.
        """
        import inspect

        for spec in reg.REGISTRY.values():
            actual = tuple(inspect.signature(spec.fn).parameters)
            assert spec.parameters == actual, spec.name

    def test_loan_payment_is_sixteen_plus(self):
        """"loan" is a banned term below 13-15. The formula follows the word."""
        assert reg.get("loan_payment").band_min == "16-18"

    def test_compound_interest_is_thirteen_plus(self):
        assert reg.get("compound_interest").band_min == "13-15"

    def test_an_unknown_name_is_none_rather_than_an_error(self):
        assert reg.get("magic_money") is None


# ── expression.py ────────────────────────────────────────────────────────────


class _Control:
    """The minimum a control needs to look like for a domain probe."""

    def __init__(self, low: float, high: float) -> None:
        self.min = low
        self.max = high


CONTROLS = {"weekly": _Control(100, 2_000), "weeks": _Control(1, 52)}


class TestExpressionRejects:
    """The attacks, each named, each rejected."""

    @pytest.mark.parametrize(
        "source",
        [
            "__import__('os').system('rm -rf /')",
            "__import__",
            "().__class__.__bases__[0].__subclasses__()",
            "weekly.__class__",
            "weekly.real",
            "weekly[0]",
            "[x for x in range(10)]",
            "(lambda: 1)()",
            "{'a': 1}",
            "'string'",
            "f'{weekly}'",
            "weekly if weeks else 0",
            "open('/etc/passwd')",
            "exec('x=1')",
            "eval('1')",
            "globals()",
            "weekly := 5",
            "weekly and weeks",
            "not weekly",
            "weekly > weeks",
            "yield weekly",
            "await weekly",
        ],
    )
    def test_the_ast_allowlist_holds(self, source):
        assert expr.check(source, CONTROLS) is not None, source

    def test_an_undeclared_name_is_refused(self):
        assert "not one of this widget's controls" in expr.check("mystery * 2", CONTROLS)

    def test_a_huge_exponent_is_refused_statically(self):
        """`2 ** 10000` is valid arithmetic and a denial of service."""
        assert "exponent" in expr.check("weekly ** 10000", CONTROLS)

    def test_a_non_literal_exponent_is_refused(self):
        assert "exponent" in expr.check("weekly ** weeks", CONTROLS)

    def test_a_long_expression_is_refused(self):
        assert expr.check("weekly + " * 60 + "1", CONTROLS) is not None

    def test_an_empty_expression_is_refused(self):
        assert expr.check("", CONTROLS) is not None
        assert expr.check("   ", CONTROLS) is not None

    def test_booleans_are_not_numbers(self):
        assert expr.check("True * weekly", CONTROLS) is not None


class TestExpressionDomain:
    def test_a_sound_expression_passes(self):
        assert expr.check("weekly * weeks", CONTROLS) is None

    def test_the_allowed_functions_pass(self):
        assert expr.check("min(weekly, 500) * max(weeks, 1)", CONTROLS) is None
        assert expr.check("round(abs(weekly) / 100)", CONTROLS) is None
        assert expr.check("ceil(weekly / 7) + floor(weeks / 2)", CONTROLS) is None

    def test_a_division_that_only_fails_at_one_corner_is_caught(self):
        """The whole reason the domain is swept rather than spot-checked.

        `weekly / share` is finite and positive across the entire range except
        at `share = 0` -- the left end of the slider, which is the first place a
        child puts it. A spot check at the defaults would pass this expression.
        """
        controls = {"weekly": _Control(100, 2_000), "share": _Control(0, 10)}
        problem = expr.check("weekly / share", controls)
        assert problem is not None and "zero" in problem

    def test_an_expression_that_can_go_negative_is_refused(self):
        assert "negative" in expr.check("weekly - 5000", CONTROLS)

    def test_an_implausible_magnitude_is_refused(self):
        assert "implausible" in expr.check("weekly ** 4", CONTROLS)

    def test_no_controls_means_no_expression(self):
        assert expr.check("1 + 1", {}) is not None

    def test_evaluation_matches_python_arithmetic(self):
        tree = expr.parse("weekly * weeks + 100", {"weekly", "weeks"})
        assert expr.evaluate(tree, {"weekly": 500, "weeks": 4}) == 2_100
