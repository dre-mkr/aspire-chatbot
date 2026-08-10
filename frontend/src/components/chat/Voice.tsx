import { CloseIcon, MicIcon } from "#/components/icons";
import { formatSeconds, type VoiceNote as Note } from "#/lib/aspire/use-voice";

/** The listening indicator: ASPIRE's brand star, repeated and rising outward. */
const STAR = "M0,-6 L1.6,-1.6 L6,0 L1.6,1.6 L0,6 L-1.6,1.6 L-6,0 L-1.6,-1.6 Z";

/** Rank 0 is the centre; higher ranks light up only at higher levels. */
const lit = (rank: number, level: number) => (level >= rank ? 1 : 0.18);

export function ListeningStars({ level }: { level: number }) {
	const points: Array<[number, number, number, number]> = [
		[160, 58, 1.15, 0],
		[124, 50, 1, 1],
		[196, 50, 1, 1],
		[88, 41, 0.88, 2],
		[232, 41, 0.88, 2],
		[52, 31, 0.76, 3],
		[268, 31, 0.76, 3],
		[16, 20, 0.64, 4],
		[304, 20, 0.64, 4],
	];

	return (
		<svg
			className="voice-stars"
			viewBox="4 8 312 62"
			width="188"
			height="44"
			aria-hidden="true"
		>
			<circle cx="160" cy="58" r="13" fill="var(--wash-m-16)" />
			{points.map(([x, y, scale, rank]) => (
				<path
					key={`${x}-${y}`}
					d={STAR}
					fill="var(--magenta)"
					opacity={lit(rank, level)}
					transform={`translate(${x},${y}) scale(${scale})`}
				/>
			))}
		</svg>
	);
}

/** The smaller rising run shown beside a playing answer. */
export function PlayingStars() {
	const points: Array<[number, number, number]> = [
		[10, 30, 0.62],
		[43, 25, 0.72],
		[76, 19, 0.82],
		[109, 13, 0.92],
		[140, 8, 1],
	];

	return (
		<svg
			className="voice-stars voice-stars--play"
			viewBox="0 0 150 40"
			width="74"
			height="20"
			aria-hidden="true"
		>
			{points.map(([x, y, scale], index) => (
				<path
					key={`${x}-${y}`}
					d={STAR}
					fill="var(--magenta)"
					transform={`translate(${x},${y}) scale(${scale})`}
					style={{ animationDelay: `${index * 120}ms` }}
				/>
			))}
		</svg>
	);
}

interface ConsentProps {
	onAllow: () => void;
	onDeny: () => void;
}

/** Shown before the microphone is ever opened. */
export function VoiceConsent({ onAllow, onDeny }: ConsentProps) {
	return (
		<section className="voice-consent" aria-label="Microphone permission">
			<div className="voice-consent__head">
				<span className="orb" aria-hidden="true" />
				<span className="voice-consent__title">Before I listen</span>
			</div>

			<ul className="voice-consent__points">
				<li>
					The microphone runs only while you are speaking. It never listens in
					the background.
				</li>
				<li>
					Your voice becomes text in a few seconds, then the audio is deleted.
					We never keep a recording.
				</li>
				<li>
					The text lands in this box so you can fix it before it is sent.
					Nothing sends on its own.
				</li>
			</ul>

			<div className="voice-consent__actions">
				<button
					type="button"
					className="voice-btn voice-btn--primary"
					onClick={onAllow}
				>
					<MicIcon size={16} />
					Allow microphone
				</button>
				<button
					type="button"
					className="voice-btn voice-btn--quiet"
					onClick={onDeny}
				>
					Not now
				</button>
				<span className="voice-consent__aside">
					A grown-up can turn this off in voice options.
				</span>
			</div>
		</section>
	);
}

interface NoteProps {
	note: Note;
	onAction: () => void;
	onDismiss: () => void;
}

export function VoiceNote({ note, onAction, onDismiss }: NoteProps) {
	// <output> rather than a div with role="status": it is a live region announcing the result of the recording the…
	return (
		<output className="voice-note" data-tone={note.tone}>
			<span className="voice-note__icon" aria-hidden="true">
				<MicIcon size={15} />
			</span>
			<span className="voice-note__text">{note.text}</span>
			<button type="button" className="voice-note__action" onClick={onAction}>
				{note.action}
			</button>
			<button
				type="button"
				className="icon-btn icon-btn--sm"
				onClick={onDismiss}
			>
				<CloseIcon />
				<span className="sr-only">Dismiss</span>
			</button>
		</output>
	);
}

interface ListeningProps {
	elapsed: number;
	level: number;
	maxSeconds: number;
	onCancel: () => void;
	onStop: () => void;
}

export function VoiceListening({
	elapsed,
	level,
	maxSeconds,
	onCancel,
	onStop,
}: ListeningProps) {
	const remaining = maxSeconds - elapsed;
	const hint =
		remaining <= 10
			? `Ten seconds left — I stop at ${formatSeconds(maxSeconds)}.`
			: "Hold Space, or click Stop when you are done.";

	return (
		<div className="voice-live">
			<span className="voice-rec">
				<span className="voice-rec__dot" aria-hidden="true" />
				<span className="voice-rec__label">REC</span>
				<span className="voice-rec__time">
					{formatSeconds(elapsed)} / {formatSeconds(maxSeconds)}
				</span>
			</span>

			<ListeningStars level={level} />

			<span className="voice-live__hint">{hint}</span>

			<div className="voice-live__actions">
				<button
					type="button"
					className="voice-btn voice-btn--quiet"
					onClick={onCancel}
				>
					<CloseIcon size={15} />
					Cancel
				</button>
				<button
					type="button"
					className="voice-btn voice-btn--stop"
					onClick={onStop}
				>
					<span className="voice-btn__square" aria-hidden="true" />
					Stop
				</button>
			</div>
		</div>
	);
}

export function VoiceTranscribing({
	captured,
	onCancel,
}: {
	captured: number;
	onCancel: () => void;
}) {
	return (
		<output className="voice-live voice-live--busy">
			<span className="voice-spinner" aria-hidden="true" />
			<span className="voice-live__title">Transcribing</span>
			<span className="voice-live__hint">Turning your voice into text.</span>
			<span className="voice-live__captured">
				{formatSeconds(captured)} captured
			</span>
			<button
				type="button"
				className="voice-btn voice-btn--quiet voice-live__trailing"
				onClick={onCancel}
			>
				<CloseIcon size={15} />
				Cancel
			</button>
		</output>
	);
}
