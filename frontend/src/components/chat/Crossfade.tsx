import { useEffect, useRef, useState } from "react";

/** Matches the `fade-in` / `fade-out` pair in styles.css. */
const DURATION_MS = 320;

/** A single line of text that dissolves when it is replaced. */
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
