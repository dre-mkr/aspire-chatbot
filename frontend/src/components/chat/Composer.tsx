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

/**
 * The voice settings panel, fetched only where voice actually exists.
 *
 * `VOICE_ENABLED` is a *server* flag. When it is off the endpoints 404, the mic
 * is unavailable and this panel is unreachable — and it still shipped in the
 * initial chunk, 5KB of code that could never execute. Gated on the runtime
 * config response now, so a deployment with voice off never downloads it.
 *
 * `import type` above rather than a value import: the props type is needed at
 * compile time and must not drag the module into the graph.
 */
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

/**
 * The backend's own cap on `message` (`backend/app/schemas.py`).
 *
 * The textarea had no limit at all, so a long paste was committed to the
 * transcript as a user bubble, sent, and rejected with 422 — and `canRetry` is
 * false for 4xx, so no retry was offered and the orphaned question sat there
 * with no route forward. Exactly the state `openPast`'s recovery turn exists to
 * prevent.
 *
 * Enforced in the box instead, where it is preventable rather than reportable.
 */
const MAX_CHARS = 8000;

/**
 * When the counter appears.
 *
 * A character count on an empty box is clutter and, worse, reads as a target.
 * This is a chat with a five-year-old at one end; nobody should be told they
 * have 8,000 characters to fill. It shows only once the limit is close enough
 * to be worth knowing about.
 */
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
	const canSend = draft.trim().length > 0 && !busy;
	const [spaceHeld, setSpaceHeld] = useState(false);
	const touch = useMediaQuery(TOUCH);
	const fieldRef = useRef<HTMLTextAreaElement>(null);
	const counterId = useId();
	const nearLimit = draft.length >= COUNTER_FROM;

	/**
	 * Put the cursor in the box so a new chat can be typed into without a click.
	 *
	 * Not on a touchscreen. Focusing a textarea there summons the on-screen
	 * keyboard, which on a 320px viewport eats most of the screen — so opening
	 * the app would bury the greeting and the suggestion chips under a keyboard
	 * nobody asked for. The pointer is the tell, and it is read from
	 * `matchMedia` directly rather than through `useMediaQuery`: that hook
	 * reports `false` for the first client paint to keep hydration quiet, which
	 * is precisely the paint this effect runs on.
	 */
	useEffect(() => {
		if (window.matchMedia(TOUCH).matches) return;
		fieldRef.current?.focus();
	}, [focusSignal]);

	/**
	 * Stop, then put focus somewhere real.
	 *
	 * The stop and send buttons carry distinct keys so React unmounts rather
	 * than reusing the node — which is what stopped a click on Stop from
	 * submitting the form. The cost is that the button being pressed
	 * disappears, so focus falls to <body> and a keyboard user is dropped out
	 * of the tab ring at the exact moment they asked for an exit. The composer
	 * is where they were and where they are most likely to go next.
	 */
	function handleStop() {
		onStop();
		fieldRef.current?.focus();
	}

	const listening = voice.phase === "listening";
	const transcribing = voice.phase === "transcribing";
	const holdToTalk = voice.phase === "rest" && voice.micState === "ready";

	function submit() {
		if (!canSend) return;
		onSend(draft);
		onDraftChange("");
	}

	function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
		// Escape abandons a recording rather than sending anything.
		if (event.key === "Escape" && (listening || transcribing)) {
			event.preventDefault();
			voice.cancel();
			return;
		}

		// Otherwise Escape leaves the box. Stopped from bubbling so it does not
		// also close whatever the composer happens to sit inside.
		if (event.key === "Escape") {
			event.preventDefault();
			event.stopPropagation();
			event.currentTarget.blur();
			return;
		}

		// Space is hold-to-talk, but only in an empty box — otherwise it is just
		// a space in the middle of a sentence. The placeholder says so, because a
		// shortcut you discover by triggering it is a surprise, not a shortcut.
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
	// Without this the key-up never arrives and the recording runs to its cap.
	function handleBlur() {
		if (!spaceHeld) return;
		setSpaceHeld(false);
		if (listening) voice.stop();
	}

	// The Space hint is the only thing that tells anyone hold-to-talk exists, but
	// it is addressed to a keyboard. On a phone — the device this is mostly used
	// on — it named a key that is not there and pointed away from the mic button
	// that does the same job.
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
					{/* `role="status"` and polite: a screen reader is told how much room
					    is left as it runs out, without interrupting typing. */}
					{nearLimit ? (
						<p
							id={counterId}
							className="composer__counter"
							role="status"
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
						{/* First in the row, because it is the widest-reaching of these
						    controls: it changes the reading level, the voice and which
						    games are offered, where "Explain it simply" changes only how
						    one answer is worded. */}
						<PersonaPicker persona={persona} onChange={onPersonaChange} />

						{/* Voice settings live here, not beside the mic. The mic is
						    already a voice affordance; a second voice-looking control
						    next to it would leave neither meaning anything.

						    Only where voice exists. `voice.available` is the runtime
						    config answer, so a deployment with VOICE_ENABLED off does
						    not render — or download — a panel for a feature it does
						    not have. No fallback: nothing was here before it loaded
						    and nothing should be, or the tool row would reflow. */}
						{voice.available ? (
							<Suspense fallback={null}>
								<VoiceSettings voice={voice} />
							</Suspense>
						) : null}

						{/* The label collapses to the icon on a narrow screen rather than
						    the whole control disappearing — this is the plain-words
						    toggle, and it has no other entry point. */}
						{/* The title carries the label when the visible one is hidden
						    under 620px — otherwise this is a bare sparkle whose only
						    state cue is a tint. */}
						<button
							type="button"
							className="tool-btn"
							aria-pressed={simpleMode}
							onClick={onToggleSimpleMode}
							title={
								simpleMode
									? "Explain it simply: on"
									: "Explain it simply: off"
							}
						>
							<SparkIcon />
							{/* Clipped, not removed, under 620px — so it still names the
							    button for a screen reader at every width. */}
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

							{/* While a reply is in flight the send button becomes a
							    stop, rather than sitting there enabled and quietly
							    orphaning the question already running. */}
							{/* The keys matter. Without them React sees one <button> in
							    one position and reuses the DOM node, mutating `type`
							    from "button" to "submit" during the flush inside click
							    dispatch. The browser then runs its post-dispatch default
							    action against the *new* type, so a click on Stop fired a
							    submit -- sending whatever was in the box as a fresh
							    question and orphaning the one being stopped. That is the
							    exact failure this control was added to prevent.
							    Distinct keys make React unmount and mount instead. */}
							{busy ? (
								<button
									key="stop"
									type="button"
									className="composer__send composer__send--stop"
									onClick={(event) => {
										// Belt and braces: this button lives inside the form,
										// so nothing it does should ever reach the submit path.
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
								>
									<SendIcon />
									<span className="sr-only">Send message</span>
								</button>
							)}
						</div>
					</div>
				)}
			</form>
		</div>
	);
}
