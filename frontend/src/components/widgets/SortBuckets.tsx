/** Things tapped into categories. */
import { useState } from "react";
import type { SortBucketsWidget } from "../../lib/stream/types";
import {
	A11yText,
	Panel,
	tone,
	useReducedMotion,
	WidgetActions,
} from "./primitives";

export function SortBuckets({
	widget,
	onDone,
	onSkip,
}: {
	widget: SortBucketsWidget;
	onDone: (state: Record<string, string>) => void;
	onSkip: () => void;
}) {
	/** Which item the child is holding. One at a time, like a hand. */
	const [held, setHeld] = useState<string | null>(null);
	const [placed, setPlaced] = useState<Record<string, string>>({});
	const [revealed, setRevealed] = useState(false);
	const reduced = useReducedMotion();

	const unplaced = widget.items.filter((item) => !(item.id in placed));

	const drop = (bucketId: string) => {
		if (!held) return;
		setPlaced((current) => ({ ...current, [held]: bucketId }));
		setHeld(null);
	};

	return (
		<Panel
			title={widget.title}
			caption={widget.caption || widget.prompt}
			a11yText={widget.a11y_text}
			footer={
				<WidgetActions
					onDone={() => {
						setRevealed(true);
						onDone(placed);
					}}
					onSkip={onSkip}
				/>
			}
		>
			{/* The things still to sort. */}
			<div
				style={{
					display: "flex",
					flexWrap: "wrap",
					gap: "0.5rem",
					marginBlockEnd: "0.875rem",
					minHeight: "var(--band-target, 44px)",
				}}
			>
				{unplaced.length === 0 ? (
					<p
						style={{
							margin: 0,
							color: "var(--quiet)",
							fontSize: "var(--band-type, 16px)",
						}}
					>
						All sorted.
					</p>
				) : (
					unplaced.map((item) => {
						const holding = held === item.id;
						const colours = tone(holding ? "accent" : "neutral");
						return (
							<button
								key={item.id}
								type="button"
								// The selection state, announced rather than only drawn.
								aria-pressed={holding}
								onClick={() => setHeld(holding ? null : item.id)}
								style={{
									minHeight: "var(--band-target, 44px)",
									minWidth: "44px",
									padding: "0.5rem 0.875rem",
									borderRadius: "0.75rem",
									border: `2px solid ${colours.line}`,
									background: colours.fill,
									color: colours.ink,
									fontSize: "var(--band-type, 16px)",
									fontWeight: holding ? 700 : 500,
									cursor: "pointer",
									transition: reduced
										? undefined
										: "background-color 160ms ease",
								}}
							>
								{item.label}
							</button>
						);
					})
				)}
			</div>

			{/* Where they go. */}
			<div
				style={{
					display: "grid",
					gridTemplateColumns: `repeat(${Math.min(widget.buckets.length, 2)}, 1fr)`,
					gap: "0.5rem",
				}}
			>
				{widget.buckets.map((bucket) => {
					const inside = widget.items.filter(
						(item) => placed[item.id] === bucket.id,
					);
					const colours = tone(bucket.colour);
					return (
						<button
							key={bucket.id}
							type="button"
							disabled={!held}
							onClick={() => drop(bucket.id)}
							// Named for what tapping it does right now, so a screen reader user is not told "Need" nine times with no indic…
							aria-label={held ? `Put it in ${bucket.label}` : bucket.label}
							style={{
								minHeight: "5.5rem",
								padding: "0.625rem",
								borderRadius: "0.875rem",
								border: `2px ${held ? "solid" : "dashed"} ${colours.line}`,
								background: colours.fill,
								color: colours.ink,
								textAlign: "left",
								cursor: held ? "pointer" : "default",
								opacity: held ? 1 : 0.85,
								transition: reduced ? undefined : "opacity 160ms ease",
							}}
						>
							<span
								style={{
									display: "block",
									fontWeight: 700,
									fontSize: "var(--band-type, 16px)",
								}}
							>
								{bucket.label}
							</span>
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

							<span
								style={{
									display: "flex",
									flexWrap: "wrap",
									gap: "0.25rem",
									marginBlockStart: "0.5rem",
								}}
							>
								{inside.map((item) => {
									// Only after "Got it", and `caution` rather than `danger`: not-yet-right, never wrong.
									const misplaced =
										revealed &&
										item.belongs_to !== null &&
										item.belongs_to !== bucket.id;
									return (
										<span
											key={item.id}
											style={{
												padding: "0.125rem 0.5rem",
												borderRadius: "999px",
												fontSize: "calc(var(--band-type, 16px) - 3px)",
												background: tone(misplaced ? "caution" : "muted").fill,
												border: `1px solid ${tone(misplaced ? "caution" : "muted").line}`,
											}}
										>
											{item.label}
										</span>
									);
								})}
							</span>
						</button>
					);
				})}
			</div>

			{/* The state a sighted child reads from the layout, in words. */}
			<A11yText>
				{held
					? `Holding ${widget.items.find((item) => item.id === held)?.label}. Choose a group for it.`
					: `${unplaced.length} left to sort.`}
			</A11yText>

			<p
				aria-live="polite"
				style={{
					marginBlockStart: "0.5rem",
					fontSize: "calc(var(--band-type, 16px) - 2px)",
					color: "var(--quiet)",
				}}
			>
				{held
					? "Now tap where it goes."
					: unplaced.length > 0
						? "Tap a thing to pick it up."
						: "Tap Got it when you are ready."}
			</p>
		</Panel>
	);
}
