/**
 * A hand-verified mirror of `backend/app/widgets/formulas/registry.py`.
 *
 * ## Why a mirror at all
 *
 * A slider has to recompute on every drag frame. Round-tripping that to the
 * server would put 60 requests a second behind a child's thumb, so the client
 * computes for display.
 *
 * ## The client is never the source of truth
 *
 * Every number that MATTERS -- the one the agent quotes back, the one that goes
 * into mastery, the one on a projection the parent reads -- is computed on the
 * server. This module exists so the slider feels immediate, and its output is
 * thrown away the moment the interaction settles and the server answers.
 *
 * That is why a divergence here is a display bug rather than a correctness bug,
 * and it is also why the parity test still fails the build: a display that
 * disagrees with the sentence underneath it is how a child learns the app is
 * unreliable.
 *
 * ## Mirror rather than generated
 *
 * The alternative was generating this file from the Python. It was rejected
 * because the generator would have to understand `Decimal`, `ROUND_HALF_UP` and
 * `ROUND_CEILING` well enough to emit correct JavaScript for each -- which is
 * the whole difficulty, moved into a tool nobody reads. A hand-written mirror
 * plus `formulas.parity.test.ts` puts the difficulty where it can be checked.
 *
 * ## Money is integer cents here too
 *
 * Every amount in and out is an integer count of cents. The intermediate
 * arithmetic is in doubles, which is exact for integers below 2^53 and has
 * ~15 significant digits for the exponentials -- comfortably inside a cent at
 * the magnitudes this product deals in. `roundHalfUp` carries an epsilon to
 * absorb the last-bit error so a value that Python's `Decimal` puts exactly on
 * a .5 boundary rounds the same way here.
 */

/** The peg. One US dollar is 2.70 East Caribbean dollars. */
export const XCD_PER_USD = 2.7;

export const MAX_PERIODS = 600;

const SYMBOL: Record<string, string> = { XCD: "EC$", USD: "US$" };

/**
 * Half up, with an epsilon.
 *
 * `Math.round` is half-up for positives and half-DOWN for negatives, which
 * would disagree with Python on any negative amount. The epsilon absorbs the
 * ~1e-10 relative error a chain of exponentials accumulates, so a value the
 * server computes as exactly `x.5` rounds up here too rather than down by one
 * cent because the double landed at `x.4999999999`.
 */
export function roundHalfUp(value: number): number {
	const sign = value < 0 ? -1 : 1;
	return sign * Math.floor(Math.abs(value) + 0.5 + 1e-9);
}

/** Mirrors `registry.money_display`. */
export function moneyDisplay(cents: number, currency = "XCD"): string {
	const sign = cents < 0 ? "-" : "";
	const whole = Math.floor(Math.abs(cents) / 100);
	const part = Math.abs(cents) % 100;
	const symbol = SYMBOL[currency] ?? `${currency} `;
	return `${sign}${symbol}${whole.toLocaleString("en-US")}.${String(part).padStart(2, "0")}`;
}

export interface Result {
	value: number;
	display: string;
	unit: string;
	breakdown: Record<string, number | string | Record<string, number>>;
}

/* ── the ten ────────────────────────────────────────────────────────────── */

export function simpleInterest(
	principal: number,
	rate: number,
	years: number,
): Result {
	const interest = roundHalfUp(principal * rate * years);
	const total = principal + interest;
	return {
		value: total,
		display: moneyDisplay(total),
		unit: "xcd_cents",
		breakdown: {
			principal,
			earned: interest,
			earned_display: moneyDisplay(interest),
		},
	};
}

export function compoundInterest(
	principal: number,
	contribution: number,
	rate: number,
	years: number,
	compoundsPerYear = 1,
): Result {
	const n = Math.max(1, Math.trunc(compoundsPerYear));
	const periods = Math.trunc(years * n);
	const perPeriod = rate / n;

	// The zero-rate branch is not an edge case to tolerate -- a savings account
	// paying nothing is the comparison the whole lesson turns on, and the
	// general formula divides by `r`.
	const total =
		perPeriod === 0
			? principal + contribution * periods
			: principal * (1 + perPeriod) ** periods +
				(contribution * ((1 + perPeriod) ** periods - 1)) / perPeriod;

	const totalCents = roundHalfUp(total);
	const contributed = principal + contribution * periods;
	const earned = totalCents - contributed;
	return {
		value: totalCents,
		display: moneyDisplay(totalCents),
		unit: "xcd_cents",
		breakdown: {
			contributed,
			contributed_display: moneyDisplay(contributed),
			earned,
			earned_display: moneyDisplay(earned),
			periods,
		},
	};
}

/**
 * Simulated period by period, exactly as the server does.
 *
 * The closed form needs a logarithm and disagrees with the simulation at the
 * boundary. The simulation is the one that matches what a child sees in a
 * passbook -- "after how many weeks does the counter pass EC$100?" -- so it is
 * the one both sides implement.
 */
export function savingsGoalTime(
	goal: number,
	perPeriod: number,
	rate = 0,
): Result {
	if (goal <= 0) {
		return { value: 0, display: "0", unit: "count", breakdown: { reached: 1 } };
	}
	let balance = 0;
	const factor = 1 + rate;
	for (let period = 1; period <= MAX_PERIODS; period += 1) {
		balance = balance * factor + perPeriod;
		if (roundHalfUp(balance) >= goal) {
			return {
				value: period,
				display: String(period),
				unit: "count",
				breakdown: { reached: 1, balance: roundHalfUp(balance) },
			};
		}
	}
	return {
		value: MAX_PERIODS,
		display: `more than ${MAX_PERIODS}`,
		unit: "count",
		breakdown: { reached: 0, balance: roundHalfUp(balance) },
	};
}

/** Rounded UP, always -- see the server's note about the bicycle. */
export function savingsGoalAmount(
	goal: number,
	periods: number,
	rate = 0,
): Result {
	const n = Math.max(1, Math.trunc(periods));
	const per = rate === 0 ? goal / n : (goal * rate) / ((1 + rate) ** n - 1);
	const amount = Math.ceil(per - 1e-9);
	return {
		value: amount,
		display: moneyDisplay(amount),
		unit: "xcd_cents",
		breakdown: { periods: n, goal },
	};
}

/**
 * Largest remainder, so the parts add EXACTLY to the total.
 *
 * Rounding each share independently loses or gains a cent, and an allocator
 * whose buckets do not sum to the money on screen is something a child notices
 * before an adult does.
 */
export function budgetSplit(
	total: number,
	allocations: Record<string, number>,
): Result {
	const shares = Object.entries(allocations);
	const sum = shares.reduce((acc, [, share]) => acc + share, 0);
	if (sum !== 100) {
		throw new Error(`allocations must total 100 percent, got ${sum}`);
	}

	const exact = shares.map(
		([name, share]) => [name, (total * share) / 100] as const,
	);
	const parts: Record<string, number> = {};
	for (const [name, value] of exact) parts[name] = Math.floor(value);

	let remainder = total - Object.values(parts).reduce((a, b) => a + b, 0);
	const order = [...exact].sort((a, b) => {
		const fractionA = a[1] - Math.floor(a[1]);
		const fractionB = b[1] - Math.floor(b[1]);
		if (fractionB !== fractionA) return fractionB - fractionA;
		return a[0] < b[0] ? -1 : 1;
	});
	for (const [name] of order) {
		if (remainder <= 0) break;
		parts[name] += 1;
		remainder -= 1;
	}

	return {
		value: total,
		display: moneyDisplay(total),
		unit: "xcd_cents",
		breakdown: { parts },
	};
}

export function inflationErosion(
	amount: number,
	rate: number,
	years: number,
): Result {
	const real = roundHalfUp(amount / (1 + rate) ** years);
	return {
		value: real,
		display: moneyDisplay(real),
		unit: "xcd_cents",
		breakdown: {
			nominal: amount,
			lost: amount - real,
			lost_display: moneyDisplay(amount - real),
		},
	};
}

export function currencyConvert(
	amount: number,
	from: string,
	to: string,
): Result {
	const source = from.toUpperCase();
	const target = to.toUpperCase();
	const converted =
		source === target
			? amount
			: source === "USD"
				? amount * XCD_PER_USD
				: amount / XCD_PER_USD;
	const cents = roundHalfUp(converted);
	return {
		value: cents,
		display: moneyDisplay(cents, target),
		unit: "xcd_cents",
		breakdown: { rate: String(XCD_PER_USD), from: source, to: target },
	};
}

export function loanPayment(
	principal: number,
	rate: number,
	months: number,
): Result {
	const n = Math.max(1, Math.trunc(months));
	const monthly = rate / 12;
	const payment =
		monthly === 0
			? principal / n
			: (principal * monthly * (1 + monthly) ** n) / ((1 + monthly) ** n - 1);
	const cents = roundHalfUp(payment);
	const total = cents * n;
	return {
		value: cents,
		display: moneyDisplay(cents),
		unit: "xcd_cents",
		breakdown: {
			total_repaid: total,
			total_repaid_display: moneyDisplay(total),
			cost_of_credit: total - principal,
			cost_of_credit_display: moneyDisplay(total - principal),
			months: n,
		},
	};
}

export function percentageOf(amount: number, pct: number): Result {
	const cents = roundHalfUp((amount * pct) / 100);
	return {
		value: cents,
		display: moneyDisplay(cents),
		unit: "xcd_cents",
		breakdown: { of: amount, pct },
	};
}

export function differenceOverTime(
	pathA: Array<number>,
	pathB: Array<number>,
	periods: number,
): Result {
	const n = Math.max(0, Math.min(Math.trunc(periods), MAX_PERIODS));
	// A path that stopped being recorded did not stop existing.
	const at = (path: Array<number>, index: number) =>
		path.length === 0 ? 0 : path[Math.min(index, path.length - 1)];

	const gaps: Array<number> = [];
	for (let index = 0; index < n; index += 1) {
		gaps.push(at(pathB, index) - at(pathA, index));
	}
	const final = gaps.length > 0 ? gaps[gaps.length - 1] : 0;
	return {
		value: final,
		display: moneyDisplay(final),
		unit: "xcd_cents",
		breakdown: { periods: n },
	};
}

/** By name, so a `simulator` widget's `formula` string can drive it. */
export const REGISTRY: Record<string, (...args: Array<never>) => Result> = {
	simple_interest: simpleInterest as never,
	compound_interest: compoundInterest as never,
	savings_goal_time: savingsGoalTime as never,
	savings_goal_amount: savingsGoalAmount as never,
	budget_split: budgetSplit as never,
	inflation_erosion: inflationErosion as never,
	currency_convert: currencyConvert as never,
	loan_payment: loanPayment as never,
	percentage_of: percentageOf as never,
	difference_over_time: differenceOverTime as never,
};

/** The parameter order each formula expects, mirroring the Python spec. */
export const PARAMETERS: Record<string, Array<string>> = {
	simple_interest: ["principal", "rate", "years"],
	compound_interest: [
		"principal",
		"contribution",
		"rate",
		"years",
		"compounds_per_year",
	],
	savings_goal_time: ["goal", "per_period", "rate"],
	savings_goal_amount: ["goal", "periods", "rate"],
	budget_split: ["total", "allocations"],
	inflation_erosion: ["amount", "rate", "years"],
	currency_convert: ["amount", "from_ccy", "to_ccy"],
	loan_payment: ["principal", "rate", "months"],
	percentage_of: ["amount", "pct"],
	difference_over_time: ["path_a", "path_b", "periods"],
};

/** Inert stand-ins for parameters no control drives. Mirrors `_DEFAULTS`. */
export const DEFAULTS: Record<string, number | string | Array<number>> = {
	principal: 10000,
	contribution: 0,
	rate: 0,
	years: 1,
	compounds_per_year: 1,
	goal: 10000,
	per_period: 500,
	periods: 12,
	total: 10000,
	amount: 10000,
	from_ccy: "XCD",
	to_ccy: "USD",
	months: 12,
	pct: 10,
	path_a: [0],
	path_b: [0],
};

/** Whole-number parameters. A slider hands back a float even at step 1. */
const INTEGERS = new Set([
	"principal",
	"contribution",
	"goal",
	"per_period",
	"periods",
	"total",
	"amount",
	"months",
	"compounds_per_year",
]);

/**
 * Run a named formula from a control-value map.
 *
 * Returns null for an unknown formula rather than throwing: a widget naming one
 * this build does not have is a deployment-skew problem, and the right answer
 * is to render the widget without a live number rather than to crash the
 * transcript.
 */
export function evaluate(
	name: string,
	values: Record<string, number>,
): Result | null {
	const fn = REGISTRY[name];
	const order = PARAMETERS[name];
	if (!fn || !order) return null;

	const args = order.map((parameter) => {
		const supplied = values[parameter];
		const value = supplied === undefined ? DEFAULTS[parameter] : supplied;
		return INTEGERS.has(parameter) && typeof value === "number"
			? Math.trunc(value)
			: value;
	});
	return (fn as (...a: Array<unknown>) => Result)(...args);
}
