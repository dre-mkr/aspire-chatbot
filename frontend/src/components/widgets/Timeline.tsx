/** When things happen, and how far apart. */
import { useState } from "react";
import type { TimelineWidget } from "../../lib/stream/types";
import { Panel, tone, useReducedMotion, WidgetActions } from "./primitives";

export function Timeline({
	widget,
	onDone,
	onSkip,
}: {
	widget: TimelineWidget;
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
			{widget.start_label || widget.end_label ? (
				<div
					style={{
						display: "flex",
						justifyContent: "space-between",
						fontSize: "calc(var(--band-type, 16px) - 3px)",
						color: "var(--quiet)",
						marginBlockEnd: "0.375rem",
					}}
				>
					<span>{widget.start_label}</span>
					<span>{widget.end_label}</span>
				</div>
			) : null}

			{/* The drawn track. Decoration: every fact on it is in the list below. */}
			<div
				aria-hidden="true"
				style={{
					position: "relative",
					height: "0.5rem",
					borderRadius: "999px",
					background: "var(--wash-9)",
					marginBlockEnd: "0.875rem",
				}}
			>
				{widget.points.map((point) => (
					<span
						key={`${point.label}-${point.at}`}
						style={{
							position: "absolute",
							left: `${Math.max(0, Math.min(100, point.at))}%`,
							top: "50%",
							width: "0.875rem",
							height: "0.875rem",
							marginInlineStart: "-0.4375rem",
							marginBlockStart: "-0.4375rem",
							borderRadius: "50%",
							/* `.dot`, not `.line`: a `muted` point drawn in the boundary
							   colour sat at 1.02:1 against the track it marks. */
							background: tone(point.colour).dot,
							border: "2px solid var(--wash-3)",
						}}
					/>
				))}
			</div>

			<ol
				style={{
					listStyle: "none",
					margin: 0,
					padding: 0,
					display: "grid",
					gap: "0.375rem",
				}}
			>
				{widget.points.map((point) => {
					const key = `${point.label}-${point.at}`;
					const colours = tone(point.colour);
					const expanded = Boolean(open[key]);
					return (
						<li key={key}>
							<button
								type="button"
								aria-expanded={expanded}
								disabled={!point.caption}
								onClick={() =>
									setOpen((current) => ({ ...current, [key]: !current[key] }))
								}
								style={{
									width: "100%",
									minHeight: "var(--band-target, 44px)",
									display: "flex",
									alignItems: "center",
									gap: "0.625rem",
									padding: "0.5rem 0.75rem",
									borderRadius: "0.75rem",
									border: `1px solid ${colours.line}`,
									background: colours.fill,
									color: colours.ink,
									textAlign: "left",
									fontSize: "var(--band-type, 16px)",
									cursor: point.caption ? "pointer" : "default",
									transition: reduced
										? undefined
										: "background-color 160ms ease",
								}}
							>
								<span
									aria-hidden="true"
									style={{
										width: "0.625rem",
										height: "0.625rem",
										borderRadius: "50%",
										background: colours.dot,
										flexShrink: 0,
									}}
								/>
								<span>
									<span style={{ fontWeight: 700 }}>{point.label}</span>
									{expanded && point.caption ? (
										<span
											style={{
												display: "block",
												fontSize: "calc(var(--band-type, 16px) - 1px)",
											}}
										>
											{point.caption}
										</span>
									) : null}
								</span>
							</button>
						</li>
					);
				})}
			</ol>
		</Panel>
	);
}
