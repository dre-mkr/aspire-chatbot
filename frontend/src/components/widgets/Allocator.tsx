/** A fixed sum split across buckets. */
import { useMemo, useState } from "react";
import type { AllocatorWidget } from "../../lib/stream/types";
import { budgetSplit, moneyDisplay } from "../../lib/widgets/formulas";
import { Bar, Panel, WidgetActions } from "./primitives";

/** One tap moves five percentage points. Fine enough to be expressive. */
const STEP = 5;

export function Allocator({
	widget,
	onSettle,
	onSkip,
}: {
	widget: AllocatorWidget;
	onSettle: (
		state: Record<string, number>,
		computed: Record<string, number | string>,
	) => void;
	onSkip: () => void;
}) {
	const [shares, setShares] = useState<Record<string, number>>(() =>
		Object.fromEntries(widget.buckets.map((b) => [b.id, b.default_share])),
	);
	const parts = useMemo(() => {
		try {
			return budgetSplit(widget.total_cents, shares).breakdown.parts as Record<
				string,
				number
			>;
		} catch {
			// Only reachable if the shares stop summing to 100, which `move` prevents.
			const even = Math.floor(widget.total_cents / widget.buckets.length);
			return Object.fromEntries(widget.buckets.map((b) => [b.id, even]));
		}
	}, [shares, widget.total_cents, widget.buckets]);

	/** Move one bucket, and take the difference from the biggest other one. */
	const move = (id: string, delta: number) => {
		setShares((current) => {
			const next = { ...current };
			const target = Math.max(0, Math.min(100, next[id] + delta));
			const actual = target - next[id];
			if (actual === 0) return current;

			const others = widget.buckets
				.map((b) => b.id)
				.filter((other) => other !== id)
				.sort((a, b) => next[b] - next[a]);

			// Take from the largest, or give to the smallest, whichever the move requires.
			let remaining = actual;
			const order = actual > 0 ? others : [...others].reverse();
			for (const other of order) {
				if (remaining === 0) break;
				const available = actual > 0 ? next[other] : 100 - next[other];
				const taken = Math.min(Math.abs(remaining), available);
				next[other] -= Math.sign(remaining) * taken;
				remaining -= Math.sign(remaining) * taken;
			}
			next[id] = target - remaining;
			return next;
		});
	};

	return (
		<Panel
			title={widget.title}
			caption={widget.caption || widget.prompt}
			a11yText={widget.a11y_text}
			footer={
				<WidgetActions
					onDone={() =>
						onSettle(parts, {
							total: widget.total_cents,
							display: moneyDisplay(widget.total_cents),
						})
					}
					onSkip={onSkip}
				/>
			}
		>
			<p
				style={{
					margin: "0 0 0.75rem",
					fontSize: "var(--band-type, 16px)",
					fontWeight: 700,
					color: "var(--plum-deep)",
				}}
			>
				{moneyDisplay(widget.total_cents)} to split
			</p>

			{widget.buckets.map((bucket) => (
				<div key={bucket.id} style={{ marginBlockEnd: "0.875rem" }}>
					<div
						style={{
							display: "flex",
							alignItems: "center",
							justifyContent: "space-between",
							gap: "0.5rem",
							marginBlockEnd: "0.25rem",
						}}
					>
						<span style={{ fontSize: "var(--band-type, 16px)" }}>
							<strong>{bucket.label}</strong>
							{bucket.hint ? (
								<span
									style={{
										display: "block",
										fontSize: "calc(var(--band-type, 16px) - 3px)",
										color: "var(--quiet)",
									}}
								>
									{bucket.hint}
								</span>
							) : null}
						</span>

						<span
							style={{ display: "flex", alignItems: "center", gap: "0.375rem" }}
						>
							<button
								type="button"
								aria-label={`Less for ${bucket.label}`}
								onClick={() => move(bucket.id, -STEP)}
								style={stepper}
							>
								−
							</button>
							{/* The MONEY, not the percentage. */}
							<output
								aria-live="polite"
								style={{
									minWidth: "5.5rem",
									textAlign: "right",
									fontWeight: 700,
									color: "var(--plum-deep)",
									fontSize: "var(--band-type, 16px)",
								}}
							>
								{moneyDisplay(parts[bucket.id] ?? 0)}
							</output>
							<button
								type="button"
								aria-label={`More for ${bucket.label}`}
								onClick={() => move(bucket.id, STEP)}
								style={stepper}
							>
								+
							</button>
						</span>
					</div>

					<Bar
						fraction={(parts[bucket.id] ?? 0) / Math.max(1, widget.total_cents)}
						token={bucket.colour}
						label=""
					/>
				</div>
			))}

			<p
				style={{
					margin: 0,
					fontSize: "calc(var(--band-type, 16px) - 2px)",
					color: "var(--quiet)",
				}}
			>
				{/* Stated outright. */}
				There is no wrong way to split it.
			</p>
		</Panel>
	);
}

const stepper = {
	width: "var(--band-target, 44px)",
	height: "var(--band-target, 44px)",
	minWidth: "44px",
	minHeight: "44px",
	borderRadius: "50%",
	border: "2px solid var(--plum)",
	background: "var(--wash-6)",
	color: "var(--plum-deep)",
	fontSize: "1.25rem",
	fontWeight: 700,
	lineHeight: 1,
	cursor: "pointer",
} as const;
