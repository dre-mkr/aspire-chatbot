/**
 * N icons, M of them highlighted. A fraction you can count.
 *
 * ## The word "percent" never appears below 13
 *
 * Enforced twice, and both times deliberately. The backend's gate 6 rejects a
 * widget whose copy uses the word at 5-8 or 9-12 (it is on the banned list for
 * both). This component enforces it a second time in the SUMMARY IT GENERATES
 * -- the "3 out of 10" line is written here, not by the model, so it is this
 * file's job to make sure it never becomes "30%".
 *
 * "Three out of ten coins" is the same fact and is a fact a nine-year-old
 * already has the equipment to hold. A percentage is a second abstraction
 * stacked on the first.
 *
 * The icons are rendered as a plain list of shapes with `aria-hidden`, and the
 * count is stated in text underneath. A screen reader hears "3 of 10 coins are
 * saved" rather than fifty-seven list items.
 */
import { useState } from "react";
import type { ProportionWidget } from "../../lib/stream/types";
import { useAgeBand } from "../chat/AgeBandProvider";
import { Coin, Panel, WidgetActions } from "./primitives";

/** Bands that must never see the word. Matches `safety/vocab.py`. */
const NO_PERCENT = new Set(["5-8", "9-12"]);

export function Proportion({
	widget,
	onDone,
	onSkip,
}: {
	widget: ProportionWidget;
	onDone: (state: Record<string, number>) => void;
	onSkip: () => void;
}) {
	const band = useAgeBand();
	const [counted, setCounted] = useState(false);

	const total = Math.max(1, widget.total);
	const highlighted = Math.min(widget.highlighted, total);
	const allowPercent = !NO_PERCENT.has(band.band);

	const summary = allowPercent
		? `${highlighted} of ${total} — ${Math.round((highlighted / total) * 100)} in every hundred`
		: `${highlighted} out of ${total}`;

	// Icon size shrinks as the count grows so a proportion of 100 still fits at
	// 380px, with a floor that keeps it above a tappable-looking size — these
	// are not controls, and they must not look like they are.
	const size = total > 40 ? 10 : total > 20 ? 14 : 18;

	return (
		<Panel
			title={widget.title}
			caption={widget.caption}
			a11yText={widget.a11y_text}
			footer={
				<WidgetActions
					onDone={() => {
						setCounted(true);
						onDone({ highlighted, total });
					}}
					onSkip={onSkip}
				/>
			}
		>
			<div
				aria-hidden="true"
				style={{
					display: "flex",
					flexWrap: "wrap",
					gap: "0.35rem",
					maxWidth: "100%",
				}}
			>
				{Array.from({ length: total }, (_, index) => `icon-${index}`).map(
					(id, index) => (
						<Coin
							key={id}
							filled={index < highlighted}
							token={index < highlighted ? "accent" : "muted"}
							size={size}
							delayMs={Math.min(index * 12, 280)}
						/>
					),
				)}
			</div>

			<p
				style={{
					marginBlockStart: "0.75rem",
					fontSize: "var(--band-type, 16px)",
					fontWeight: 600,
					color: "var(--plum-deep)",
				}}
			>
				{summary}
			</p>

			{widget.highlighted_label || widget.remainder_label ? (
				<dl
					style={{
						margin: "0.5rem 0 0",
						display: "grid",
						gridTemplateColumns: "auto 1fr",
						gap: "0.25rem 0.5rem",
						fontSize: "calc(var(--band-type, 16px) - 1px)",
						color: "var(--slate)",
					}}
				>
					{widget.highlighted_label ? (
						<>
							<dt style={{ fontWeight: 600 }}>{highlighted}</dt>
							<dd style={{ margin: 0 }}>{widget.highlighted_label}</dd>
						</>
					) : null}
					{widget.remainder_label ? (
						<>
							<dt style={{ fontWeight: 600 }}>{total - highlighted}</dt>
							<dd style={{ margin: 0 }}>{widget.remainder_label}</dd>
						</>
					) : null}
				</dl>
			) : null}

			{counted ? null : null}
		</Panel>
	);
}
