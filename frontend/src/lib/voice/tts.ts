/** Speaking the answer, and stopping the instant a child touches anything. */

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

/** Stop whatever is playing. */
export function stopSpeaking(): void {
	if (!current) return;
	const { stop } = current;
	current = null;
	stop();
}

/** Stop speech on any interaction. */
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

/** Speak `text`. */
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
			// Asked for, not required.
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
		// Revoked, always.
		URL.revokeObjectURL(url);
		settle();
	};

	audio.addEventListener("ended", cleanup, { once: true });
	audio.addEventListener("error", cleanup, { once: true });

	current = { audio, stop: cleanup };

	try {
		await audio.play();
	} catch (error) {
		// Autoplay was refused.
		console.info("[aspire] speech was not permitted to start", error);
		cleanup();
	}

	return { finished, stop: cleanup, words };
}

/** Whether anything is currently being spoken. */
export function isSpeaking(): boolean {
	return current !== null;
}

/** Character timings from the provider, folded into word spans. */
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
