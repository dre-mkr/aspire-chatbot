import {
	type KeyboardEvent,
	lazy,
	Suspense,
	useEffect,
	useId,
	useRef,
	useState,
} from "react";
import { MicIcon, SendIcon, SparkIcon, StopIcon } from "#/components/icons";
import type { PersonaId } from "#/lib/aspire/personas";
import type { MicState, VoicePhase } from "#/lib/aspire/use-voice";
import { useMediaQuery } from "#/lib/use-media-query";
import { PersonaPicker } from "./PersonaPicker";
import { VoiceListening, VoiceTranscribing } from "./Voice";
import type { VoiceSettingsProps } from "./VoiceSettings";

/** The voice settings panel, fetched only where voice actually exists. */
const VoiceSettings = lazy(() =>
	import("./VoiceSettings").then((m) => ({ default: m.VoiceSettings })),
);

/** No hover means no pointer to hover with, which here means no Space key. */
const TOUCH = "(hover: none)";

interface ComposerProps {
	onSend: (text: string) => void;
	/** A reply is in flight: send is unavailable and becomes a stop control. */
	busy: boolean;
	onStop: () => void;
	/** "Explain it simply" — asks for the plain-words version of every answer. */
	simpleMode: boolean;
	onToggleSimpleMode: () => void;
	/** Who the assistant is answering for. Null means nobody has said. */
	persona: PersonaId | null;
	onPersonaChange: (next: PersonaId | null) => void;
	/** Draft is lifted so a transcript can land in it for review before sending. */
	draft: string;
	onDraftChange: (value: string) => void;
	/** Bumped whenever the composer should take the cursor. */
	focusSignal: number;
	/** Recording state, plus everything the settings panel needs now it lives here. */
	voice: VoiceSettingsProps["voice"] & {
		phase: VoicePhase;
		micState: MicState;
		elapsed: number;
		captured: number;
		level: number;
		maxSeconds: number;
		start: () => void;
		stop: () => void;
		cancel: () => void;
	};
}

/** The backend's own cap on `message` (`backend/app/schemas.py`). */
const MAX_CHARS = 8000;

/** When the counter appears. */
const COUNTER_FROM = MAX_CHARS - 500;

const MIC_TITLE: Record<MicState, string> = {
	ready: "Speak your question",
	denied: "Microphone blocked",
	off: "Voice unavailable",
};

export function Composer({
	onSend,
	busy,
	onStop,
	simpleMode,
	onToggleSimpleMode,
	persona,
	onPersonaChange,
	draft,
	onDraftChange,
	focusSignal,
	voice,
}: ComposerProps) {
	const [spaceHeld, setSpaceHeld] = useState(false);
	const touch = useMediaQuery(TOUCH);
	const fieldRef = useRef<HTMLTextAreaElement>(null);
	const counterId = useId();
	const nearLimit = draft.length >= COUNTER_FROM;

	/**
	 * Whether this composer is attached yet.
	 *
	 * Both routes are full-document SSR, so the box is painted, focusable and
	 * typeable well before React reaches it — measured at 2.0 to 4.7 seconds
	 * ahead of it on a throttled machine. Until then `draft` is empty however
	 * much has been typed, so `canSend` is false and the send button sits
	 * disabled with nothing to say for itself. Somebody types a question,
	 * presses send, and nothing happens.
	 *
	 * It cannot be made to send in that window — there is no handler to run yet
	 * — but it can stop pretending to be ready. Below, the button says it is
	 * starting up rather than that the question is unsendable, and `submit`
	 * reads the field itself so a state that has not caught up cannot eat one.
	 */
	const [live, setLive] = useState(false);
	useEffect(() => setLive(true), []);

	const canSend = draft.trim().length > 0 && !busy;

	/** Put the cursor in the box so a new chat can be typed into without a click. */
	// biome-ignore lint/correctness/useExhaustiveDependencies: focusSignal is the trigger, not an input
	useEffect(() => {
		if (window.matchMedia(TOUCH).matches) return;
		fieldRef.current?.focus();
	}, [focusSignal]);

	/** Stop, then put focus somewhere real. */
	function handleStop() {
		onStop();
		fieldRef.current?.focus();
	}

	const listening = voice.phase === "listening";
	const transcribing = voice.phase === "transcribing";
	const holdToTalk = voice.phase === "rest" && voice.micState === "ready";

	function submit() {
		// The field, not just the state. They are the same value once React is
		// attached; before that the field is the only one that has the question.
		const text = (draft || fieldRef.current?.value || "").trim();
		if (!text || busy) return;
		onSend(text);
		onDraftChange("");
	}

	function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
		// Escape abandons a recording rather than sending anything.
		if (event.key === "Escape" && (listening || transcribing)) {
			event.preventDefault();
			voice.cancel();
			return;
		}

		// Otherwise Escape leaves the box.
		if (event.key === "Escape") {
			event.preventDefault();
			event.stopPropagation();
			event.currentTarget.blur();
			return;
		}

		// Space is hold-to-talk only in an empty box; otherwise it is just a space.
		if (event.code === "Space" && !event.repeat && !draft && holdToTalk) {
			event.preventDefault();
			setSpaceHeld(true);
			voice.start();
			return;
		}

		// Enter sends; Shift+Enter is how you get a second line.
		if (event.key === "Enter" && !event.shiftKey) {
			event.preventDefault();
			submit();
		}
	}

	function handleKeyUp(event: KeyboardEvent<HTMLTextAreaElement>) {
		if (event.code === "Space" && spaceHeld) {
			setSpaceHeld(false);
			if (listening) voice.stop();
		}
	}

	// Focus can leave mid-hold — a click elsewhere, a screen reader moving on.
	function handleBlur() {
		if (!spaceHeld) return;
		setSpaceHeld(false);
		if (listening) voice.stop();
	}

	// The Space hint is the only sign hold-to-talk exists, so it is keyboard-only.
	const placeholder = listening
		? "Speak now — your words appear here"
		: transcribing
			? "Transcribing…"
			: !holdToTalk
				? "Ask me anything..."
				: touch
					? "Ask me anything, or tap the mic to talk"
					: "Ask me anything, or hold Space to talk";

	return (
		<div className="composer-slot">
			<form
				className="composer"
				onSubmit={(event) => {
					event.preventDefault();
					submit();
				}}
			>
				<label className="sr-only" htmlFor="aspire-composer">
					Ask ASPIRE AI a question
				</label>
				<div className="composer__field">
					<textarea
						id="aspire-composer"
						ref={fieldRef}
						value={draft}
						maxLength={MAX_CHARS}
						onChange={(event) => onDraftChange(event.target.value)}
						onKeyDown={handleKeyDown}
						onKeyUp={handleKeyUp}
						onBlur={handleBlur}
						placeholder={placeholder}
						aria-describedby={nearLimit ? counterId : undefined}
					/>
					{/* Polite status: the room left is announced as it runs out, without interrupting. */}
					{nearLimit ? (
						<p
							id={counterId}
							className="composer__counter"
							aria-live="polite"
							data-full={draft.length >= MAX_CHARS || undefined}
						>
							{draft.length >= MAX_CHARS
								? "That is as long as a question can be."
								: `${MAX_CHARS - draft.length} characters left`}
						</p>
					) : null}
				</div>

				{listening ? (
					<VoiceListening
						elapsed={voice.elapsed}
						level={voice.level}
						maxSeconds={voice.maxSeconds}
						onCancel={voice.cancel}
						onStop={voice.stop}
					/>
				) : transcribing ? (
					<VoiceTranscribing
						captured={voice.captured}
						onCancel={voice.cancel}
					/>
				) : (
					<div className="composer__tools">
						{/* First in the row: it is the widest-reaching control here, reading level included. */}
						<PersonaPicker persona={persona} onChange={onPersonaChange} />

						{/* Voice settings live here, not beside the mic. */}
						{voice.available ? (
							<Suspense fallback={null}>
								<VoiceSettings voice={voice} />
							</Suspense>
						) : null}

						{/* Narrow screens collapse the label to the icon rather than dropping the control. */}
						{/* The title carries the label under 620px, where it is otherwise a bare sparkle. */}
						<button
							type="button"
							className="tool-btn"
							aria-pressed={simpleMode}
							onClick={onToggleSimpleMode}
							title={
								simpleMode ? "Explain it simply: on" : "Explain it simply: off"
							}
						>
							<SparkIcon />
							{/* Clipped, not removed, under 620px: it still names the button at every width. */}
							<span className="tool-btn__label">Explain it simply</span>
						</button>

						<div className="composer__end">
							<button
								type="button"
								className="composer__mic"
								data-mic={voice.micState}
								onClick={voice.start}
								disabled={voice.micState === "off"}
								title={MIC_TITLE[voice.micState]}
							>
								<MicIcon />
								<span className="sr-only">{MIC_TITLE[voice.micState]}</span>
							</button>

							{/* In flight, send becomes stop rather than sitting enabled and orphaned. */}
							{/* The keys matter. */}
							{busy ? (
								<button
									key="stop"
									type="button"
									className="composer__send composer__send--stop"
									onClick={(event) => {
										// This button lives inside the form; nothing it does should reach submit.
										event.preventDefault();
										handleStop();
									}}
								>
									<StopIcon />
									<span className="sr-only">Stop generating</span>
								</button>
							) : (
								<button
									key="send"
									type="submit"
									className="composer__send"
									disabled={!canSend}
									data-waking={!live || undefined}
									title={live ? undefined : "Starting up…"}
								>
									<SendIcon />
									<span className="sr-only">
										{live
											? "Send message"
											: "Starting up. Send is not ready yet."}
									</span>
								</button>
							)}
						</div>
					</div>
				)}
			</form>
		</div>
	);
}
