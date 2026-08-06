/**
 * Push-to-talk transcription. Never always-listening.
 *
 * ## The microphone is open only while a button is held or toggled on
 *
 * There is no wake word, no ambient listening, and no "start recording when the
 * page loads". A microphone that a child does not know is open is a microphone
 * recording their household, and no product feature is worth that.
 *
 * The permission prompt therefore appears when they first press the button,
 * which is also the moment it makes sense to them.
 *
 * ## Audio is not stored
 *
 * The recorder holds chunks in memory, posts them once, and drops the
 * reference. Nothing is written to IndexedDB, nothing to localStorage, nothing
 * to a file. The server's transcription endpoint holds the bytes for the length
 * of the request and no longer.
 *
 * ## Auto-stop after 15 seconds of silence
 *
 * A child who wanders off mid-sentence, or who presses the button and forgets,
 * must not leave a microphone open. Silence is measured with an analyser node
 * on the live stream rather than by transcribing and checking for words --
 * which would mean sending the silence somewhere to find out it was silence.
 */

const API_URL = (
	import.meta.env.VITE_ASPIRE_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

/** How long a run of quiet ends the recording. */
export const SILENCE_TIMEOUT_MS = 15000;

/** Below this RMS the input counts as silence. Empirical, and forgiving. */
const SILENCE_THRESHOLD = 0.012;

/** A hard ceiling regardless of speech. A child does not need 60 seconds. */
const MAX_RECORDING_MS = 30000;

export interface Recording {
	/** Resolves with the transcript, or "" if nothing usable was said. */
	transcript: Promise<string>;
	/** End the recording now and transcribe what there is. */
	stop: () => void;
	/** Throw it away without sending anything. */
	cancel: () => void;
}

export interface RecorderOptions {
	locale: string;
	token?: string;
	/** Called as the level changes, for the recording indicator. 0-1. */
	onLevel?: (level: number) => void;
	/** Called when silence ended the recording rather than the user. */
	onSilenceStop?: () => void;
}

export function microphoneAvailable(): boolean {
	return (
		typeof navigator !== "undefined" &&
		!!navigator.mediaDevices?.getUserMedia &&
		typeof MediaRecorder !== "undefined"
	);
}

/**
 * Start recording. The stream is released the moment it stops.
 *
 * Releasing the track matters visibly: a browser shows a recording indicator
 * for as long as ANY track is live, so a stream left open tells the child they
 * are still being listened to when they are not.
 */
export async function record(options: RecorderOptions): Promise<Recording> {
	const stream = await navigator.mediaDevices.getUserMedia({
		audio: {
			echoCancellation: true,
			noiseSuppression: true,
			autoGainControl: true,
		},
	});

	const chunks: Array<Blob> = [];
	const recorder = new MediaRecorder(stream, pickMimeType());
	recorder.addEventListener("dataavailable", (event) => {
		if (event.data.size > 0) chunks.push(event.data);
	});

	// Level metering, and the silence timer that rides on it.
	const context = new AudioContext();
	const source = context.createMediaStreamSource(stream);
	const analyser = context.createAnalyser();
	analyser.fftSize = 512;
	source.connect(analyser);
	const samples = new Float32Array(analyser.fftSize);

	let cancelled = false;
	let silentSince = Date.now();
	let frame = 0;

	const release = () => {
		cancelAnimationFrame(frame);
		for (const track of stream.getTracks()) track.stop();
		void context.close();
	};

	let settle: (value: string) => void = () => undefined;
	const transcript = new Promise<string>((resolve) => {
		settle = resolve;
	});

	const finish = async () => {
		release();
		if (cancelled || chunks.length === 0) {
			settle("");
			return;
		}
		const blob = new Blob(chunks, { type: recorder.mimeType });
		// The chunks array is dropped with this closure; nothing else holds a
		// reference to the audio once the request completes.
		chunks.length = 0;
		try {
			settle(await transcribe(blob, options));
		} catch (error) {
			console.error("[aspire] transcription failed", error);
			settle("");
		}
	};

	recorder.addEventListener("stop", () => void finish(), { once: true });

	const meter = () => {
		analyser.getFloatTimeDomainData(samples);
		let sum = 0;
		for (const sample of samples) sum += sample * sample;
		const level = Math.sqrt(sum / samples.length);
		options.onLevel?.(Math.min(1, level * 8));

		const now = Date.now();
		if (level > SILENCE_THRESHOLD) silentSince = now;
		else if (now - silentSince > SILENCE_TIMEOUT_MS) {
			options.onSilenceStop?.();
			if (recorder.state === "recording") recorder.stop();
			return;
		}
		frame = requestAnimationFrame(meter);
	};

	recorder.start();
	frame = requestAnimationFrame(meter);

	const ceiling = setTimeout(() => {
		if (recorder.state === "recording") recorder.stop();
	}, MAX_RECORDING_MS);

	return {
		transcript,
		stop: () => {
			clearTimeout(ceiling);
			if (recorder.state === "recording") recorder.stop();
		},
		cancel: () => {
			cancelled = true;
			clearTimeout(ceiling);
			if (recorder.state === "recording") recorder.stop();
			else {
				release();
				settle("");
			}
		},
	};
}

/**
 * The first container the browser will actually record.
 *
 * Safari records mp4 and refuses webm; Chrome and Firefox do the opposite. A
 * hardcoded type works in development and produces an empty recording on an
 * iPhone, which is most of the audience.
 */
function pickMimeType(): MediaRecorderOptions {
	for (const type of [
		"audio/webm;codecs=opus",
		"audio/webm",
		"audio/mp4",
		"audio/ogg;codecs=opus",
	]) {
		if (MediaRecorder.isTypeSupported(type)) return { mimeType: type };
	}
	return {};
}

async function transcribe(
	blob: Blob,
	options: RecorderOptions,
): Promise<string> {
	const body = new FormData();
	body.append("audio", blob, "speech");
	body.append("language", options.locale);

	const response = await fetch(`${API_URL}/api/voice/transcribe`, {
		method: "POST",
		headers: options.token ? { Authorization: `Bearer ${options.token}` } : {},
		body,
	});
	if (!response.ok) throw new Error(`transcription failed: ${response.status}`);
	const data = (await response.json()) as { text?: string };
	return (data.text ?? "").trim();
}
