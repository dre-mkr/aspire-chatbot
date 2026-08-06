/**
 * Two coin stacks and a "Next year" button. The compound-interest widget for 9-12.
 *
 * The child taps, coins drop into both stacks, and the `earned` stack -- in the
 * accent token -- grows faster than the one they are putting money into. That
 * difference IS the lesson, and it is delivered without a percentage, a
 * formula, or the word "compound" appearing anywhere.
 *
 * ## No percentages for band 9-12
 *
 * "5%" is a second abstraction stacked on the first. The rate is in the widget
 * payload because the arithmetic needs it; it is never rendered. `reveal_line`
 * appears only after the final period, so the sentence that names what happened
 * lands after the child has watched it happen rather than before.
 *
 * ## Coins are capped, and the cap is the reason the widget works
 *
 * Fifty periods of contributions is thousands of coins, which is a grey smear.
 * Above `MAX_COINS` each coin represents several, and the caption says so. A
 * stack whose height is unreadable teaches nothing.
 */
import { useState } from "react";
import type { GrowthStackWidget } from "../../lib/stream/types";
import { compoundInterest, moneyDisplay } from "../../lib/widgets/formulas";
import { useAgeBand } from "../chat/AgeBandProvider";
import { Coin, Panel, useReducedMotion, WidgetActions } from "./primitives";

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
	const band = useAgeBand();
	const reduced = useReducedMotion();

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
			<div
				style={{
					display: "grid",
					gridTemplateColumns: "1fr 1fr",
					gap: "0.75rem",
					alignItems: "end",
				}}
			>
				<Stack
					label={widget.saved_label}
					amount={saved}
					coins={Math.round(saved / perCoinSaved)}
					token="neutral"
					reduced={reduced}
				/>
				<Stack
					label={widget.earned_label}
					amount={earned}
					coins={Math.round(earned / perCoinEarned)}
					token="accent"
					reduced={reduced}
				/>
			</div>

			{perCoinSaved > 100 ? (
				<p
					style={{
						marginBlockStart: "0.5rem",
						fontSize: "calc(var(--band-type, 16px) - 3px)",
						color: "var(--faint)",
					}}
				>
					Each coin is {moneyDisplay(perCoinSaved)}
				</p>
			) : null}

			<p
				aria-live="polite"
				style={{
					marginBlockStart: "0.75rem",
					fontSize: "var(--band-type, 16px)",
					fontWeight: 600,
					color: "var(--plum-deep)",
				}}
			>
				{period === 0
					? `Starting out: ${moneyDisplay(saved)}`
					: `After ${period} ${widget.period_label}${period === 1 ? "" : "s"}: ${result.display}`}
			</p>

			{finished && widget.reveal_line ? (
				// Only after the final period. The sentence that names what
				// happened has to land after they have watched it happen.
				<p
					style={{
						marginBlockStart: "0.5rem",
						padding: "0.75rem",
						borderRadius: "0.75rem",
						background: "var(--wash-m-10)",
						fontSize: "var(--band-type, 16px)",
						color: "var(--plum-deep)",
						fontWeight: 600,
					}}
				>
					{widget.reveal_line}
				</p>
			) : null}

			{finished ? null : (
				<button
					type="button"
					onClick={advance}
					style={{
						marginBlockStart: "0.75rem",
						minHeight: `${band.touchTarget}px`,
						width: "100%",
						borderRadius: "0.875rem",
						border: "1px solid var(--plum)",
						background: "var(--plum)",
						color: "white",
						fontSize: "var(--band-type, 16px)",
						fontWeight: 700,
						cursor: "pointer",
					}}
				>
					Next {widget.period_label} ▶
				</button>
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
	reduced,
}: {
	label: string;
	amount: number;
	coins: number;
	token: "neutral" | "accent";
	reduced: boolean;
}) {
	const shown = Math.max(0, Math.min(coins, MAX_COINS));
	return (
		<div>
			<div
				aria-hidden="true"
				style={{
					display: "flex",
					flexDirection: "column-reverse",
					gap: "0.15rem",
					minHeight: "6rem",
					justifyContent: "flex-start",
				}}
			>
				{/* Keyed by a minted id rather than by the loop index. The coins
				    are indistinguishable, so the key is arbitrary -- but an index
				    key on a list that grows is the shape React warns about, and a
				    stable string costs nothing. */}
				{coinIds(shown).map((id, index) => (
					<Coin
						key={id}
						filled
						token={token}
						size={16}
						delayMs={reduced ? 0 : index * 10}
					/>
				))}
			</div>
			<p
				style={{
					margin: "0.5rem 0 0",
					fontSize: "calc(var(--band-type, 16px) - 2px)",
					color: "var(--slate)",
				}}
			>
				{label}
			</p>
			<p
				style={{
					margin: 0,
					fontSize: "var(--band-type, 16px)",
					fontWeight: 700,
					color: token === "accent" ? "var(--magenta)" : "var(--plum-deep)",
				}}
			>
				{moneyDisplay(amount)}
			</p>
		</div>
	);
}
