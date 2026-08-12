/** N icons, M of them highlighted. */
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

	// Shrinks as the count grows so 100 icons still fit at 380px, with a floor.
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
