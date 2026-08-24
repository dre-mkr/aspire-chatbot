/** The voice half of the ASPIRE backend client. */
import { API_URL } from "../config";
import { authHeaders } from "./session";

/**
 * Personas map to voices on the server, and this is the fallback -- not the
 * answer.
 *
 * `speakStream` took no persona and sent this for every request, so every
 * reader heard Nova: the STAFF voice, whose card opens "you are the ASPIRE
 * assistant for teachers, staff and partners" and whose delivery is tuned
 * flattest of the four. A six-year-old reading a lesson Stella wrote heard it
 * read aloud by the staff voice.
 *
 * None of the machinery was missing. `voice/registry.py` builds all four
 * personas across all three languages, resolves a language-specific voice
 * before falling back to the persona's own, carries per-persona speed and
 * style, and REFUSES TO START if any of the twelve pairs is unmapped. Only the
 * client never said who was speaking.
 *
 * The fallback itself moves from `nova` to `stella` to match
 * `_ANONYMOUS_DEFAULT` on the server. A signed-out visitor has no persona in
 * the URL and none from an account, so they land here -- and they are banded as
 * the youngest, so the staff voice was the wrong end of the range to default
 * to. A registered reader never reaches this: their account supplies one.
 */
export const DEFAULT_PERSONA = "stella";

export type VoiceLanguage = "en" | "es" | "fr";

export interface VoiceLimits {
	max_duration_seconds: number;
	max_file_size_bytes: number;
	allowed_mime_types: Array<string>;
}

export interface PersonaVoice {
	persona: string;
	languages: Array<VoiceLanguage>;
	/** How fast this persona reads, before the reader's own preference. */
	speed: number;
	stability: number;
}

export interface VoiceConfig {
	enabled: boolean;
	languages: Array<VoiceLanguage>;
	limits: VoiceLimits;
	/**
	 * Per-persona delivery, which the server has always sent and nothing read.
	 *
	 * Skye is tuned to 0.88 and Azuri to 0.96 -- a five-year-old is read to more
	 * slowly than a teacher is. The client used only the reader's own speed
	 * preference, so every persona was delivered at exactly the same pace and
	 * the tuning did nothing.
	 */
	personas: Array<PersonaVoice>;
}

export interface Transcription {
	text: string;
	language_code: string;
	language_probability: number;
	duration_seconds: number;
}

/** Why voice is unavailable, in the vocabulary the UI writes its notes in. */
export type VoiceFailure =
	| "no-speech"
	| "denied"
	| "offline"
	| "dropped"
	| "limited"
	/**
	 * The server has no voice it is willing to use, and said to try the browser.
	 *
	 * Two causes, one answer. `voice_uncast` is a persona whose voice id is not
	 * set -- Kaleb, who deliberately does NOT borrow Skye's, so without his own
	 * he has none. `voice_unavailable` is the vendor being unreachable or the
	 * key being absent. Both arrive as 503 carrying `fallback: "browser"`, and
	 * nothing was reading it: the reply was "Voice is offline", which was untrue
	 * and left a working browser voice unused.
	 */
	| "use-browser"
	/** The caller cancelled it. */
	| "aborted";

export class VoiceError extends Error {
	readonly failure: VoiceFailure;

	constructor(failure: VoiceFailure, message?: string) {
		super(message ?? failure);
		this.name = "VoiceError";
		this.failure = failure;
	}
}

/**
 * Held for the life of the page: the composer is mounted fresh on every move
 * between the landing and a chat, and without this each one re-asks and blinks
 * the mic and its settings out of the toolbar while the answer is in flight.
 */
let configRequest: Promise<VoiceConfig | null> | null = null;

/** Ask the server what voice can do. */
export function fetchVoiceConfig(): Promise<VoiceConfig | null> {
	configRequest ??= (async () => {
		try {
			const response = await fetch(`${API_URL}/api/voice/config`, {
				signal: AbortSignal.timeout(4000),
			});
			if (!response.ok) return null;
			const body = (await response.json()) as VoiceConfig;
			return body.enabled ? body : null;
		} catch {
			// A timeout is not an answer: forget it, so the next mount asks again.
			configRequest = null;
			return null;
		}
	})();
	return configRequest;
}

/** A filename whose extension matches what was actually recorded. */
function filenameFor(blobType: string) {
	const container = blobType.split(";", 1)[0].trim().toLowerCase();
	const extension =
		container === "audio/mp4"
			? "mp4"
			: container === "audio/ogg"
				? "ogg"
				: container === "audio/mpeg"
					? "mp3"
					: "webm";
	return `speech.${extension}`;
}

export async function transcribe(
	audio: Blob,
	language: VoiceLanguage,
	threadId: string | null,
): Promise<Transcription> {
	const form = new FormData();
	// The filename's extension must agree with the blob's own Content-Type.
	form.append("file", audio, filenameFor(audio.type));
	form.append("voice_consent", "true");
	form.append("language", language);
	if (threadId) form.append("thread_id", threadId);

	let response: Response;
	try {
		response = await fetch(`${API_URL}/api/voice/transcribe`, {
			method: "POST",
			// The endpoint requires a verified caller now. It was open, and so
			// were both speak routes: anybody at all could spend the programme's
			// ElevenLabs budget, metered only against a thread id they sent
			// themselves. `ensureSession` has run by the time a mic exists.
			headers: authHeaders(),
			body: form,
			signal: AbortSignal.timeout(20_000),
		});
	} catch {
		throw new VoiceError("dropped");
	}

	if (response.status === 429) throw new VoiceError("limited");
	if (response.status === 403) throw new VoiceError("denied");
	// A 401 falls through to "offline" on purpose. `denied` is about a blocked
	// MICROPHONE and tells the reader to open the lock icon and allow it, which
	// would be wrong and baffling advice for an expired session; "voice is
	// offline, typing gets you the same answers" is both true and actionable.
	if (!response.ok) throw new VoiceError("offline");

	const body = (await response.json()) as Transcription;
	if (!body.text.trim()) throw new VoiceError("no-speech");
	return body;
}

/** Synthesise an answer and start it playing before it has finished being made. */
export async function speakStream(
	text: string,
	language: VoiceLanguage,
	threadId: string | null,
	persona: string | null,
	signal?: AbortSignal,
): Promise<string> {
	// The timeout covers WAITING for audio, never the stream: long answers run long.
	const controller = new AbortController();
	const timer = setTimeout(() => controller.abort(), 20_000);
	if (signal) {
		if (signal.aborted) controller.abort();
		else
			signal.addEventListener("abort", () => controller.abort(), {
				once: true,
			});
	}

	let response: Response;
	try {
		response = await fetch(`${API_URL}/api/voice/speak-stream`, {
			method: "POST",
			headers: { "Content-Type": "application/json", ...authHeaders() },
			body: JSON.stringify({
				text,
				persona: persona ?? DEFAULT_PERSONA,
				language,
				thread_id: threadId,
			}),
			signal: controller.signal,
		});
	} catch {
		clearTimeout(timer);
		if (signal?.aborted) throw new VoiceError("aborted");
		throw new VoiceError("dropped");
	}
	clearTimeout(timer);

	if (response.status === 429) throw new VoiceError("limited");
	// The server offers the browser when it cannot speak itself. Take it.
	if (response.status === 503) throw new VoiceError("use-browser");
	if (!response.ok) throw new VoiceError("offline");

	const body = response.body;
	const canStream =
		typeof MediaSource !== "undefined" &&
		MediaSource.isTypeSupported("audio/mpeg") &&
		body !== null;
	if (!canStream || body === null) {
		return URL.createObjectURL(await response.blob());
	}

	const source = new MediaSource();
	const url = URL.createObjectURL(source);
	const reader = body.getReader();

	source.addEventListener(
		"sourceopen",
		() => {
			const buffer = source.sourceBuffers.length
				? source.sourceBuffers[0]
				: source.addSourceBuffer("audio/mpeg");

			const appended = () =>
				new Promise<void>((resolve, reject) => {
					buffer.addEventListener("updateend", () => resolve(), { once: true });
					buffer.addEventListener("error", () => reject(new Error("append")), {
						once: true,
					});
				});

			const finish = () => {
				// Ending an already-closed source throws; that is teardown, not a failure.
				try {
					if (source.readyState === "open") source.endOfStream();
				} catch {
					/* torn down mid-append */
				}
			};

			void (async () => {
				try {
					for (;;) {
						const { done, value } = await reader.read();
						if (done) break;
						if (source.readyState !== "open") return;
						const wait = appended();
						buffer.appendBuffer(value);
						await wait;
					}
				} catch {
					// Whatever audio arrived is still playable; the ended event resets the UI.
				} finally {
					finish();
				}
			})();
		},
		{ once: true },
	);

	// Stop pulling bytes on abort, or the fetch keeps downloading and billing.
	signal?.addEventListener(
		"abort",
		() => void reader.cancel().catch(() => {}),
		{
			once: true,
		},
	);

	return url;
}

/** The first container the browser will actually record in. */
export function pickRecorderMimeType(): string | undefined {
	if (typeof MediaRecorder === "undefined") return undefined;
	const candidates = [
		"audio/webm;codecs=opus",
		"audio/webm",
		"audio/mp4",
		"audio/ogg;codecs=opus",
	];
	return candidates.find((type) => MediaRecorder.isTypeSupported(type));
}
