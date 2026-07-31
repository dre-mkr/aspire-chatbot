import { type KeyboardEvent, useState } from "react";
import { MicIcon, SendIcon, SparkIcon } from "#/components/icons";
import type { MicState, VoicePhase } from "#/lib/aspire/use-voice";
import { VoiceListening, VoiceTranscribing } from "./Voice";

interface ComposerProps {
	onSend: (text: string) => void;
	/** "Explain it simply" — asks for the plain-words version of every answer. */
	simpleMode: boolean;
	onToggleSimpleMode: () => void;
	/** Draft is lifted so a transcript can land in it for review before sending. */
	draft: string;
	onDraftChange: (value: string) => void;
	voice: {
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

const MIC_TITLE: Record<MicState, string> = {
	ready: "Speak your question",
	denied: "Microphone blocked",
	off: "Voice unavailable",
};

export function Composer({
	onSend,
	simpleMode,
	onToggleSimpleMode,
	draft,
	onDraftChange,
	voice,
}: ComposerProps) {
	const canSend = draft.trim().length > 0;
	const [spaceHeld, setSpaceHeld] = useState(false);

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

	const placeholder = listening
		? "Speak now — your words appear here"
		: transcribing
			? "Transcribing…"
			: holdToTalk
				? "Ask me anything, or hold Space to talk"
				: "Ask me anything...";

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
						value={draft}
						onChange={(event) => onDraftChange(event.target.value)}
						onKeyDown={handleKeyDown}
						onKeyUp={handleKeyUp}
						onBlur={handleBlur}
						placeholder={placeholder}
					/>
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
						{/* The label collapses to the icon on a narrow screen rather than
						    the whole control disappearing — this is the plain-words
						    toggle, and it has no other entry point. */}
						<button
							type="button"
							className="tool-btn"
							aria-pressed={simpleMode}
							onClick={onToggleSimpleMode}
						>
							<SparkIcon />
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

							<button
								type="submit"
								className="composer__send"
								disabled={!canSend}
							>
								<SendIcon />
								<span className="sr-only">Send message</span>
							</button>
						</div>
					</div>
				)}
			</form>
		</div>
	);
}
