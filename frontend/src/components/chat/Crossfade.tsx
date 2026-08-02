import { useEffect, useRef, useState } from "react";

/** Matches the `fade-in` / `fade-out` pair in styles.css. */
const DURATION_MS = 320;

/**
 * A single line of text that dissolves when it is replaced.
 *
 * Built for one specific moment: the provisional label — the truncated first
 * message, written the instant a chat is sent — being replaced by the generated
 * title a few seconds later. That swap happens while the reader is looking
 * somewhere else on the page, and a hard substitution reads as a glitch.
 *
 * Both strings occupy the same grid cell, so the outgoing one cannot change the
 * height or width of whatever contains it on its way out, and it is
 * `aria-hidden` so the swap is one announcement rather than two.
 */
export function Crossfade({ text }: { text: string }) {
	const [outgoing, setOutgoing] = useState<string | null>(null);
	const shown = useRef(text);

	useEffect(() => {
		if (text === shown.current) return;
		setOutgoing(shown.current);
		shown.current = text;
		const timer = setTimeout(() => setOutgoing(null), DURATION_MS);
		return () => clearTimeout(timer);
	}, [text]);

	return (
		<span className="xfade">
			<span className="xfade__in">{text}</span>
			{outgoing ? (
				<span className="xfade__out" aria-hidden="true">
					{outgoing}
				</span>
			) : null}
		</span>
	);
}
