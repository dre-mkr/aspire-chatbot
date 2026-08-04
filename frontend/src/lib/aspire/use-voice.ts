import { useCallback, useEffect, useRef, useState } from "react";
import {
	fetchVoiceConfig,
	pickRecorderMimeType,
	speak,
	transcribe,
	VoiceError,
	type VoiceFailure,
	type VoiceLanguage,
} from "./voice";

export type VoicePhase = "rest" | "consent" | "listening" | "transcribing";
/**
 * "aborted" is excluded on purpose, and the type is what enforces it.
 *
 * Every other failure has a note because every other failure is something the
 * reader needs told. An abort is something they asked for -- they pressed stop,
 * played a different answer, or navigated away -- and a message about it would
 * be the product apologising for doing as it was told. Leaving it out of this
 * union means a future `showNote(failure)` that forgets to filter it will not
 * compile.
 */
export type NoteKind = Exclude<VoiceFailure, "aborted"> | "review";
export type NoteTone = "brand" | "bad" | "warn" | "quiet";

export interface VoiceNote {
	kind: NoteKind;
	text: string;
	action: string;
	tone: NoteTone;
}

/** Every message the voice layer can show, in the product's own voice. */
const NOTES: Record<NoteKind, Omit<VoiceNote, "kind">> = {
	review: {
		text: "Heard you. Check the words below — I was unsure of one — then send.",
		action: "Speak again",
		tone: "brand",
	},
	"no-speech": {
		text: "I didn't hear anything. Sit closer to the microphone and speak again.",
		action: "Speak again",
		tone: "bad",
	},
	denied: {
		text: "The microphone is blocked. Open the lock icon beside the web address, allow Microphone, then reload.",
		action: "Reload page",
		tone: "bad",
	},
	offline: {
		text: "Voice is offline. Typing gets you the same answers, with the same sources.",
		action: "Try voice again",
		tone: "quiet",
	},
	dropped: {
		text: "The connection dropped, so nothing was sent and nothing was kept. Speak again when you are back online.",
		action: "Speak again",
		tone: "quiet",
	},
	limited: {
		text: "That's a lot of recordings in a short time. Voice comes back shortly — typing has no limit.",
		action: "Got it",
		tone: "warn",
	},
};

/** Hard stop, matching the server's own 60-second cap. */
const MAX_SECONDS = 60;
const LEVEL_INTERVAL_MS = 240;

/** Voice preferences outlive a reload; they are a setting, not session state. */
const PREFS_KEY = "aspire.voice.prefs.v1";

interface VoicePrefs {
	autoSpeak: boolean;
	speed: string;
	language: VoiceLanguage;
}

const DEFAULT_PREFS: VoicePrefs = {
	autoSpeak: false,
	speed: "1",
	language: "en",
};

function readPrefs(): VoicePrefs {
	if (typeof window === "undefined") return DEFAULT_PREFS;
	try {
		const raw = window.localStorage.getItem(PREFS_KEY);
		if (!raw) return DEFAULT_PREFS;
		const parsed = JSON.parse(raw) as Partial<VoicePrefs>;
		return {
			autoSpeak:
				typeof parsed.autoSpeak === "boolean" ? parsed.autoSpeak : false,
			speed: typeof parsed.speed === "string" ? parsed.speed : "1",
			language: (["en", "es", "fr"] as const).includes(
				parsed.language as VoiceLanguage,
			)
				? (parsed.language as VoiceLanguage)
				: "en",
		};
	} catch {
		return DEFAULT_PREFS;
	}
}

export type MicState = "ready" | "denied" | "off";

export interface UseVoiceOptions {
	/** Transcribed text is handed back for the user to check before sending. */
	onTranscript: (text: string) => void;
	threadId: string | null;
	/**
	 * The language from the URL, when the URL says.
	 *
	 * Language used to live here alone, in `useState` seeded from localStorage
	 * after mount — which the server cannot read, so every load painted English
	 * and swapped. The address is the one place the server can see, so it wins
	 * when it has an opinion and the stored preference fills in when it does not.
	 */
	language?: VoiceLanguage;
	/**
	 * Where a change goes. The URL is written by the caller, which owns routing;
	 * this hook still writes localStorage, so the next visit without a link
	 * remembers.
	 */
	onLanguageChange?: (next: VoiceLanguage) => void;
}

export function useVoice({
	onTranscript,
	threadId,
	language: languageFromUrl,
	onLanguageChange,
}: UseVoiceOptions) {
	const [available, setAvailable] = useState(false);
	const [phase, setPhase] = useState<VoicePhase>("rest");
	const [consented, setConsented] = useState(false);
	const [elapsed, setElapsed] = useState(0);
	const [captured, setCaptured] = useState(0);
	const [level, setLevel] = useState(2);
	const [note, setNote] = useState<VoiceNote | null>(null);
	// Defaults on the server render, real preferences once mounted — unless the
	// URL says, in which case the server already knew and there is nothing to
	// swap in.
	const [storedLanguage, setStoredLanguage] = useState<VoiceLanguage>(
		DEFAULT_PREFS.language,
	);
	/**
	 * The language in force: the address when it has an opinion, otherwise this
	 * device's remembered preference.
	 *
	 * The URL is the half the server can see, which is what removes the paint
	 * flash -- there is nothing to swap in on mount because the first render
	 * already had it.
	 */
	const language = languageFromUrl ?? storedLanguage;

	/**
	 * Both places, deliberately.
	 *
	 * The address so the choice is shareable and survives SSR; storage so a
	 * later visit with no link still opens in the language this device chose.
	 */
	const setLanguage = useCallback(
		(next: VoiceLanguage) => {
			setStoredLanguage(next);
			onLanguageChange?.(next);
		},
		[onLanguageChange],
	);

	const [autoSpeak, setAutoSpeak] = useState(DEFAULT_PREFS.autoSpeak);
	const [speed, setSpeed] = useState(DEFAULT_PREFS.speed);
	const [prefsLoaded, setPrefsLoaded] = useState(false);
	const [playingId, setPlayingId] = useState<number | null>(null);
	const [pausedId, setPausedId] = useState<number | null>(null);

	const recorder = useRef<MediaRecorder | null>(null);
	const stream = useRef<MediaStream | null>(null);
	const chunks = useRef<Array<Blob>>([]);
	const tickTimer = useRef<ReturnType<typeof setInterval>>(undefined);
	const levelTimer = useRef<ReturnType<typeof setInterval>>(undefined);
	const cancelled = useRef(false);
	const audio = useRef<HTMLAudioElement | null>(null);
	const objectUrl = useRef<string | null>(null);
	/** The in-flight synthesis, so it can be cancelled rather than paid for. */
	const synthesis = useRef<AbortController | null>(null);

	// localStorage is unavailable during SSR, so preferences load after mount.
	useEffect(() => {
		const prefs = readPrefs();
		setStoredLanguage(prefs.language);
		setAutoSpeak(prefs.autoSpeak);
		setSpeed(prefs.speed);
		setPrefsLoaded(true);
	}, []);

	// Persist only after the first read, or the defaults would overwrite them.
	useEffect(() => {
		if (!prefsLoaded || typeof window === "undefined") return;
		try {
			window.localStorage.setItem(
				PREFS_KEY,
				JSON.stringify({ autoSpeak, speed, language }),
			);
		} catch {
			// Private browsing throws. Preferences are a convenience, not a feature.
		}
	}, [autoSpeak, language, prefsLoaded, speed]);

	// A 404 or a disabled module both mean "no voice", which the mic button
	// shows as unavailable rather than as an error.
	useEffect(() => {
		let live = true;
		fetchVoiceConfig().then((config) => {
			if (!live) return;
			setAvailable(Boolean(config) && typeof MediaRecorder !== "undefined");
		});
		return () => {
			live = false;
		};
	}, []);

	const stopTimers = useCallback(() => {
		clearInterval(tickTimer.current);
		clearInterval(levelTimer.current);
		tickTimer.current = undefined;
		levelTimer.current = undefined;
	}, []);

	const releaseMic = useCallback(() => {
		recorder.current = null;
		// Releasing every track is what turns the browser's recording indicator
		// off. Leaving it on would contradict what the consent panel promises.
		stream.current?.getTracks().forEach((track) => {
			track.stop();
		});
		stream.current = null;
	}, []);

	const showNote = useCallback((kind: NoteKind) => {
		setNote({ kind, ...NOTES[kind] });
	}, []);

	const finish = useCallback(
		async (blob: Blob, seconds: number) => {
			setCaptured(seconds);
			setPhase("transcribing");
			try {
				const result = await transcribe(blob, language, threadId);
				if (cancelled.current) return;
				// Never auto-sent: the text lands in the composer to be checked.
				onTranscript(result.text);
				showNote("review");
			} catch (error) {
				if (cancelled.current) return;
				// `transcribe` takes no external signal, so "aborted" cannot arrive
				// here today. Handled anyway because the union allows it and a
				// silent fallthrough to "offline" would be the wrong message on the
				// day it can.
				if (error instanceof VoiceError) {
					if (error.failure !== "aborted") showNote(error.failure);
				} else {
					showNote("offline");
				}
			} finally {
				if (!cancelled.current) setPhase("rest");
			}
		},
		[language, onTranscript, showNote, threadId],
	);

	const stopListening = useCallback(() => {
		if (recorder.current?.state === "recording") recorder.current.stop();
		stopTimers();
	}, [stopTimers]);

	const beginListening = useCallback(async () => {
		cancelled.current = false;
		setNote(null);
		setElapsed(0);
		setLevel(2);

		let media: MediaStream;
		try {
			media = await navigator.mediaDevices.getUserMedia({ audio: true });
		} catch {
			showNote("denied");
			setPhase("rest");
			return;
		}

		stream.current = media;
		chunks.current = [];

		const mimeType = pickRecorderMimeType();
		const instance = new MediaRecorder(
			media,
			mimeType ? { mimeType } : undefined,
		);
		recorder.current = instance;

		let seconds = 0;
		instance.ondataavailable = (event) => {
			if (event.data.size > 0) chunks.current.push(event.data);
		};
		instance.onstop = () => {
			releaseMic();
			const blob = new Blob(chunks.current, { type: instance.mimeType });
			chunks.current = [];
			if (cancelled.current) return;
			if (blob.size === 0) {
				showNote("no-speech");
				setPhase("rest");
				return;
			}
			void finish(blob, seconds);
		};

		instance.start();
		setPhase("listening");

		tickTimer.current = setInterval(() => {
			seconds += 1;
			setElapsed(seconds);
			if (seconds >= MAX_SECONDS) stopListening();
		}, 1000);

		// The bars read as "something is being heard". Real level metering would
		// need an AnalyserNode; this is deliberately decorative.
		levelTimer.current = setInterval(
			() => setLevel(1 + Math.floor(Math.random() * 4)),
			LEVEL_INTERVAL_MS,
		);
	}, [finish, releaseMic, showNote, stopListening]);

	const start = useCallback(() => {
		if (!available || phase !== "rest") return;
		if (!consented) {
			setNote(null);
			setPhase("consent");
			return;
		}
		void beginListening();
	}, [available, beginListening, consented, phase]);

	const cancel = useCallback(() => {
		cancelled.current = true;
		stopTimers();
		if (recorder.current?.state === "recording") recorder.current.stop();
		releaseMic();
		setPhase("rest");
		setNote(null);
		setElapsed(0);
	}, [releaseMic, stopTimers]);

	const allowMic = useCallback(() => {
		setConsented(true);
		void beginListening();
	}, [beginListening]);

	const denyMic = useCallback(() => {
		setPhase("rest");
		setNote(null);
	}, []);

	const reviewConsent = useCallback(() => {
		setNote(null);
		setPhase("consent");
	}, []);

	const stopPlayback = useCallback(() => {
		// Abort the synthesis too, not just the playback. Without this,
		// interrupting a reply that was still being spoken left ElevenLabs
		// generating -- and billing for -- audio that had already been cancelled.
		synthesis.current?.abort();
		synthesis.current = null;
		audio.current?.pause();
		audio.current = null;
		if (objectUrl.current) {
			URL.revokeObjectURL(objectUrl.current);
			objectUrl.current = null;
		}
		setPlayingId(null);
		setPausedId(null);
	}, []);

	/**
	 * Stop on the way out, as well as on every deliberate interruption.
	 *
	 * `stopPlayback` was already called on send, regenerate, stop, chat switch
	 * and audio-end, and no effect returned it as a cleanup. `AspireChat`
	 * survives `/` to `/chat/:id`, so this was narrow -- but navigating to
	 * `/signin`, `/signup`, `/verify` or `/reset` unmounts the shell, and audio
	 * playing at that moment carried on with its blob never revoked.
	 */
	useEffect(() => stopPlayback, [stopPlayback]);

	/**
	 * Play an answer aloud, pause it if it is already playing, or resume it if
	 * it was paused. Resuming reuses the audio already fetched, so it continues
	 * from where it stopped instead of restarting.
	 */
	const play = useCallback(
		async (id: number, text: string) => {
			if (playingId === id) {
				audio.current?.pause();
				setPlayingId(null);
				setPausedId(id);
				return;
			}

			if (pausedId === id && audio.current) {
				setPausedId(null);
				setPlayingId(id);
				try {
					await audio.current.play();
				} catch {
					stopPlayback();
				}
				return;
			}

			stopPlayback();
			const controller = new AbortController();
			synthesis.current = controller;
			let url: string;
			try {
				url = await speak(text, language, threadId, controller.signal);
			} catch (error) {
				// An abort is this component's own doing -- another answer was
				// played, the reader stopped it, the shell unmounted. Saying "the
				// connection dropped" for something they asked for would be a lie.
				if (error instanceof VoiceError) {
					if (error.failure !== "aborted") showNote(error.failure);
				} else {
					showNote("offline");
				}
				return;
			}

			// Cancelled while the bytes were arriving. Nothing to play, and the
			// object URL must not leak.
			if (controller.signal.aborted) {
				URL.revokeObjectURL(url);
				return;
			}
			synthesis.current = null;

			objectUrl.current = url;
			const element = new Audio(url);
			element.playbackRate = Number(speed) || 1;
			element.onended = () => stopPlayback();
			audio.current = element;
			setPausedId(null);
			setPlayingId(id);

			try {
				await element.play();
			} catch {
				// A browser can refuse to start audio that the user did not ask for
				// directly. That is not a failure of the service, so it leaves the
				// answer sitting on Play instead of claiming voice is offline.
				setPlayingId(null);
				setPausedId(id);
			}
		},
		[language, pausedId, playingId, showNote, speed, stopPlayback, threadId],
	);

	// Changing the speed mid-sentence applies to what is already playing rather
	// than only to the next answer.
	useEffect(() => {
		if (audio.current) audio.current.playbackRate = Number(speed) || 1;
	}, [speed]);

	const runNoteAction = useCallback(() => {
		const kind = note?.kind;
		setNote(null);
		if (kind === "denied") {
			window.location.reload();
			return;
		}
		if (kind === "review" || kind === "no-speech" || kind === "dropped")
			start();
	}, [note, start]);

	useEffect(
		() => () => {
			stopTimers();
			releaseMic();
			stopPlayback();
		},
		[releaseMic, stopPlayback, stopTimers],
	);

	const micState: MicState = !available
		? "off"
		: note?.kind === "denied"
			? "denied"
			: "ready";

	return {
		available,
		phase,
		micState,
		elapsed,
		captured,
		level,
		note,
		language,
		autoSpeak,
		speed,
		playingId,
		pausedId,
		maxSeconds: MAX_SECONDS,
		start,
		stop: stopListening,
		cancel,
		allowMic,
		denyMic,
		reviewConsent,
		dismissNote: () => setNote(null),
		runNoteAction,
		setLanguage,
		setSpeed,
		toggleAutoSpeak: () => setAutoSpeak((on) => !on),
		play,
		stopPlayback,
	};
}

/** m:ss, the way both the recorder and the player label time. */
export function formatSeconds(total: number) {
	const whole = Math.max(0, Math.round(total));
	return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}
