/** Shared parts every widget is built from: tokens, panel, coin, actions. */
import { type CSSProperties, type ReactNode, useEffect, useState } from "react";
import type { ColourToken } from "../../../lib/stream/types";

export type { ColourToken };

/** The five tokens, as the CSS variables the stylesheet defines. */
export function tone(token: ColourToken | undefined): {
	fill: string;
	line: string;
	ink: string;
} {
	switch (token) {
		case "accent":
			// The money the bank added.
			return {
				fill: "var(--wash-m-16)",
				line: "var(--magenta)",
				ink: "var(--plum-deep)",
			};
		case "positive":
			return {
				fill: "color-mix(in srgb, var(--success) 12%, transparent)",
				line: "var(--success)",
				ink: "var(--prose)",
			};
		case "caution":
			return {
				fill: "color-mix(in srgb, var(--warn) 12%, transparent)",
				line: "var(--warn)",
				ink: "var(--warn-ink)",
			};
		case "muted":
			return {
				fill: "var(--wash-3)",
				line: "var(--hairline)",
				ink: "var(--quiet)",
			};
		default:
			return {
				fill: "var(--wash-6)",
				line: "var(--hairline)",
				ink: "var(--prose)",
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
