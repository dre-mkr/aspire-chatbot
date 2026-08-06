/**
 * Cards that flip on tap. Question on the front, answer on the back.
 *
 * The cheapest primitive to render and often the right one: it needs no
 * formula, no numbers and no domain checks, so it is what the planner should
 * reach for when the concept is vocabulary rather than arithmetic.
 *
 * The flip is a colour and content change rather than a 3D rotation. A rotation
 * looks better and is a vestibular trigger; the lesson is what is on the back,
 * and it arrives either way.
 */
import { useState } from "react";
import type { RevealCardsWidget } from "../../lib/stream/types";
import { Panel, tone, useReducedMotion, WidgetActions } from "./primitives";

export function RevealCards({
	widget,
	onDone,
	onSkip,
}: {
	widget: RevealCardsWidget;
	onDone: (state: Record<string, boolean>) => void;
	onSkip: () => void;
}) {
	const [flipped, setFlipped] = useState<Array<boolean>>(() =>
		widget.cards.map(() => false),
	);
	const reduced = useReducedMotion();
	const neutral = tone("neutral");
	const accent = tone("accent");

	const turned = flipped.filter(Boolean).length;

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
								widget.cards.map((card, index) => [card.front, flipped[index]]),
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
					gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 9rem), 1fr))",
					gap: "0.5rem",
				}}
			>
				{widget.cards.map((card, index) => {
					const open = flipped[index];
					const colours = open ? accent : neutral;
					return (
						<button
							key={card.front}
							type="button"
							aria-expanded={open}
							onClick={() =>
								setFlipped((current) =>
									current.map((value, position) =>
										position === index ? !value : value,
									),
								)
							}
							style={{
								minHeight: "calc(var(--band-target, 44px) + 1.5rem)",
								padding: "0.75rem",
								borderRadius: "0.875rem",
								border: `2px solid ${colours.line}`,
								background: colours.fill,
								color: colours.ink,
								fontSize: "var(--band-type, 16px)",
								textAlign: "left",
								cursor: "pointer",
								transition: reduced
									? undefined
									: "background-color 200ms ease, border-color 200ms ease",
							}}
						>
							<span style={{ display: "block", fontWeight: 700 }}>
								{card.front}
							</span>
							{open ? (
								<span
									style={{
										display: "block",
										marginBlockStart: "0.5rem",
										fontSize: "calc(var(--band-type, 16px) - 1px)",
									}}
								>
									{card.back}
								</span>
							) : null}
						</button>
					);
				})}
			</div>
			<p
				aria-live="polite"
				style={{
					marginBlockStart: "0.5rem",
					fontSize: "calc(var(--band-type, 16px) - 2px)",
					color: "var(--quiet)",
				}}
			>
				{turned} of {widget.cards.length} turned over
			</p>
		</Panel>
	);
}
