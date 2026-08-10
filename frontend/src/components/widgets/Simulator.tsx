/** Sliders driving a number that recomputes as they move. */
import { useEffect, useMemo, useRef, useState } from "react";
import type { SimulatorWidget } from "../../lib/stream/types";
import { evaluate, moneyDisplay } from "../../lib/widgets/formulas";
import { Bar, Panel, tone, WidgetActions } from "./primitives";

/** How long a control must be still before the interaction counts as settled. */
const SETTLE_MS = 800;

export function Simulator({
	widget,
	onSettle,
	onSkip,
}: {
	widget: SimulatorWidget;
	onSettle: (
		state: Record<string, number>,
		computed: Record<string, number | string>,
	) => void;
	onSkip: () => void;
}) {
	const [values, setValues] = useState<Record<string, number>>(() =>
		Object.fromEntries(widget.controls.map((c) => [c.id, c.default])),
	);
	const [touched, setTouched] = useState(0);
	const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

	const result = useMemo(
		() => (widget.formula ? evaluate(widget.formula, values) : null),
		[widget.formula, values],
	);

	// Debounced settle.
	useEffect(() => {
		if (touched === 0) return;
		if (timer.current) clearTimeout(timer.current);
		timer.current = setTimeout(() => {
			onSettle(values, {
				value: result?.value ?? 0,
				display: result?.display ?? "",
			});
		}, SETTLE_MS);
		return () => {
			if (timer.current) clearTimeout(timer.current);
		};
	}, [touched, values, result, onSettle]);

	const display =
		result?.display ??
		(widget.output_unit === "xcd_cents" ? moneyDisplay(0) : "—");

	return (
		<Panel
			title={widget.title}
			caption={widget.caption}
			a11yText={widget.a11y_text}
			footer={
				<WidgetActions
					onDone={() =>
						onSettle(values, {
							value: result?.value ?? 0,
							display: result?.display ?? "",
						})
					}
					onSkip={onSkip}
				/>
			}
		>
			{widget.controls.map((control) => (
				<div key={control.id} style={{ marginBlockEnd: "0.875rem" }}>
					<label
						htmlFor={`sim-${widget.concept_id}-${control.id}`}
						style={{
							display: "flex",
							justifyContent: "space-between",
							fontSize: "var(--band-type, 16px)",
							color: "var(--prose)",
							marginBlockEnd: "0.25rem",
						}}
					>
						<span>{control.label}</span>
						<span style={{ fontWeight: 700, color: "var(--plum-deep)" }}>
							{formatControl(control.unit, values[control.id])}
						</span>
					</label>
					<input
						id={`sim-${widget.concept_id}-${control.id}`}
						type="range"
						min={control.min}
						max={control.max}
						step={control.step}
						value={values[control.id]}
						// Both are stated: a screen reader reads `aria-valuetext` where it exists and the raw number where it does not,…
						aria-valuetext={formatControl(control.unit, values[control.id])}
						onChange={(event) => {
							const next = Number(event.target.value);
							setValues((current) => ({ ...current, [control.id]: next }));
							setTouched((count) => count + 1);
						}}
						style={{
							width: "100%",
							// The thumb is the tap target; the track is not.
							minHeight: "var(--band-target, 44px)",
							accentColor: "var(--plum)",
						}}
					/>
				</div>
			))}

			<output
				// `aria-live="polite"` rather than `assertive`: the number changes on every drag frame, and assertive would int…
				aria-live="polite"
				style={{
					display: "block",
					marginBlockStart: "0.5rem",
					padding: "0.75rem",
					borderRadius: "0.75rem",
					background: tone("accent").fill,
					border: `1px solid ${tone("accent").line}`,
				}}
			>
				<span
					style={{
						display: "block",
						fontSize: "calc(var(--band-type, 16px) - 2px)",
						color: "var(--slate)",
					}}
				>
					{widget.output_label}
				</span>
				<span
					style={{
						display: "block",
						fontSize: "calc(var(--band-type, 16px) + 8px)",
						fontWeight: 800,
						color: "var(--plum-deep)",
					}}
				>
					{display}
				</span>
			</output>

			{widget.visual === "stacked_bars" && result ? (
				<div style={{ marginBlockStart: "0.75rem" }}>
					<Bar
						fraction={
							Number(result.breakdown.contributed ?? 0) /
							Math.max(1, result.value)
						}
						token="neutral"
						label={`You put in ${moneyDisplay(Number(result.breakdown.contributed ?? 0))}`}
					/>
					<Bar
						fraction={
							Number(result.breakdown.earned ?? 0) / Math.max(1, result.value)
						}
						token="accent"
						label={`The bank added ${moneyDisplay(Number(result.breakdown.earned ?? 0))}`}
					/>
				</div>
			) : null}

			{widget.visual === "line" && result ? (
				<LineChart widget={widget} values={values} final={result.value} />
			) : null}
		</Panel>
	);
}

function formatControl(unit: string, value: number): string {
	if (unit === "xcd_cents") return moneyDisplay(value);
	if (unit === "rate") return `${(value * 100).toFixed(1)} in every hundred`;
	if (unit === "years") return `${value} year${value === 1 ? "" : "s"}`;
	if (unit === "months") return `${value} month${value === 1 ? "" : "s"}`;
	if (unit === "weeks") return `${value} week${value === 1 ? "" : "s"}`;
	return String(value);
}

/** A minimal inline chart. */
function LineChart({
	widget,
	values,
	final,
}: {
	widget: SimulatorWidget;
	values: Record<string, number>;
	final: number;
}) {
	const periodControl = widget.controls.find((control) =>
		["years", "months", "weeks", "count"].includes(control.unit),
	);
	if (!periodControl || !widget.formula) return null;

	const span = Math.max(1, Math.round(values[periodControl.id]));
	const points: Array<number> = [];
	for (let step = 1; step <= span; step += 1) {
		const result = evaluate(widget.formula, {
			...values,
			[periodControl.id]: step,
		});
		points.push(result?.value ?? 0);
	}

	const peak = Math.max(final, ...points, 1);
	const path = points
		.map((value, index) => {
			const x = (index / Math.max(1, points.length - 1)) * 100;
			const y = 100 - (value / peak) * 100;
			return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
		})
		.join(" ");

	return (
		<svg
			viewBox="0 0 100 100"
			preserveAspectRatio="none"
			role="img"
			aria-label={`A line rising to ${moneyDisplay(final)} over ${span} ${periodControl.unit}`}
			style={{
				width: "100%",
				height: "7rem",
				marginBlockStart: "0.75rem",
				borderRadius: "0.5rem",
				background: "var(--wash-3)",
			}}
		>
			<title>{`Growth over ${span} ${periodControl.unit}`}</title>
			<path
				d={path}
				fill="none"
				stroke="var(--magenta)"
				strokeWidth="2"
				vectorEffect="non-scaling-stroke"
			/>
		</svg>
	);
}
