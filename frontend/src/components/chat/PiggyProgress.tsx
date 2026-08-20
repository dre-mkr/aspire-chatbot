/** The piggy bank that walks the progress bar, and the coins it catches. */

import { useEffect, useRef, useState } from "react";

/** What the bank just did. Drives one animation, then falls back to idle. */
export type PiggyMood = "idle" | "fed" | "dropped";

/**
 * Progress through a round, drawn as a piggy bank rather than a dot.
 *
 * The bank sits at the player's position on the track and moves as they answer.
 * A coin flies in when they get one right and rolls back out when they do not.
 *
 * Two things it deliberately does not do. It does not empty on a wrong answer:
 * the coins already earned are still earned, and taking them away turns a
 * learning game into a punishment. And its reaction to being wrong is a wobble
 * and a coin leaving, not a shake hard enough to read as anger.
 *
 * Under `prefers-reduced-motion` the movement stops but the STATE does not: the
 * bank still jumps to its new position and the coin count still changes, because
 * both carry information. Only the travel between positions is removed. That
 * follows the rule the stylesheet already sets for the wrong-guess shake — a
 * meaningful animation is replaced, not deleted.
 */
export function PiggyProgress({
	answered,
	total,
	coins,
	mood,
	moodAt,
}: {
	/** How many questions have been resolved. */
	answered: number;
	total: number;
	/** How many were right. The coins actually in the bank. */
	coins: number;
	mood: PiggyMood;
	/**
	 * Bumped by the caller on every answer, right or wrong.
	 *
	 * The trigger, because `mood` is not one: two right answers running set
	 * "fed" over "fed" and an effect watching the value would not fire.
	 */
	moodAt: number;
}) {
	const safeTotal = Math.max(1, total);
	const pct = Math.min(100, (answered / safeTotal) * 100);

	// The mood is a one-shot: it plays, then the bank goes back to idle.
	//
	// Keyed on `moodAt` rather than on `mood`, and that is the whole point. An
	// effect on `mood` alone fires when the VALUE changes, so two right answers
	// running set "fed" over "fed", nothing changes, and the second coin never
	// flies. Right-then-wrong animated and right-then-right did not, which is
	// the sort of bug that looks like a rendering glitch for weeks.
	const [playing, setPlaying] = useState<PiggyMood>("idle");
	const seq = useRef(0);
	// biome-ignore lint/correctness/useExhaustiveDependencies: `moodAt` is the trigger; `mood` is read at that moment
	useEffect(() => {
		if (mood === "idle") return;
		seq.current += 1;
		const mine = seq.current;
		setPlaying(mood);
		const timer = setTimeout(() => {
			if (seq.current === mine) setPlaying("idle");
		}, 900);
		return () => clearTimeout(timer);
	}, [moodAt]);

	return (
		<div className="piggy" data-mood={playing}>
			<div className="piggy__track">
				<div className="piggy__fill" style={{ width: `${pct}%` }} />
				{/* Marks the rungs, so "three of five" is visible and not only counted. */}
				<div className="piggy__rungs" aria-hidden="true">
					{Array.from({ length: safeTotal }, (_, i) => (
						<span
							// biome-ignore lint/suspicious/noArrayIndexKey: rungs are positional; the index IS the identity
							key={`rung-${safeTotal}-${i}`}
							data-done={i < answered || undefined}
						/>
					))}
				</div>

				<div className="piggy__walker" style={{ left: `${pct}%` }}>
					{/* The coin that arrives, or leaves. Rendered only while it moves. */}
					{playing !== "idle" ? (
						<span className="piggy__coin" aria-hidden="true">
							<CoinGlyph />
						</span>
					) : null}
					<span className="piggy__bank" aria-hidden="true">
						<PiggyGlyph />
					</span>
				</div>
			</div>

			{/* The bar is decoration; this is what a screen reader is told. */}
			<p className="piggy__count">
				<span aria-hidden="true">
					<CoinGlyph size={13} />
				</span>
				<span>
					{coins} of {safeTotal}
				</span>
				<span className="sr-only">
					{` coins saved. Question ${Math.min(answered + 1, safeTotal)} of ${safeTotal}.`}
				</span>
			</p>
		</div>
	);
}

function CoinGlyph({ size = 16 }: { size?: number }) {
	return (
		<svg
			width={size}
			height={size}
			viewBox="0 0 16 16"
			aria-hidden="true"
			focusable="false"
		>
			<circle cx="8" cy="8" r="7" fill="var(--coin-face)" />
			<circle
				cx="8"
				cy="8"
				r="7"
				fill="none"
				stroke="var(--coin-edge)"
				strokeWidth="1.4"
			/>
			<path
				d="M8 4.4v7.2M6.2 6.1h3a1.3 1.3 0 0 1 0 2.6h-2.4a1.3 1.3 0 0 0 0 2.6h3"
				fill="none"
				stroke="var(--coin-edge)"
				strokeWidth="1.3"
				strokeLinecap="round"
			/>
		</svg>
	);
}

/** A piggy bank, drawn rather than emoji so it inherits the brand's colours. */
function PiggyGlyph() {
	return (
		<svg
			width="34"
			height="30"
			viewBox="0 0 34 30"
			aria-hidden="true"
			focusable="false"
		>
			{/* Ear */}
			<path d="M9.5 6.5 12.5 3l1.6 4.2z" fill="var(--piggy-dark)" />
			{/* Body */}
			<ellipse cx="16" cy="16.5" rx="12.5" ry="9.5" fill="var(--piggy)" />
			{/* Snout */}
			<ellipse cx="28" cy="17" rx="4.4" ry="3.6" fill="var(--piggy-dark)" />
			<circle cx="27" cy="17" r="0.85" fill="var(--piggy-deep)" />
			<circle cx="29.4" cy="17" r="0.85" fill="var(--piggy-deep)" />
			{/* Coin slot */}
			<rect
				x="12"
				y="8"
				width="9"
				height="1.9"
				rx="0.95"
				fill="var(--piggy-deep)"
			/>
			{/* Eye */}
			<circle cx="21.5" cy="13.5" r="1.25" fill="var(--piggy-deep)" />
			{/* Legs */}
			<rect
				x="8"
				y="24"
				width="3.4"
				height="4"
				rx="1.4"
				fill="var(--piggy-dark)"
			/>
			<rect
				x="19"
				y="24"
				width="3.4"
				height="4"
				rx="1.4"
				fill="var(--piggy-dark)"
			/>
			{/* Tail */}
			<path
				d="M3.6 13.5c-2 .4-2.4 2.6-.6 3.2"
				fill="none"
				stroke="var(--piggy-dark)"
				strokeWidth="1.7"
				strokeLinecap="round"
			/>
		</svg>
	);
}
