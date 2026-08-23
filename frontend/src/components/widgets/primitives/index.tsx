/** Shared parts every widget is built from: tokens, panel, coin, actions. */
import { type CSSProperties, type ReactNode, useEffect, useState } from "react";
import type { ColourToken } from "../../../lib/stream/types";

export type { ColourToken };

/**
 * The five tokens, as the CSS variables the stylesheet defines.
 *
 * ONE INK, not five. Each token used to carry its own text colour — plum-deep,
 * prose, warn-ink, quiet, prose — so a timeline of three structurally identical
 * points rendered its three labels in three different colours, and a reader
 * learned a colour vocabulary the widget did not mean. The fill and the line
 * are what carry the token's meaning; the words are words. `caution` keeps its
 * own ink because there it is load-bearing for contrast against the warm fill.
 *
 * `line` is a CONTROL BOUNDARY on most of these widgets — the edge of a
 * tappable panel — so it has to clear the 3:1 that WCAG 1.4.11 asks. It was
 * `--hairline` (1.19:1) for `muted` and for the default, which is a boundary
 * nobody can see. `--control-line` is the token the project already keeps for
 * exactly this, and it is 3.0:1 over these fills.
 *
 * `dot` is the same colour at full strength, for the places a token has to be
 * legible as a MARK rather than as a surface — a point on a timeline track,
 * where a 10%-alpha line disappears into the track it sits on.
 */
export function tone(token: ColourToken | undefined): {
	fill: string;
	line: string;
	ink: string;
	dot: string;
} {
	switch (token) {
		case "accent":
			// The money the bank added.
			return {
				fill: "var(--wash-m-16)",
				line: "var(--magenta)",
				ink: "var(--plum-deep)",
				dot: "var(--magenta)",
			};
		case "positive":
			return {
				fill: "color-mix(in srgb, var(--success) 12%, transparent)",
				line: "var(--success-ink)",
				ink: "var(--plum-deep)",
				dot: "var(--success-ink)",
			};
		case "caution":
			return {
				/* 7%, not 12%: `--warn-ink` on the 12% fill measures 4.21:1, under
				   the 4.5:1 its own label has to clear. */
				fill: "var(--warn-wash)",
				line: "var(--warn)",
				ink: "var(--warn-ink)",
				dot: "var(--warn-ink)",
			};
		case "muted":
			return {
				fill: "var(--wash-3)",
				line: "var(--control-line)",
				ink: "var(--plum-deep)",
				dot: "var(--wash-32)",
			};
		default:
			return {
				fill: "var(--wash-6)",
				line: "var(--control-line)",
				ink: "var(--plum-deep)",
				dot: "var(--plum)",
			};
	}
}

/** Whether the reader has asked for less motion. */
export function useReducedMotion(): boolean {
	const [reduced, setReduced] = useState(() => {
		if (typeof window === "undefined" || !window.matchMedia) return false;
		return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
	});

	useEffect(() => {
		if (typeof window === "undefined" || !window.matchMedia) return;
		const query = window.matchMedia("(prefers-reduced-motion: reduce)");
		const listener = (event: MediaQueryListEvent) => setReduced(event.matches);
		query.addEventListener("change", listener);
		return () => query.removeEventListener("change", listener);
	}, []);

	return reduced;
}

/** The text equivalent, for a screen reader. */
export function A11yText({ children }: { children: ReactNode }) {
	const hidden: CSSProperties = {
		position: "absolute",
		width: "1px",
		height: "1px",
		padding: 0,
		margin: "-1px",
		overflow: "hidden",
		clip: "rect(0, 0, 0, 0)",
		whiteSpace: "nowrap",
		border: 0,
	};
	return <p style={hidden}>{children}</p>;
}

/** The card every widget sits in. */
export function Panel({
	title,
	caption,
	a11yText,
	children,
	footer,
}: {
	title: string;
	caption?: string;
	a11yText: string;
	children: ReactNode;
	footer?: ReactNode;
}) {
	return (
		// `<figure>` rather than `<section role="group">`.
		<figure className="w-panel">
			<A11yText>{a11yText}</A11yText>
			<h3 className="w-panel__title">{title}</h3>
			{caption ? <p className="w-panel__caption">{caption}</p> : null}
			<div className="w-panel__body">{children}</div>
			{footer}
		</figure>
	);
}

/** "Got it" and "Skip". */
export function WidgetActions({
	onDone,
	onSkip,
	doneLabel = "Got it",
	skipLabel = "Skip",
	/* Quiet while a step remains, so the card has one loud control at a time. */
	doneTone = "primary",
}: {
	onDone: () => void;
	onSkip: () => void;
	doneLabel?: string;
	skipLabel?: string;
	doneTone?: "primary" | "quiet";
}) {
	return (
		<div className="w-actions">
			<button
				type="button"
				onClick={onDone}
				className={`w-btn w-btn--${doneTone}`}
			>
				{doneLabel}
			</button>
			<button type="button" onClick={onSkip} className="w-btn w-btn--quiet">
				{skipLabel}
			</button>
		</div>
	);
}

/** One coin. Used by `GrowthStack` and `Proportion`. */
export function Coin({
	filled,
	token = "neutral",
	size = 18,
	delayMs = 0,
}: {
	filled: boolean;
	token?: ColourToken;
	size?: number;
	delayMs?: number;
}) {
	return (
		<span
			aria-hidden="true"
			className={filled ? "w-coin" : "w-coin w-coin--empty"}
			// `accent` is the only token drawn differently; the rest are plain discs.
			data-token={filled && token === "accent" ? "accent" : undefined}
			style={
				{
					width: size,
					height: size,
					// Staggered entry, capped well under 600ms in total.
					"--coin-delay": `${Math.min(delayMs, 300)}ms`,
				} as CSSProperties
			}
		/>
	);
}

/** A horizontal bar, for `stacked_bars`. */
export function Bar({
	fraction,
	token,
	label,
}: {
	fraction: number;
	token: ColourToken;
	label: string;
}) {
	const colours = tone(token);
	return (
		<div className="w-bar">
			<div className="w-bar__label">
				<span>{label}</span>
			</div>
			<div className="w-bar__track">
				<div
					className="w-bar__fill"
					style={
						{
							"--fill": Math.max(0, Math.min(1, fraction)),
							background: colours.line,
						} as CSSProperties
					}
				/>
			</div>
		</div>
	);
}
