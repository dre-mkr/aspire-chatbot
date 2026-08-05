/**
 * Where money goes, as a short sequence of steps.
 *
 * Linear, and that is the whole design. A general graph would need edge routing
 * and a layout engine, and a seven-year-old reading "you get money → some in
 * the tin → some to the shop" needs a line, not a diagram.
 *
 * ## It is a list, and it is marked up as one
 *
 * `<ol>` rather than a row of divs with arrows between them. A screen reader
 * then announces "list, 3 items, item 1 of 3", which is exactly the sequence
 * information the arrows carry visually. The arrows themselves are
 * `aria-hidden` — they are the same fact twice.
 *
 * ## Tap to expand, never to proceed
 *
 * Each step's detail is behind a tap because putting all three on screen at
 * once is more text than the primitive is for. Nothing has to be tapped: the
 * labels alone carry the sequence, which is the lesson.
 */
import { useState } from "react";
import type { FlowDiagramWidget } from "../../lib/stream/types";
import { Panel, tone, useReducedMotion, WidgetActions } from "./primitives";

export function FlowDiagram({
	widget,
	onDone,
	onSkip,
}: {
	widget: FlowDiagramWidget;
	onDone: (state: Record<string, boolean>) => void;
	onSkip: () => void;
}) {
	const [open, setOpen] = useState<Record<string, boolean>>({});
	const reduced = useReducedMotion();

	return (
		<Panel
			title={widget.title}
			caption={widget.caption}
			a11yText={widget.a11y_text}
			footer={<WidgetActions onDone={() => onDone(open)} onSkip={onSkip} />}
		>
			<ol
				style={{
					listStyle: "none",
					margin: 0,
					padding: 0,
					display: "flex",
					flexDirection: "column",
					gap: "0.25rem",
				}}
			>
				{widget.steps.map((step, index) => {
					const colours = tone(step.colour);
					const expanded = Boolean(open[step.id]);
					const edge = widget.edge_labels[index - 1];
					return (
						<li key={step.id}>
							{index > 0 ? (
								<div
									aria-hidden="true"
									style={{
										display: "flex",
										alignItems: "center",
										gap: "0.5rem",
										padding: "0.125rem 0 0.125rem 1rem",
										color: "var(--faint)",
										fontSize: "calc(var(--band-type, 16px) - 3px)",
									}}
								>
									<span style={{ fontSize: "1.1rem", lineHeight: 1 }}>↓</span>
									{edge ? <span>{edge}</span> : null}
								</div>
							) : null}

							<button
								type="button"
								aria-expanded={expanded}
								disabled={!step.detail}
								onClick={() =>
									setOpen((current) => ({
										...current,
										[step.id]: !current[step.id],
									}))
								}
								style={{
									width: "100%",
									minHeight: "var(--band-target, 44px)",
									padding: "0.625rem 0.875rem",
									borderRadius: "0.875rem",
									border: `2px solid ${colours.line}`,
									background: colours.fill,
									color: colours.ink,
									textAlign: "left",
									fontSize: "var(--band-type, 16px)",
									cursor: step.detail ? "pointer" : "default",
									transition: reduced
										? undefined
										: "background-color 160ms ease",
								}}
							>
								<span style={{ fontWeight: 700 }}>{step.label}</span>
								{expanded && step.detail ? (
									<span
										style={{
											display: "block",
											marginBlockStart: "0.25rem",
											fontSize: "calc(var(--band-type, 16px) - 1px)",
										}}
									>
										{step.detail}
									</span>
								) : null}
							</button>
						</li>
					);
				})}
			</ol>
		</Panel>
	);
}
