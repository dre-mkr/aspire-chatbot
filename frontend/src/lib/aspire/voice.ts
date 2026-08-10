/** The voice half of the ASPIRE backend client. */

const API_URL = (
	import.meta.env.VITE_ASPIRE_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

/** Personas map to voices on the server. */
export const DEFAULT_PERSONA = "nova";

export type VoiceLanguage = "en" | "es" | "fr";

export interface VoiceLimits {
	max_duration_seconds: number;
	max_file_size_bytes: number;
	allowed_mime_types: Array<string>;
}

export interface VoiceConfig {
	enabled: boolean;
	languages: Array<VoiceLanguage>;
	limits: VoiceLimits;
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

/** Ask the server what voice can do. */
export async function fetchVoiceConfig(): Promise<VoiceConfig | null> {
	try {
		const response = await fetch(`${API_URL}/api/voice/config`, {
			signal: AbortSignal.timeout(4000),
		});
		if (!response.ok) return null;
		const body = (await response.json()) as VoiceConfig;
		return body.enabled ? body : null;
	} catch {
		return null;
	}
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
	// The blob's own type rides along as the part's Content-Type; the filename has to agree with it, because that i…
	form.append("file", audio, filenameFor(audio.type));
	form.append("voice_consent", "true");
	form.append("language", language);
	if (threadId) form.append("thread_id", threadId);

	let response: Response;
	try {
		response = await fetch(`${API_URL}/api/voice/transcribe`, {
			method: "POST",
			body: form,
			signal: AbortSignal.timeout(20_000),
		});
	} catch {
		throw new VoiceError("dropped");
	}

	if (response.status === 429) throw new VoiceError("limited");
	if (response.status === 403) throw new VoiceError("denied");
	if (!response.ok) throw new VoiceError("offline");

	const body = (await response.json()) as Transcription;
	if (!body.text.trim()) throw new VoiceError("no-speech");
	return body;
}

/** Synthesise an answer. */
export async function speak(
	text: string,
	language: VoiceLanguage,
	threadId: string | null,
	/** Cancels the synthesis, and with it the ElevenLabs call behind it. */
	signal?: AbortSignal,
): Promise<string> {
	let response: Response;
	// The external signal and the timeout are combined rather than chosen between: whichever fires first should sto…
	const timeout = AbortSignal.timeout(20_000);
	const cancel = signal ? AbortSignal.any([signal, timeout]) : timeout;
	try {
		response = await fetch(`${API_URL}/api/voice/speak`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				text,
				persona: DEFAULT_PERSONA,
				language,
				thread_id: threadId,
			}),
			signal: cancel,
		});
	} catch {
		// A caller-driven abort is not a fault and must not be dressed as one: the caller already knows, because it is…
		if (signal?.aborted) throw new VoiceError("aborted");
		throw new VoiceError("dropped");
	}

	if (response.status === 429) throw new VoiceError("limited");
	if (!response.ok) throw new VoiceError("offline");

	return URL.createObjectURL(await response.blob());
}

/** Synthesise an answer and start it playing before it has finished being made. */
export async function speakStream(
	text: string,
	language: VoiceLanguage,
	threadId: string | null,
	signal?: AbortSignal,
): Promise<string> {
	// The timeout must cover WAITING for audio, never the audio itself: a long answer streams for longer than any s…
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
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				text,
				persona: DEFAULT_PERSONA,
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
				// Ending a source that is already closed (stopPlayback revoked the URL) throws; that is teardown, not a failure.
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
					// A dropped stream or an abort: whatever audio arrived is playable, and the ended event returns the UI to Play.
				} finally {
					finish();
				}
			})();
		},
		{ once: true },
	);

	// Stop pulling bytes the moment the caller aborts — without this the fetch keeps billing and downloading into a…
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
