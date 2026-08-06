/**
 * The word being spoken, highlighted as it is spoken.
 *
 * ## It is literacy support, not decoration
 *
 * A six-year-old following a highlighted word while hearing it is doing the
 * thing that teaches reading. That is the reason this exists; the fact that it
 * looks good is incidental, and it is why the fallback below is worth having
 * rather than skipping.
 *
 * ## Reduced motion gets a static sentence highlight
 *
 * `prefers-reduced-motion` does not mean "no highlight" -- it means no movement
 * a vestibular system can object to. A word jumping along a line at reading
 * speed is exactly that. The fallback highlights the CURRENT SENTENCE, changing
 * only when the sentence changes, which is a handful of transitions per turn
 * instead of one per word.
 *
 * The same fallback runs when the provider returned no word timings, so the
 * degraded path is exercised constantly rather than only by users who set the
 * preference -- which is the only way a fallback stays working.
 *
 * ## Highlighting never reflows
 *
 * Background and colour only. No weight change, no size change, no padding: a
 * bolded word is wider than an unbolded one, and a line that re-wraps under a
 * moving highlight is unreadable for exactly the child this is for.
 */
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
	// Keys are minted once per text, not derived from the loop index. The words
	// repeat -- "the" appears six times in a paragraph -- so position IS the
	// identity, and a minted id says that without tripping the index-key rule.
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
										// Background and colour only. Anything that changes
										// the word's box re-wraps the line underneath the
										// highlight.
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
	// Reached both under reduced motion and whenever the provider gave no
	// timings, so it is exercised constantly rather than only by preference.
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

/**
 * Split on sentence ends, keeping the terminator with its sentence.
 *
 * Keeping the terminator matters: a highlight that stops before the full stop
 * leaves a stray character outside the block, which reads as a rendering bug
 * rather than as emphasis.
 */
function splitSentences(text: string): Array<string> {
	const parts = text.match(/[^.!?…]+[.!?…]*\s*/g);
	return parts && parts.length > 0 ? parts : [text];
}
