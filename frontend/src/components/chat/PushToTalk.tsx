/** One large button. */
import { useCallback, useEffect, useRef, useState } from "react";
import {
	microphoneAvailable,
	type Recording,
	record,
	SILENCE_TIMEOUT_MS,
} from "../../lib/voice/stt";
import { stopSpeaking } from "../../lib/voice/tts";
import { useAgeBand } from "./AgeBandProvider";

/** A press shorter than this latches recording on rather than ending it. */
const TAP_MS = 400;

export function PushToTalk({
	locale = "en",
	token,
	onTranscript,
	disabled = false,
}: {
	locale?: string;
	token?: string;
	onTranscript: (text: string) => void;
	disabled?: boolean;
}) {
	const band = useAgeBand();
	const [listening, setListening] = useState(false);
	const [level, setLevel] = useState(0);
	const [problem, setProblem] = useState<string | null>(null);
	const session = useRef<Recording | null>(null);
	const pressedAt = useRef(0);
	const latched = useRef(false);

	const finish = useCallback(() => {
		const active = session.current;
		session.current = null;
		latched.current = false;
		setListening(false);
		setLevel(0);
		active?.stop();
	}, []);

	// A component unmounting mid-recording must release the microphone, or the browser keeps showing the recording…
	useEffect(() => {
		return () => {
			session.current?.cancel();
			session.current = null;
		};
	}, []);

	const start = useCallback(async () => {
		if (session.current || disabled) return;
		// Talking over the mascot is the normal case -- a child interrupts.
		stopSpeaking();
		setProblem(null);

		try {
			const active = await record({
				locale,
				token,
				onLevel: setLevel,
				onSilenceStop: () => {
					latched.current = false;
					setListening(false);
				},
			});
			session.current = active;
			setListening(true);

			const text = await active.transcript;
			session.current = null;
			setListening(false);
			setLevel(0);
			if (text) onTranscript(text);
		} catch (error) {
			console.error("[aspire] microphone unavailable", error);
			setProblem(
				"I could not hear you. You can type instead, or check the microphone.",
			);
			setListening(false);
			session.current = null;
		}
	}, [disabled, locale, onTranscript, token]);

	if (!microphoneAvailable()) return null;

	const size = band.micSize;
	const ring = 1 + level * 0.12;

	return (
		<div style={{ display: "grid", justifyItems: "center", gap: "0.375rem" }}>
			<button
				type="button"
				disabled={disabled}
				// Announced state, not just a visual one.
				aria-pressed={listening}
				aria-label={listening ? "Listening. Tap to stop." : "Hold to talk"}
				onPointerDown={(event) => {
					event.preventDefault();
					pressedAt.current = Date.now();
					if (listening && latched.current) {
						finish();
						return;
					}
					void start();
				}}
				onPointerUp={() => {
					const held = Date.now() - pressedAt.current;
					if (held < TAP_MS) {
						// A tap latches it on. The next tap ends it.
						latched.current = true;
						return;
					}
					finish();
				}}
				onPointerLeave={() => {
					if (!latched.current && listening) finish();
				}}
				style={{
					width: size,
					height: size,
					borderRadius: "50%",
					border: `3px solid ${listening ? "var(--magenta)" : "var(--plum)"}`,
					background: listening ? "var(--wash-m-16)" : "var(--wash-6)",
					color: listening ? "var(--magenta)" : "var(--plum-deep)",
					fontSize: `${Math.round(size / 4)}px`,
					cursor: disabled ? "default" : "pointer",
					display: "grid",
					placeItems: "center",
					// Scale only -- it cannot reflow anything around it, so a pulsing ring never moves the layout under a child's t…
					transform: `scale(${listening ? ring : 1})`,
					transition: "transform 90ms linear, background-color 160ms ease",
					touchAction: "none",
				}}
			>
				<span aria-hidden="true">🎤</span>
			</button>

			<p
				aria-live="polite"
				style={{
					margin: 0,
					fontSize: "calc(var(--band-type, 16px) - 2px)",
					color: listening ? "var(--magenta)" : "var(--quiet)",
					fontWeight: listening ? 700 : 400,
				}}
			>
				{listening ? "Listening…" : "Hold to talk"}
			</p>

			{problem ? (
				<p
					role="alert"
					style={{
						margin: 0,
						fontSize: "calc(var(--band-type, 16px) - 2px)",
						color: "var(--danger)",
						textAlign: "center",
						maxWidth: "18rem",
					}}
				>
					{problem}
				</p>
			) : null}

			{listening ? (
				<p style={{ display: "none" }}>
					{/* Documented rather than rendered: recording ends itself after {SILENCE_TIMEOUT_MS}ms of quiet, so a child who… */}
					{SILENCE_TIMEOUT_MS}
				</p>
			) : null}
		</div>
	);
}
