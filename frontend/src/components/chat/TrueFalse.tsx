import { useCallback, useEffect, useRef, useState } from "react";
import {
	CheckIcon,
	ExitIcon,
	EyeIcon,
	LampIcon,
	SparkIcon,
} from "#/components/icons";
import {
	type Closing,
	GameError,
	type GameState,
	type GameSummary,
	quitGame,
	type Reveal,
	skipWord,
	submitAnswer,
} from "#/lib/aspire/games";
import { useMediaQuery } from "#/lib/use-media-query";

/** True or false, played in the thread. */

/* Counts come from the round, never from the copy. */
const COPY = {
	sub: (total: number) =>
		`${total} ${total === 1 ? "statement" : "statements"}`,
	leave: "Leave game",
	close: "Close",
	skip: "Not sure — show me the answer",
	inputHint: "Press T or F.",
	meaning: "What this means",
	next: "Next statement",
	last: "See them all",
	completeLead: "That is all of them.",
	together: "What ties them together",
	exit: "Back to chat",
	exitNote: "Ask me to go deeper on any of these whenever you want.",
	right: (answer: string) => `You said ${answer} — that is right.`,
	wrong: (answer: string) => `Not this one — the answer is ${answer}.`,
	shown: (answer: string) => `Fair enough — the answer is ${answer}.`,
} as const;

type Copy = typeof COPY;

/** How the item was settled. Skipped is not a wrong answer. */
type Outcome = "correct" | "incorrect" | "skipped";

interface Settled {
	statement: string;
	reveal: Reveal;
	outcome: Outcome;
	/** What the player picked, or null when they asked to be shown. */
	chose: string | null;
}

interface TrueFalseProps {
	threadId: string;
	state: GameState;
	onChanged: (state: GameState | null) => void;
	/** Fires once, with the final numbers, the moment the set resolves. */
	onSummary?: (summary: GameSummary) => void;
}

export function TrueFalse({
	threadId,
	state,
	onChanged,
	onSummary,
}: TrueFalseProps) {
	const copy = COPY;

	const [settled, setSettled] = useState<Settled | null>(null);
	const [covered, setCovered] = useState<Array<Settled>>([]);
	const [summary, setSummary] = useState<GameSummary | null>(null);
	const [busy, setBusy] = useState(false);
	const [failure, setFailure] = useState<string | null>(null);

	const complete = summary !== null && settled === null;
	const choices = state.prompt.choices.length
		? state.prompt.choices
		: ["True", "False"];

	// A new statement clears whatever the last one resolved to.
	const itemKey = `${state.prompt.position}:${state.prompt.text}`;
	// biome-ignore lint/correctness/useExhaustiveDependencies: keyed reset
	useEffect(() => {
		setFailure(null);
	}, [itemKey]);

	const guard = useCallback(async (work: () => Promise<void>) => {
		setBusy(true);
		setFailure(null);
		try {
			await work();
		} catch (error) {
			setFailure(
				error instanceof GameError
					? error.message
					: "Something went wrong. Try again.",
			);
		} finally {
			setBusy(false);
		}
	}, []);

	const settle = useCallback(
		(entry: Settled, next: GameState | null, done: GameSummary | null) => {
			setCovered((current) => [...current, entry]);
			setSettled(entry);
			setSummary(done);
			// The final numbers go up the moment they exist; `onChanged(null)` only fires on leave, after the wrap-up has b…
			if (done) onSummary?.(done);
			// Null means the round is over.
			if (next) onChanged(next);
		},
		[onChanged, onSummary],
	);

	const choose = useCallback(
		(value: string) =>
			guard(async () => {
				const statement = state.prompt.text;
				const result = await submitAnswer(threadId, value);
				if (result.unreadable) {
					setFailure(result.unreadable);
					return;
				}
				if (!result.reveal) {
					// Cannot happen for true/false — a wrong answer resolves the item — but the type allows it, so say something ho…
					setFailure("That did not settle the statement. Try again.");
					return;
				}
				settle(
					{
						statement,
						reveal: result.reveal,
						outcome: result.correct ? "correct" : "incorrect",
						chose: value,
					},
					result.game,
					result.summary,
				);
			}),
		[guard, settle, state.prompt.text, threadId],
	);

	const skip = () =>
		guard(async () => {
			const statement = state.prompt.text;
			const result = await skipWord(threadId);
			settle(
				{ statement, reveal: result.reveal, outcome: "skipped", chose: null },
				result.game,
				result.summary,
			);
		});

	const leave = () =>
		guard(async () => {
			if (!complete) await quitGame(threadId).catch(() => undefined);
			onChanged(null);
		});

	const advance = () => setSettled(null);

	// T and F answer the statement, as the design specifies.
	const asking = settled === null && !complete;
	const cardRef = useRef<HTMLElement>(null);
	// Whether the shortcut can actually fire right now, so the hint can stop claiming otherwise.
	const [keyboardArmed, setKeyboardArmed] = useState(false);
	// And never on a device with no keys to press.
	const touch = useMediaQuery("(hover: none)");

	useEffect(() => {
		const card = cardRef.current;
		if (!card) return;

		const onIn = () => setKeyboardArmed(true);
		// `focusout` fires before focus lands, so `document.activeElement` is still <body> here — `relatedTarget` is wh…
		const onOut = (event: FocusEvent) =>
			setKeyboardArmed(card.contains(event.relatedTarget as Node | null));

		setKeyboardArmed(card.contains(document.activeElement));
		card.addEventListener("focusin", onIn);
		card.addEventListener("focusout", onOut);
		return () => {
			card.removeEventListener("focusin", onIn);
			card.removeEventListener("focusout", onOut);
		};
	}, []);

	useEffect(() => {
		if (!asking || busy) return;
		const card = cardRef.current;
		if (!card) return;

		const onKey = (event: KeyboardEvent) => {
			const tag = (event.target as HTMLElement | null)?.tagName;
			if (tag === "TEXTAREA" || tag === "INPUT") return;
			if (event.metaKey || event.ctrlKey || event.altKey) return;
			const key = event.key.toLowerCase();
			if (key !== "t" && key !== "f") return;
			event.preventDefault();
			void choose(key === "t" ? "true" : "false");
		};

		card.addEventListener("keydown", onKey);
		return () => card.removeEventListener("keydown", onKey);
	}, [asking, busy, choose]);

	const label = `Statement ${state.prompt.position} of ${state.prompt.total}`;

	return (
		// tabIndex -1 so a click anywhere on the card puts focus inside it, which is what arms the T/F shortcut scoped…
		<section className="game tf" aria-label={label} ref={cardRef} tabIndex={-1}>
			<header className="game__head">
				<span className="game__badge" aria-hidden="true">
					<SparkIcon />
				</span>
				<span className="game__title">{state.display_name}</span>
				<span className="game__sub">{copy.sub(state.prompt.total)}</span>

				<div className="game__steps" aria-hidden="true">
					{Array.from({ length: state.prompt.total }, (_, i) => {
						const n = i + 1;
						const done =
							n < state.prompt.position ||
							(n === state.prompt.position && settled !== null);
						const now = n === state.prompt.position && !done && !complete;
						return (
							<span
								key={n}
								className="game__step"
								data-state={done ? "done" : now ? "now" : "next"}
							>
								{done || now ? n : null}
							</span>
						);
					})}
				</div>

				<button
					type="button"
					className="game__leave"
					onClick={leave}
					disabled={busy}
				>
					<ExitIcon />
					{complete ? copy.close : copy.leave}
				</button>
			</header>

			<div className="game__body">
				{failure ? <output className="game__failure">{failure}</output> : null}

				{complete ? (
					<CompletePanel
						copy={copy}
						covered={covered}
						closing={summary?.closing ?? null}
						onExit={leave}
					/>
				) : settled ? (
					<SettledPanel
						copy={copy}
						label={label}
						settled={settled}
						choices={choices}
						isLast={summary !== null}
						position={state.prompt.position}
						total={state.prompt.total}
						onNext={advance}
					/>
				) : (
					<>
						<p className="game__eyebrow">
							<span>{label}</span>
							<span className="game__rule" aria-hidden="true" />
						</p>

						<p className="tf__statement">{state.prompt.text}</p>

						{/* No wrapper role: the section's own label already announces which statement this is, and each button says what… */}
						<div className="tf__choices">
							{choices.map((choice) => (
								<button
									key={choice}
									type="button"
									className="tf__choice"
									onClick={() => choose(choice.toLowerCase())}
									disabled={busy}
								>
									{choice}
								</button>
							))}
						</div>

						<div className="game__actions">
							<button
								type="button"
								className="game__btn game__btn--ghost"
								onClick={skip}
								disabled={busy}
							>
								{copy.skip}
							</button>
							{/* Only claimed while it is true. */}
							{keyboardArmed && !touch ? (
								<span className="game__count tf__hint">{copy.inputHint}</span>
							) : null}
						</div>
					</>
				)}
			</div>
		</section>
	);
}

function ResultIcon({ outcome }: { outcome: Outcome }) {
	if (outcome === "correct") return <CheckIcon />;
	if (outcome === "incorrect") return <LampIcon />;
	return <EyeIcon />;
}

/** The two verdicts, side by side. */
function VerdictPills({
	choices,
	answer,
	chose,
}: {
	choices: Array<string>;
	answer: string;
	chose: string | null;
}) {
	return (
		<div className="tf__pills">
			{choices.map((choice) => {
				const isAnswer = choice.toLowerCase() === answer.toLowerCase();
				const isMine =
					!isAnswer &&
					chose !== null &&
					choice.toLowerCase() === chose.toLowerCase();
				return (
					<div key={choice} className="tf__pill-slot">
						<span
							className="tf__pill"
							data-answer={isAnswer || undefined}
							data-mine={isMine || undefined}
						>
							{isAnswer ? <CheckIcon /> : null}
							{choice}
						</span>
						<span className="tf__pill-tag" data-mine={isMine || undefined}>
							{isAnswer ? "The answer" : isMine ? "You chose" : ""}
						</span>
					</div>
				);
			})}
		</div>
	);
}

function SettledPanel({
	copy,
	label,
	settled,
	choices,
	isLast,
	position,
	total,
	onNext,
}: {
	copy: Copy;
	label: string;
	settled: Settled;
	choices: Array<string>;
	isLast: boolean;
	position: number;
	total: number;
	onNext: () => void;
}) {
	const { reveal, outcome, chose } = settled;
	const lead =
		outcome === "correct"
			? copy.right(reveal.answer)
			: outcome === "incorrect"
				? copy.wrong(reveal.answer)
				: copy.shown(reveal.answer);

	// Laid-out content when the set has it, the flat explanation when it does not.
	const paragraphs = reveal.paragraphs.length
		? reveal.paragraphs
		: [reveal.explanation];

	return (
		<div className="tf__settled">
			<p className="game__eyebrow">
				<span>{label}</span>
				<span className="game__rule" aria-hidden="true" />
			</p>
			<p className="tf__statement tf__statement--quiet">{settled.statement}</p>

			<p className="game__result" data-outcome={outcome}>
				<span className="game__result-icon" aria-hidden="true">
					<ResultIcon outcome={outcome} />
				</span>
				{lead}
			</p>

			<VerdictPills choices={choices} answer={reveal.answer} chose={chose} />

			<div className="game__meaning">
				<span className="game__meaning-label">
					<SparkIcon size={13} />
					{copy.meaning}
				</span>
				{reveal.takeaway ? (
					<span className="game__meaning-word tf__takeaway">
						{reveal.takeaway}
					</span>
				) : null}
				{paragraphs.map((text) => (
					<p key={text} className="game__meaning-text">
						{text}
					</p>
				))}

				{reveal.bullets.length > 0 ? (
					<div className="tf__bullets">
						{reveal.bullets.map((bullet) => (
							<div key={bullet.marker} className="tf__bullet">
								<span className="game__chip">{bullet.marker}</span>
								<span className="tf__bullet-text">
									<b>{bullet.label}</b>
									{bullet.text}
								</span>
							</div>
						))}
					</div>
				) : null}

				{reveal.after ? (
					<p className="game__meaning-text">{reveal.after}</p>
				) : null}
			</div>

			<div className="game__actions">
				<button
					type="button"
					className="game__btn game__btn--go"
					onClick={onNext}
				>
					{isLast ? copy.last : copy.next}
				</button>
				<span className="game__count">
					{position} of {total} covered
				</span>
			</div>
		</div>
	);
}

function CompletePanel({
	copy,
	covered,
	closing,
	onExit,
}: {
	copy: Copy;
	covered: Array<Settled>;
	closing: Closing | null;
	onExit: () => void;
}) {
	return (
		<>
			<p className="game__result" data-outcome="correct">
				<span className="game__stars" aria-hidden="true">
					{covered.map((entry, i) => (
						<SparkIcon
							key={entry.statement}
							size={16}
							style={{ animationDelay: `${i * 250}ms` }}
						/>
					))}
				</span>
				{copy.completeLead}
			</p>

			<div className="tf__topics">
				{covered.map((entry, i) => (
					<div key={entry.statement} className="tf__bullet">
						<span className="game__chip">{i + 1}</span>
						<span className="tf__bullet-text">
							<b>{entry.reveal.topic ?? entry.reveal.answer}</b>
							{entry.reveal.topic_line ?? ""}
						</span>
					</div>
				))}
			</div>

			{closing ? (
				<div className="game__meaning">
					<span className="game__meaning-label">
						<SparkIcon size={13} />
						{copy.together}
					</span>
					<span className="game__meaning-word tf__takeaway">
						{closing.lead}
					</span>
					<p className="game__meaning-text">{closing.text}</p>
				</div>
			) : null}

			<div className="game__actions">
				<button
					type="button"
					className="game__btn game__btn--go"
					onClick={onExit}
				>
					{copy.exit}
				</button>
				<span className="game__count">{copy.exitNote}</span>
			</div>
		</>
	);
}
