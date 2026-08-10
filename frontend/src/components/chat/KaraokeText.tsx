/** The word being spoken, highlighted as it is spoken. */
import { useEffect, useMemo, useRef, useState } from "react";
import type { WordSpan } from "../../lib/voice/tts";
import { useReducedMotion } from "../widgets/primitives";

export function KaraokeText({
	text,
	words,
	playing,
	startedAt,
}: {
	text: string;
	/** From the TTS provider. Empty means fall back to sentence highlighting. */
	words: Array<WordSpan>;
	playing: boolean;
	/** `performance.now()` at the moment playback began. */
	startedAt: number | null;
}) {
	const reduced = useReducedMotion();
	const [elapsed, setElapsed] = useState(0);
	const frame = useRef(0);

	const sentences = useMemo(() => splitSentences(text), [text]);
	// Keys are minted once per text, not derived from the loop index.
	const wordKeys = useMemo(
		() => words.map((span, index) => `${index}:${span.word}`),
		[words],
	);
	const sentenceKeys = useMemo(
		() => sentences.map((_sentence, index) => `s${index}`),
		[sentences],
	);
	const useWords = words.length > 0 && !reduced;

	useEffect(() => {
		if (!playing || startedAt === null) {
			setElapsed(0);
			return;
		}
		const tick = () => {
			setElapsed(performance.now() - startedAt);
			frame.current = requestAnimationFrame(tick);
		};
		frame.current = requestAnimationFrame(tick);
		return () => cancelAnimationFrame(frame.current);
	}, [playing, startedAt]);

	if (!playing) {
		return <span>{text}</span>;
	}

	if (useWords) {
		const active = words.findIndex(
			(span) => elapsed >= span.startMs && elapsed < span.endMs,
		);
		return (
			<span>
				{words.map((span, index) => (
					<span
						key={wordKeys[index]}
						style={
							index === active
								? {
										// Background and colour only.
										background: "var(--wash-m-22)",
										borderRadius: "0.25rem",
										color: "var(--plum-deep)",
									}
								: undefined
						}
					>
						{span.word}
						{index < words.length - 1 ? " " : ""}
					</span>
				))}
			</span>
		);
	}

	// The fallback: highlight the sentence, changing only when it changes.
	const total = words.length > 0 ? words[words.length - 1].endMs : 0;
	const fraction = total > 0 ? Math.min(1, elapsed / total) : 0;
	const activeSentence = Math.min(
		sentences.length - 1,
		Math.floor(fraction * sentences.length),
	);

	return (
		<span>
			{sentences.map((sentence, index) => (
				<span
					key={sentenceKeys[index]}
					style={
						index === activeSentence
							? {
									background: "var(--wash-m-12)",
									borderRadius: "0.25rem",
									color: "var(--plum-deep)",
								}
							: undefined
					}
				>
					{sentence}
				</span>
			))}
		</span>
	);
}

/** Split on sentence ends, keeping the terminator with its sentence. */
function splitSentences(text: string): Array<string> {
	const parts = text.match(/[^.!?…]+[.!?…]*\s*/g);
	return parts && parts.length > 0 ? parts : [text];
}
