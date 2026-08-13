/** Two or three panels, each hiding its answer until tapped. */
import { useState } from "react";
import type { CompareWidget } from "../../lib/stream/types";
import { Panel, tone, useReducedMotion, WidgetActions } from "./primitives";

export function Compare({
	widget,
	onDone,
	onSkip,
}: {
	widget: CompareWidget;
	onDone: (state: Record<string, boolean>) => void;
	onSkip: () => void;
}) {
	const [revealed, setRevealed] = useState<Array<boolean>>(() =>
		widget.panels.map(() => false),
	);
	const reduced = useReducedMotion();

	const flip = (index: number) => {
		setRevealed((current) =>
			current.map((value, position) => (position === index ? !value : value)),
		);
	};

	return (
		<Panel
			title={widget.title}
			caption={widget.caption || widget.prompt}
			a11yText={widget.a11y_text}
			footer={
				<WidgetActions
					onDone={() =>
						onDone(
							Object.fromEntries(
								widget.panels.map((panel, index) => [
									panel.label,
									revealed[index],
								]),
							),
						)
					}
					onSkip={onSkip}
				/>
			}
		>
			<div
				style={{
					display: "grid",
					gridTemplateColumns: `repeat(${widget.panels.length}, 1fr)`,
					gap: "0.5rem",
				}}
			>
				{widget.panels.map((panel, index) => {
					const colours = tone(
						widget.highlight === index ? "accent" : panel.colour,
					);
					const open = revealed[index];
					return (
						<button
							key={panel.label}
							type="button"
							aria-expanded={open}
							onClick={() => flip(index)}
							style={{
								minHeight: "var(--band-target, 44px)",
								padding: "0.75rem",
								borderRadius: "0.875rem",
								border: `2px solid ${colours.line}`,
								background: colours.fill,
								color: colours.ink,
								textAlign: "left",
								cursor: "pointer",
								fontSize: "var(--band-type, 16px)",
								transition: reduced ? undefined : "background-color 180ms ease",
							}}
						>
							<span style={{ display: "block", fontWeight: 700 }}>
								{panel.label}
							</span>
							<span
								style={{
									display: "block",
									marginBlockStart: "0.25rem",
									fontSize: "calc(var(--band-type, 16px) - 1px)",
								}}
							>
								{panel.summary}
							</span>
							{open ? (
								<span
									style={{
										display: "block",
										marginBlockStart: "0.5rem",
										paddingBlockStart: "0.5rem",
										borderTop: "1px solid var(--hairline)",
										fontWeight: 600,
									}}
								>
									{panel.detail}
								</span>
							) : (
								// A hint, not a control: the whole panel is already the button.
								<span
									aria-hidden="true"
									style={{
										display: "block",
										marginBlockStart: "0.5rem",
										color: "var(--faint)",
										fontSize: "calc(var(--band-type, 16px) - 2px)",
									}}
								>
									Tap to see
								</span>
							)}
						</button>
					);
				})}
			</div>
		</Panel>
	);
}
