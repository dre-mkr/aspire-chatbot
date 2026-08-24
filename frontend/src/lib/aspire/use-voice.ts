import { useCallback, useEffect, useRef, useState } from "react";
import {
	fetchVoiceConfig,
	pickRecorderMimeType,
	speakStream,
	transcribe,
	VoiceError,
	type VoiceFailure,
	type VoiceLanguage,
} from "./voice";

export type VoicePhase = "rest" | "consent" | "listening" | "transcribing";
/** "aborted" is excluded on purpose, and the type is what enforces it. */
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
	"use-browser": {
		text: "Reading this in your device's voice — the ASPIRE voice is not available right now.",
		action: "Got it",
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

/** Per-personality flavour for the notes, where the register truly differs. */
const OVERLAY_NOTES: Record<string, Partial<Record<NoteKind, string>>> = {
	quiet: {
		denied: "Mic blocked. Go fix it or just type.",
		"no-speech": "Heard nothing. Try again or type, you good.",
		offline: "Voice down. Typing works same way.",
	},
	unbothered: {
		denied: "Mic not working. Up to you.",
		"no-speech": "Didn't catch that. Or don't repeat it. Your call.",
		offline: "Voice is down. It is what it is -- typing works.",
	},
	limer: {
		denied: "De mic block up. Allow it in the browser or just type, y'know.",
		"no-speech": "Didn' hear nothing -- come closer and talk again.",
		offline: "Voice gone for now. Type it out, same answers.",
	},
	hype: {
		"no-speech": "MIC MISSED IT! Run it back one more time! 🎉",
		offline: "Voice taking a break -- typing still gets the party! 🎉",
	},
};

/**
 * Read text aloud with the device's own speech engine.
 *
 * The fallback the server has always offered in `fallback: "browser"` and which
 * nothing took. It is deliberately plain: it must not sound like a persona,
 * because the reason we are here is usually that a persona's own voice is not
 * cast, and borrowing another one is the bug this avoids.
 */
function speakInBrowser(
	text: string,
	language: string,
	rate: number,
	onDone: () => void,
): boolean {
	if (typeof window === "undefined" || !("speechSynthesis" in window))
		return false;
	try {
		window.speechSynthesis.cancel();
		const utterance = new SpeechSynthesisUtterance(text);
		utterance.lang =
			{ en: "en-GB", es: "es-ES", fr: "fr-FR" }[language] ?? "en-GB";
		utterance.rate = rate;
		utterance.onend = onDone;
		utterance.onerror = onDone;
		window.speechSynthesis.speak(utterance);
		return true;
	} catch {
		return false;
	}
}

/** Hard stop, matching the server's own 60-second cap. */
const MAX_SECONDS = 60;
const LEVEL_INTERVAL_MS = 240;

/** Voice preferences outlive a reload; they are a setting, not session state. */
const PREFS_KEY = "aspire.voice.prefs.v1";

interface VoicePrefs {
	autoSpeak: boolean;
	speed: string;
	language: VoiceLanguage;
	/**
	 * Whether the language follows what the reader writes.
	 *
	 * Stored beside `language` rather than replacing it: the assistant always
	 * has exactly one language it is answering and speaking in, and the voice
	 * layer needs a real one to pick a voice with. This says where that value
	 * came from — detected, or chosen — not what it is.
	 *
	 * On by default. Detection already ran on every turn before there was a
	 * control for it, so defaulting to off would take a working behaviour away
	 * from everyone who never opens this menu.
	 */
	autoLanguage: boolean;
	/**
	 * Whether the games may make a sound.
	 *
	 * On, unlike `autoSpeak`, and the difference is who asked. Reading every
	 * answer aloud happens to a reader who only wanted to read; a coin landing
	 * in a piggy bank happens inside a game they chose to start, in response to
	 * a button they pressed. It is still one tap away in the same menu, because
	 * the room a child is in is not always a room that wants noise.
	 */
	gameSound: boolean;
	/** Chosen personality overlay key, or "". */
	overlay: string;
}

const DEFAULT_PREFS: VoicePrefs = {
	autoSpeak: false,
	speed: "1",
	language: "en",
	autoLanguage: true,
	gameSound: true,
	overlay: "",
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
			autoLanguage:
				typeof parsed.autoLanguage === "boolean" ? parsed.autoLanguage : true,
			gameSound:
				typeof parsed.gameSound === "boolean" ? parsed.gameSound : true,
			overlay: typeof parsed.overlay === "string" ? parsed.overlay : "",
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
	/** The language from the URL, when the URL says. */
	language?: VoiceLanguage;
	/** Who is speaking. Without it every reader is read to in the staff voice. */
	persona?: string | null;
	/** Where a change goes. */
	onLanguageChange?: (next: VoiceLanguage) => void;
}

export function useVoice({
	onTranscript,
	threadId,
	language: languageFromUrl,
	persona = null,
	onLanguageChange,
}: UseVoiceOptions) {
	const [available, setAvailable] = useState(false);
	const [phase, setPhase] = useState<VoicePhase>("rest");
	const [consented, setConsented] = useState(false);
	const [elapsed, setElapsed] = useState(0);
	const [captured, setCaptured] = useState(0);
	const [level, setLevel] = useState(2);
	const [note, setNote] = useState<VoiceNote | null>(null);
	// Defaults during SSR, stored preferences once mounted — unless the URL overrides.
	const [storedLanguage, setStoredLanguage] = useState<VoiceLanguage>(
		DEFAULT_PREFS.language,
	);
	/** The language in force: the URL if it says, else this device's preference. */
	const language = languageFromUrl ?? storedLanguage;

	const [autoLanguage, setAutoLanguage] = useState(DEFAULT_PREFS.autoLanguage);

	/**
	 * Both places, deliberately.
	 *
	 * Choosing a language also leaves Automatic. Picking Espanol and then being
	 * answered in English because the last message happened to be English is
	 * the control not working, whatever the menu says is selected.
	 */
	const setLanguage = useCallback(
		(next: VoiceLanguage) => {
			setStoredLanguage(next);
			setAutoLanguage(false);
			onLanguageChange?.(next);
		},
		[onLanguageChange],
	);

	/**
	 * Back to following the reader.
	 *
	 * The language in force is left exactly as it is. Automatic means the next
	 * message decides, not that everything reverts to English.
	 */
	const enableAutoLanguage = useCallback(() => setAutoLanguage(true), []);

	const [gameSound, setGameSound] = useState(DEFAULT_PREFS.gameSound);
	const [overlay, setOverlay] = useState(DEFAULT_PREFS.overlay);

	const [autoSpeak, setAutoSpeak] = useState(DEFAULT_PREFS.autoSpeak);
	const [speed, setSpeed] = useState(DEFAULT_PREFS.speed);
	/** `persona -> speed`, from `/api/voice/config`. Empty until it answers. */
	const personaSpeeds = useRef<Map<string, number>>(new Map());
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
		setAutoLanguage(prefs.autoLanguage);
		setGameSound(prefs.gameSound);
		setOverlay(prefs.overlay);
		setPrefsLoaded(true);
	}, []);

	// Persist only after the first read, or the defaults would overwrite them.
	useEffect(() => {
		if (!prefsLoaded || typeof window === "undefined") return;
		try {
			window.localStorage.setItem(
				PREFS_KEY,
				JSON.stringify({
					autoSpeak,
					speed,
					language,
					autoLanguage,
					gameSound,
					overlay,
				}),
			);
		} catch {
			// Private browsing throws. Preferences are a convenience, not a feature.
		}
	}, [
		autoSpeak,
		autoLanguage,
		gameSound,
		language,
		overlay,
		prefsLoaded,
		speed,
	]);

	// A 404 or a disabled module both mean "no voice": unavailable, not an error.
	useEffect(() => {
		let live = true;
		fetchVoiceConfig().then((config) => {
			if (!live) return;
			setAvailable(Boolean(config) && typeof MediaRecorder !== "undefined");
			// The per-persona pace the server has always sent. Kept, not discarded.
			personaSpeeds.current = new Map(
				(config?.personas ?? []).map((entry) => [entry.persona, entry.speed]),
			);
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
		// Releasing every track is what turns the browser's recording indicator off.
		stream.current?.getTracks().forEach((track) => {
			track.stop();
		});
		stream.current = null;
	}, []);

	const showNote = useCallback(
		(kind: NoteKind) => {
			// The chosen personality colours even the bad news. "Mic not working.
			// Up to you." is The Unbothered being itself where a default note
			// would break character -- overrides exist only where the register
			// genuinely differs, and every other overlay keeps the plain text.
			const flavoured = OVERLAY_NOTES[overlay]?.[kind];
			setNote({
				kind,
				...NOTES[kind],
				...(flavoured ? { text: flavoured } : {}),
			});
		},
		[overlay],
	);

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
				// `transcribe` takes no external signal, so "aborted" cannot arrive here today.
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

		// The bars read as "something is being heard".
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
		// Abort the synthesis too, not just the playback.
		synthesis.current?.abort();
		synthesis.current = null;
		// And the browser's own voice, which is a separate engine entirely.
		if (typeof window !== "undefined" && "speechSynthesis" in window) {
			window.speechSynthesis.cancel();
		}
		audio.current?.pause();
		audio.current = null;
		if (objectUrl.current) {
			URL.revokeObjectURL(objectUrl.current);
			objectUrl.current = null;
		}
		setPlayingId(null);
		setPausedId(null);
	}, []);

	/** Stop on the way out, as well as on every deliberate interruption. */
	useEffect(() => stopPlayback, [stopPlayback]);

	/** Play an answer aloud, pause it if it is already playing, or resume it if it was paused. */
	const play = useCallback(
		async (id: number, text: string) => {
			if (playingId === id) {
				// Two engines. The ASPIRE voice is an <audio> element; the
				// browser fallback is speechSynthesis, which has no element at
				// all -- pausing only `audio.current` left the device voice
				// talking straight through the button. This was the report
				// "when you play it and try to stop it it does not stop".
				if (audio.current) {
					audio.current.pause();
				} else if (
					typeof window !== "undefined" &&
					"speechSynthesis" in window
				) {
					window.speechSynthesis.pause();
				}
				setPlayingId(null);
				setPausedId(id);
				return;
			}

			if (pausedId === id) {
				if (audio.current) {
					setPausedId(null);
					setPlayingId(id);
					try {
						await audio.current.play();
					} catch {
						stopPlayback();
					}
					return;
				}
				if (
					typeof window !== "undefined" &&
					"speechSynthesis" in window &&
					window.speechSynthesis.paused
				) {
					setPausedId(null);
					setPlayingId(id);
					window.speechSynthesis.resume();
					return;
				}
				// Nothing left to resume: fall through and start this answer fresh.
			}

			stopPlayback();
			const controller = new AbortController();
			synthesis.current = controller;
			let url: string;
			try {
				// Playback starts on the vendor's first chunk, not after the whole file.
				url = await speakStream(
					text,
					language,
					threadId,
					persona,
					controller.signal,
				);
			} catch (error) {
				// An abort is always this component's own doing, so it earns no note.
				if (error instanceof VoiceError) {
					if (error.failure === "use-browser") {
						// The server has no voice it will use and said to try the
						// browser. Reading in a plain device voice is worse than
						// Kaleb's own and far better than "voice is offline" over a
						// working speech engine.
						const spoke = speakInBrowser(
							text,
							language,
							(personaSpeeds.current.get(persona ?? "") ?? 1) *
								(Number(speed) || 1),
							() => setPlayingId(null),
						);
						// The play button must reflect what is happening, and if
						// the device has no speech engine at all then "offline"
						// is finally the true thing to say.
						if (spoke) {
							setPausedId(null);
							setPlayingId(id);
							showNote("use-browser");
						} else {
							showNote("offline");
						}
						return;
					}
					if (error.failure !== "aborted") showNote(error.failure);
				} else {
					showNote("offline");
				}
				return;
			}

			// Cancelled while the bytes were arriving.
			if (controller.signal.aborted) {
				URL.revokeObjectURL(url);
				return;
			}
			synthesis.current = null;

			objectUrl.current = url;
			const element = new Audio(url);
			// The persona's own pace, then the reader's preference on top of it.
			// Two different things: 0.88 is how Skye reads to a five-year-old,
			// and the preference is a reader saying "faster than that, please".
			// Using only the preference delivered every persona identically.
			element.playbackRate =
				(personaSpeeds.current.get(persona ?? "") ?? 1) * (Number(speed) || 1);
			element.onended = () => stopPlayback();
			audio.current = element;
			setPausedId(null);
			setPlayingId(id);

			try {
				await element.play();
			} catch {
				// A browser can refuse to start audio that the user did not ask for directly.
				setPlayingId(null);
				setPausedId(id);
			}
		},
		// `persona` belongs here: it is passed to the speech call, so without it
		// `play` closes over whoever was selected when this callback was last
		// built. Switching guide and pressing Play then speaks in the previous
		// guide's voice -- which matters more now that each guide has a face and a
		// voice of their own, and a child would hear the mismatch before anyone
		// reading the code would.
		[
			language,
			pausedId,
			persona,
			playingId,
			showNote,
			speed,
			stopPlayback,
			threadId,
		],
	);

	// A speed change applies to what is already playing, not just the next answer.
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
		autoLanguage,
		overlay,
		setOverlay,
		enableAutoLanguage,
		gameSound,
		toggleGameSound: () => setGameSound((on) => !on),
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
