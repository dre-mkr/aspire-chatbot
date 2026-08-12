/** Two coin stacks and a "Next year" button. */
import { useState } from "react";
import { ChevronRightIcon } from "#/components/icons";
import type { GrowthStackWidget } from "../../lib/stream/types";
import { compoundInterest, moneyDisplay } from "../../lib/widgets/formulas";
import { Coin, Panel, WidgetActions } from "./primitives";

/** Above this, one coin stands for several and the caption says so. */
const MAX_COINS = 24;

export function GrowthStack({
	widget,
	onSettle,
	onSkip,
}: {
	widget: GrowthStackWidget;
	onSettle: (
		state: Record<string, number>,
		computed: Record<string, number | string>,
	) => void;
	onSkip: () => void;
}) {
	const [period, setPeriod] = useState(0);

	const result = compoundInterest(
		widget.principal_cents,
		widget.contribution_cents,
		widget.rate,
		Math.max(period, 0),
		1,
	);
	const saved = Number(result.breakdown.contributed ?? 0);
	const earned = Math.max(0, Number(result.breakdown.earned ?? 0));

	const finished = period >= widget.periods;
	const perCoinSaved = coinValue(saved);
	const perCoinEarned = coinValue(Math.max(earned, perCoinSaved));

	const advance = () => {
		const next = Math.min(period + 1, widget.periods);
		setPeriod(next);
		if (next >= widget.periods) {
			const final = compoundInterest(
				widget.principal_cents,
				widget.contribution_cents,
				widget.rate,
				widget.periods,
				1,
			);
			onSettle(
				{ periods: widget.periods },
				{
					total: final.value,
					saved: Number(final.breakdown.contributed ?? 0),
					earned: Number(final.breakdown.earned ?? 0),
					display: final.display,
				},
			);
		}
	};

	return (
		<Panel
			title={widget.title}
			caption={widget.caption}
			a11yText={widget.a11y_text}
			footer={
				<WidgetActions
					// Loud only once there is no year left to run.
					doneTone={finished ? "primary" : "quiet"}
					onDone={() =>
						onSettle(
							{ periods: period },
							{ total: result.value, saved, earned, display: result.display },
						)
					}
					onSkip={onSkip}
				/>
			}
		>
			<div className="w-stats">
				<Stack
					label={widget.saved_label}
					amount={saved}
					coins={Math.round(saved / perCoinSaved)}
					token="neutral"
				/>
				<Stack
					label={widget.earned_label}
					amount={earned}
					coins={Math.round(earned / perCoinEarned)}
					token="accent"
				/>
			</div>

			{perCoinSaved > 100 ? (
				<p className="w-note">Each coin is {moneyDisplay(perCoinSaved)}</p>
			) : null}

			<p aria-live="polite" className="w-running">
				{period === 0
					? `Starting out: ${moneyDisplay(saved)}`
					: `After ${period} ${widget.period_label}${period === 1 ? "" : "s"}: ${result.display}`}
			</p>

			{finished && widget.reveal_line ? (
				// Only after the final period.
				<p className="w-reveal">{widget.reveal_line}</p>
			) : null}

			{finished ? null : (
				<div className="w-advance">
					<button
						type="button"
						onClick={advance}
						className="w-btn w-btn--primary"
					>
						Next {widget.period_label}
						<ChevronRightIcon size={17} />
					</button>
				</div>
			)}
		</Panel>
	);
}

/** Stable ids for a run of identical coins. */
function coinIds(count: number): Array<string> {
	return Array.from({ length: count }, (_, index) => `coin-${index}`);
}

/** Round numbers only, so the caption reads as a price rather than a remainder. */
function coinValue(amount: number): number {
	if (amount <= 0) return 100;
	const raw = amount / MAX_COINS;
	for (const step of [100, 500, 1000, 2500, 5000, 10000, 50000, 100000]) {
		if (raw <= step) return step;
	}
	return 100000;
}

function Stack({
	label,
	amount,
	coins,
	token,
}: {
	label: string;
	amount: number;
	coins: number;
	token: "neutral" | "accent";
}) {
	const shown = Math.max(0, Math.min(coins, MAX_COINS));
	return (
		<div>
			{/* The pile wraps: one column of 24 coins ran ~400px tall. */}
			<div aria-hidden="true" className="w-coins">
				{/* Keyed by a minted id rather than by the loop index. */}
				{coinIds(shown).map((id, index) => (
					<Coin key={id} filled token={token} size={16} delayMs={index * 10} />
				))}
			</div>
			<p className="w-stat__label">{label}</p>
			<p className="w-stat__value" data-token={token}>
				{moneyDisplay(amount)}
			</p>
		</div>
	);
}
