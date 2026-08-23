import { useCallback, useEffect, useState } from "react";
import { CheckIcon, SparkIcon } from "#/components/icons";
import { playCoin, playMiss } from "#/lib/aspire/game-sound";
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
import { GAME_COPY } from "./game-copy";
import { GameHead } from "./GameHead";
import { type PiggyMood, PiggyProgress } from "./PiggyProgress";

/** Who Wants to Be a Millionaire, played in the thread. */

const COPY = {
	/* The card header holds a badge, a name, a count, up to eight step dots and
	   an exit. "Who Wants to Be a Millionaire?" is four words longer than any
	   other game's name and pushed the exit onto a second, mostly empty row.
	   The full name is still what the section announces; see `fullTitle`. */
	title: "Millionaire",
	fullTitle: "Who Wants to Be a Millionaire?",
	sub: (total: number) => `${total} ${total === 1 ? "question" : "questions"}`,
	...GAME_COPY,
	next: "Next question",
	last: "See the score",
	completeLead: "That is the round.",
	right: (answer: string) => `${answer} — that is right.`,
	wrong: (answer: string) => `Not this time. The answer is ${answer}.`,
} as const;

/**
 * What the card says on a right answer.
 *
 * Short, and varied only so the fifth one in a row does not read as a stuck
 * recording. Nothing here is a superlative: "Yay!" for answering a question is
 * the kind of praise children stop believing.
 */
const CHEERS = ["Right.", "That's it.", "Correct.", "Yes.", "Got it."] as const;

/** A, B, C, D — the labels the player can also type. */
const LETTERS = ["A", "B", "C", "D"] as const;

type Outcome = "correct" | "incorrect" | "skipped";

interface Settled {
	question: string;
	reveal: Reveal;
	outcome: Outcome;
	/** Null when the reader asked for the answer rather than choosing one. */
	chose: string | null;
	cheer: string;
}

export function Millionaire({
	threadId,
	state,
	onChanged,
	onSummary,
	soundOn = true,
}: {
	threadId: string;
	state: GameState;
	onChanged: (state: GameState | null) => void;
	onSummary?: (summary: GameSummary) => void;
	/** The reader's own preference, from the voice and sound menu. */
	soundOn?: boolean;
}) {
	const [settled, setSettled] = useState<Settled | null>(null);
	const [covered, setCovered] = useState<Array<Settled>>([]);
	const [summary, setSummary] = useState<GameSummary | null>(null);
	const [busy, setBusy] = useState(false);
	const [failure, setFailure] = useState<string | null>(null);
	const [mood, setMood] = useState<PiggyMood>("idle");
	// Bumped on every answer, so two of the same in a row still animate.
	const [moodAt, setMoodAt] = useState(0);

	const complete = summary !== null && settled === null;
	const choices = state.prompt.choices;
	const total = state.prompt.total || choices.length;

	/**
	 * How many are behind us.
	 *
	 * This was `covered.length` alone, which is a count of what THIS mount has
	 * seen. Reopening a game in progress reset it to zero, so the piggy read
	 * "0 of 8" on question three. `prompt.position` is the server's count and
	 * survives the remount; the local array still wins when it is ahead, which
	 * is the moment between settling an answer and the next prompt arriving.
	 */
	const answered = Math.max(state.prompt.position - 1, covered.length);
	/* Seeded from the server for the same reason `answered` is: reopening a
	   game in progress emptied the bank. */
	const coins = Math.max(
		state.solved,
		covered.filter((c) => c.outcome === "correct").length,
	);

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

	const choose = useCallback(
		(value: string) =>
			guard(async () => {
				const question = state.prompt.text;
				const result = await submitAnswer(threadId, value);
				if (result.unreadable) {
					setFailure(result.unreadable);
					return;
				}
				if (!result.reveal) {
					setFailure("That did not settle the question. Try again.");
					return;
				}

				const right = Boolean(result.correct);
				// Inside the click that caused it: this is the user gesture browser
				// autoplay policy wants, and it is why nothing is ever played on mount.
				if (right) playCoin(soundOn);
				else playMiss(soundOn);
				setMood(right ? "fed" : "dropped");
				setMoodAt((n) => n + 1);

				const entry: Settled = {
					question,
					reveal: result.reveal,
					outcome: right ? "correct" : "incorrect",
					chose: value,
					cheer: CHEERS[covered.length % CHEERS.length],
				};
				setCovered((current) => [...current, entry]);
				setSettled(entry);
				setSummary(result.summary);
				if (result.summary) onSummary?.(result.summary);
				if (result.game) onChanged(result.game);
			}),
		[
			covered.length,
			guard,
			onChanged,
			onSummary,
			soundOn,
			state.prompt.text,
			threadId,
		],
	);

	/** The way past a question nobody can answer. See `TrueFalse.skip`. */
	const giveUp = () =>
		guard(async () => {
			const question = state.prompt.text;
			const result = await skipWord(threadId);
			const entry: Settled = {
				question,
				reveal: result.reveal,
				outcome: "skipped",
				chose: null,
				cheer: "",
			};
			setCovered((current) => [...current, entry]);
			setSettled(entry);
			setSummary(result.summary);
			if (result.summary) onSummary?.(result.summary);
			if (result.game) onChanged(result.game);
		});

	const leave = () =>
		guard(async () => {
			if (!complete) await quitGame(threadId).catch(() => undefined);
			onChanged(null);
		});

	const asking = settled === null && !complete;

	return (
		<section
			className="game game--quiz"
			aria-live="polite"
			aria-label={`${COPY.fullTitle}, question ${state.prompt.position} of ${total}`}
		>
			<GameHead
				title={COPY.title}
				sub={COPY.sub(total)}
				position={state.prompt.position}
				total={total}
				complete={complete}
				leaveLabel={complete ? COPY.close : COPY.leave}
				onLeave={leave}
				busy={busy}
			/>

			{/* THE BODY WRAPPER WAS MISSING, and `.game` sets `overflow: hidden`.
			 * So every one of these rows ran flush to the card's edge and the
			 * answer grid was visibly clipped on the right — see the same wrapper
			 * in `WordScramble` and `TrueFalse`, which have always had it. */}
			<div className="game__body">
				{failure ? (
					<p className="game__failure" role="alert">
						{failure}
					</p>
				) : null}

				<PiggyProgress
					answered={answered}
					total={total}
					coins={coins}
					mood={mood}
					moodAt={moodAt}
				/>

				{complete ? (
					<Complete
						covered={covered}
						summary={summary}
						closing={summary?.closing ?? null}
						onExit={leave}
					/>
				) : settled ? (
					<div className="game__resolved">
						{/* `.game__result`, not `.game__verdict`: the icon chip is what
						 * the other two games use, and a right answer that looks
						 * different depending on which game you are in is two products. */}
						<p className="game__result" data-outcome={settled.outcome}>
							<span className="game__result-icon" aria-hidden="true">
								{settled.outcome === "correct" ? <CheckIcon /> : null}
							</span>
							{settled.outcome === "correct"
								? `${settled.cheer} ${COPY.right(settled.reveal.answer)}`
								: COPY.wrong(settled.reveal.answer)}
						</p>
						<div className="game__meaning">
							<span className="game__meaning-label">{COPY.meaning}</span>
							<p className="game__meaning-text">
								{settled.reveal.explanation}
							</p>
						</div>
						<div className="game__actions">
							<button
								type="button"
								className="game__btn game__btn--go"
								onClick={() => setSettled(null)}
								disabled={busy}
							>
								{summary ? COPY.last : COPY.next}
							</button>
						</div>
					</div>
				) : (
					<>
						<p className="game__question">{state.prompt.text}</p>
						<div className="quiz__choices">
							{choices.map((choice, index) => (
								<button
									key={choice}
									type="button"
									className="quiz__choice"
									onClick={() => choose(choice)}
									disabled={busy || !asking}
								>
									<span className="quiz__letter" aria-hidden="true">
										{LETTERS[index] ?? String(index + 1)}
									</span>
									<span className="quiz__text">{choice}</span>
								</button>
							))}
						</div>
						{/* This was the only game with no way past a question a child
						 * cannot answer. Every other one has had one from the start. */}
						<div className="game__actions">
							<button
								type="button"
								className="game__btn game__btn--quiet"
								onClick={giveUp}
								disabled={busy || !asking}
							>
								{COPY.skip}
							</button>
						</div>
					</>
				)}
			</div>
		</section>
	);
}

function Complete({
	covered,
	summary,
	closing,
	onExit,
}: {
	covered: Array<Settled>;
	summary: GameSummary | null;
	closing: Closing | null;
	onExit: () => void;
}) {
	const right = covered.filter((c) => c.outcome === "correct").length;
	return (
		<div className="game__complete">
			{/* `.game__result` with the star row, as word scramble closes. This was
			 * `.game__eyebrow` — an uppercase tracked kicker — over the score set
			 * in `.game__count`, a 13px muted caption class. The number a child
			 * played eight questions for was the smallest text on the card. */}
			<p className="game__result" data-correct>
				<span className="game__stars" aria-hidden="true">
					{[0, 1, 2, 3].map((i) => (
						<SparkIcon
							key={i}
							size={16}
							style={{ animationDelay: `${i * 300}ms` }}
						/>
					))}
				</span>
				{COPY.completeLead}
			</p>
			<p className="game__score">
				{right} of {summary?.total ?? covered.length} right
			</p>
			<ul className="game__recap">
				{covered.map((entry) => (
					<li key={entry.question} data-outcome={entry.outcome}>
						<span className="game__recap-mark">
							{entry.outcome === "correct" ? <CheckIcon /> : null}
							{/* The tick was the only sign of how a question went, and it
							    was hidden from screen readers — which left the recap
							    reading as a plain list with no outcome in it at all. */}
							<span className="sr-only">
								{entry.outcome === "correct" ? "Right." : "Not right."}
							</span>
						</span>
						<span>
							<strong>{entry.question}</strong>
							<br />
							{entry.reveal.answer}
						</span>
					</li>
				))}
			</ul>
			{/* `.game__meaning`, the bordered teaching block the other two games
			 * close with — not `.game__closing`, a flat grey box that existed only
			 * here and in Hangman. */}
			{closing ? (
				<div className="game__meaning">
					<span className="game__meaning-label">
						<SparkIcon size={13} />
						{closing.lead || COPY.together}
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
					{COPY.exit}
				</button>
				<span className="game__count">{COPY.exitNote}</span>
			</div>
		</div>
	);
}
