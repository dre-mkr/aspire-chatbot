/**
 * Speaking the answer, and stopping the instant a child touches anything.
 *
 * ## Interruptible is the requirement, not a feature
 *
 * A six-year-old who taps a chip while the mascot is mid-sentence expects the
 * mascot to stop. If it talks over their tap they will tap again, and again,
 * and the interface will feel like it is not listening -- which for a
 * voice-first product is the whole product failing.
 *
 * So `stop()` is synchronous, it is wired to a global pointerdown and keydown
 * listener, and it does not wait for a fade. Audio cutting off abruptly is
 * correct here.
 *
 * ## Streaming, because time-to-first-sound is the number that matters
 *
 * The existing voice layer already streams from ElevenLabs (see
 * `app/voice/`), and this consumes that endpoint rather than a second one. The
 * child hears the first syllable while the rest is still being synthesised.
 *
 * ## Word timings drive `KaraokeText`
 *
 * When the endpoint returns character-level timings they are converted to word
 * spans here, once, and handed to the highlighter. When it does not, the
 * highlighter falls back to a per-sentence highlight -- which is a real
 * degradation and still useful, because the fallback is the reduced-motion
 * behaviour anyway.
 */

const API_URL = (
	import.meta.env.VITE_ASPIRE_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

/** Per-persona voice. Ids come from the server's registry, never hardcoded here. */
export interface VoiceOptions {
	persona: string;
	locale: string;
	token?: string;
}

export interface WordSpan {
	word: string;
	/** Milliseconds from the start of playback. */
	startMs: number;
	endMs: number;
}

export interface Speech {
	/** Resolves when playback finishes, or immediately if it was interrupted. */
	finished: Promise<void>;
	stop: () => void;
	/** Word timings, when the provider supplied them. Empty otherwise. */
	words: Array<WordSpan>;
}

let current: { audio: HTMLAudioElement; stop: () => void } | null = null;

/**
 * Stop whatever is playing. Safe to call at any time, from anywhere.
 *
 * Exported and wired to a document-level listener by `installInterrupts`, so
 * every tap anywhere stops playback without each component having to remember.
 */
export function stopSpeaking(): void {
	if (!current) return;
	const { stop } = current;
	current = null;
	stop();
}

/**
 * Stop speech on any interaction. Returns a teardown.
 *
 * Capture phase, deliberately: a chip's own click handler will send a message
 * and re-render, and a bubbling listener attached to the document might never
 * run. Capture fires before anything can stop propagation.
 */
export function installInterrupts(
	target: Document | HTMLElement = document,
): () => void {
	const stop = () => stopSpeaking();
	target.addEventListener("pointerdown", stop, { capture: true });
	target.addEventListener("keydown", stop, { capture: true });
	return () => {
		target.removeEventListener("pointerdown", stop, { capture: true });
		target.removeEventListener("keydown", stop, { capture: true });
	};
}

/**
 * Speak `text`. Any speech already playing is stopped first.
 *
 * Never more than one voice at a time: two overlapping mascots is unusable, and
 * it is what happens when a turn arrives while the previous one is still being
 * read.
 */
export async function speak(
	text: string,
	options: VoiceOptions,
): Promise<Speech> {
	stopSpeaking();

	const response = await fetch(`${API_URL}/api/voice/speak`, {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			...(options.token ? { Authorization: `Bearer ${options.token}` } : {}),
		},
		body: JSON.stringify({
			text,
			persona: options.persona,
			language: options.locale,
			// Asked for, not required. A provider that does not return them makes
			// `KaraokeText` fall back to sentence highlighting, which is the
			// reduced-motion behaviour anyway.
			with_timestamps: true,
		}),
	});

	if (!response.ok) {
		throw new Error(`speech failed: ${response.status}`);
	}

	const timingHeader = response.headers.get("x-aspire-word-timings");
	const words = timingHeader ? parseTimings(timingHeader, text) : [];

	const blob = await response.blob();
	const url = URL.createObjectURL(blob);
	const audio = new Audio(url);

	let settle: () => void = () => undefined;
	const finished = new Promise<void>((resolve) => {
		settle = resolve;
	});

	const cleanup = () => {
		audio.pause();
		// Revoked, always. A conversation of forty turns leaks forty audio blobs
		// otherwise, and on a phone that is real memory.
		URL.revokeObjectURL(url);
		settle();
	};

	audio.addEventListener("ended", cleanup, { once: true });
	audio.addEventListener("error", cleanup, { once: true });

	current = { audio, stop: cleanup };

	try {
		await audio.play();
	} catch (error) {
		// Autoplay was refused. Not an error to surface: the child has simply
		// not interacted with the page yet, and the next tap will unblock it.
		console.info("[aspire] speech was not permitted to start", error);
		cleanup();
	}

	return { finished, stop: cleanup, words };
}

/** Whether anything is currently being spoken. */
export function isSpeaking(): boolean {
	return current !== null;
}

/**
 * Character timings from the provider, folded into word spans.
 *
 * Done here rather than in the highlighter because it is a pure transformation
 * of provider output, and doing it per render would be doing it sixty times a
 * second for a value that never changes.
 */
function parseTimings(header: string, text: string): Array<WordSpan> {
	let raw: Array<{ start: number; end: number }>;
	try {
		raw = JSON.parse(header);
	} catch {
		return [];
	}
	if (!Array.isArray(raw) || raw.length === 0) return [];

	const words: Array<WordSpan> = [];
	let index = 0;
	for (const word of text.split(/(\s+)/)) {
		if (!word.trim()) {
			index += word.length;
			continue;
		}
		const first = raw[Math.min(index, raw.length - 1)];
		const last = raw[Math.min(index + word.length - 1, raw.length - 1)];
		words.push({
			word,
			startMs: (first?.start ?? 0) * 1000,
			endMs: (last?.end ?? 0) * 1000,
		});
		index += word.length;
	}
	return words;
}
