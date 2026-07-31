/**
 * The voice half of the ASPIRE backend client.
 *
 * Kept apart from `api.ts` so the whole voice feature can be reviewed — or
 * removed — in one move, exactly as the backend module is.
 */

const API_URL = (
	import.meta.env.VITE_ASPIRE_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

/** Personas map to voices on the server. Nothing in the UI selects one yet, so
 *  every request uses the newcomer voice; wire this to the persona picker when
 *  one exists. */
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
	| "limited";

export class VoiceError extends Error {
	readonly failure: VoiceFailure;

	constructor(failure: VoiceFailure, message?: string) {
		super(message ?? failure);
		this.name = "VoiceError";
		this.failure = failure;
	}
}

/**
 * Ask the server what voice can do. A 404 means the module is switched off
 * server-side, which is a normal state, not an error.
 */
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

/**
 * A filename whose extension matches what was actually recorded.
 *
 * Not cosmetic: the transcription API detects the container from the filename,
 * so a Safari recording (mp4) labelled `.webm` is a file that disagrees with
 * itself. `blob.type` carries the codec parameter — `audio/webm;codecs=opus` —
 * so the container is the part before the semicolon.
 */
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
	// The blob's own type rides along as the part's Content-Type; the filename
	// has to agree with it, because that is what the API reads the container from.
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

/**
 * Synthesise an answer. Returns an object URL the caller must revoke.
 */
export async function speak(
	text: string,
	language: VoiceLanguage,
	threadId: string | null,
): Promise<string> {
	let response: Response;
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
			signal: AbortSignal.timeout(20_000),
		});
	} catch {
		throw new VoiceError("dropped");
	}

	if (response.status === 429) throw new VoiceError("limited");
	if (!response.ok) throw new VoiceError("offline");

	return URL.createObjectURL(await response.blob());
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
