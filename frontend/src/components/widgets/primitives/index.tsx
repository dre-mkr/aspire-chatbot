/** Shared parts every widget is built from: tokens, a panel, a coin, and the two affordances that are not option… */
import { type CSSProperties, type ReactNode, useEffect, useState } from "react";

export type ColourToken =
	| "neutral"
	| "accent"
	| "positive"
	| "caution"
	| "muted";

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

/** Money in minor units, as a reader sees it. Mirrors `registry.money_display`. */
export function money(cents: number, currency = "EC$"): string {
	const sign = cents < 0 ? "-" : "";
	const whole = Math.floor(Math.abs(cents) / 100);
	const part = Math.abs(cents) % 100;
	return `${sign}${currency}${whole.toLocaleString("en-US")}.${String(part).padStart(2, "0")}`;
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
		<figure
			style={{
				position: "relative",
				margin: "0.75rem 0",
				padding: "1rem",
				borderRadius: "1rem",
				border: "1px solid var(--hairline)",
				background: "var(--wash-3)",
			}}
		>
			<A11yText>{a11yText}</A11yText>
			<h3
				style={{
					margin: 0,
					fontSize: "calc(var(--band-type, 16px) + 1px)",
					fontWeight: 700,
					color: "var(--plum-deep)",
				}}
			>
				{title}
			</h3>
			{caption ? (
				<p
					style={{
						margin: "0.25rem 0 0.75rem",
						fontSize: "var(--band-type, 16px)",
						color: "var(--slate)",
					}}
				>
					{caption}
				</p>
			) : (
				<div style={{ height: "0.75rem" }} />
			)}
			{children}
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
}: {
	onDone: () => void;
	onSkip: () => void;
	doneLabel?: string;
	skipLabel?: string;
}) {
	const base: CSSProperties = {
		minHeight: "var(--band-target, 44px)",
		minWidth: "44px",
		padding: "0.5rem 1rem",
		borderRadius: "0.75rem",
		fontSize: "var(--band-type, 16px)",
		fontWeight: 600,
		cursor: "pointer",
	};

	return (
		<div
			style={{
				display: "flex",
				gap: "0.5rem",
				marginBlockStart: "0.875rem",
				flexWrap: "wrap",
			}}
		>
			<button
				type="button"
				onClick={onDone}
				style={{
					...base,
					border: "1px solid var(--plum)",
					background: "var(--plum)",
					color: "white",
				}}
			>
				{doneLabel}
			</button>
			<button
				type="button"
				onClick={onSkip}
				style={{
					...base,
					border: "1px solid var(--hairline)",
					background: "transparent",
					color: "var(--quiet)",
				}}
			>
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
	const reduced = useReducedMotion();
	const colours = tone(token);
	return (
		<span
			aria-hidden="true"
			style={{
				display: "inline-block",
				width: size,
				height: size,
				borderRadius: "50%",
				background: filled ? colours.fill : "transparent",
				border: `2px solid ${filled ? colours.line : "var(--hairline)"}`,
				// Staggered entry, capped well under 600ms in total.
				animation: reduced || !filled ? undefined : "none",
				opacity: 1,
				transition: reduced
					? undefined
					: `background-color 200ms ease ${Math.min(delayMs, 300)}ms`,
			}}
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
	const reduced = useReducedMotion();
	const colours = tone(token);
	return (
		<div style={{ marginBlockEnd: "0.5rem" }}>
			<div
				style={{
					display: "flex",
					justifyContent: "space-between",
					fontSize: "calc(var(--band-type, 16px) - 2px)",
					color: "var(--slate)",
				}}
			>
				<span>{label}</span>
			</div>
			<div
				style={{
					height: "0.75rem",
					borderRadius: "999px",
					background: "var(--wash-6)",
					overflow: "hidden",
				}}
			>
				<div
					style={{
						width: `${Math.max(0, Math.min(1, fraction)) * 100}%`,
						height: "100%",
						background: colours.line,
						transition: reduced ? undefined : "width 320ms ease",
					}}
				/>
			</div>
		</div>
	);
}
