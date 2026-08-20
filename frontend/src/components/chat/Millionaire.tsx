import { useCallback, useEffect, useState } from "react";
import { CheckIcon, ExitIcon, SparkIcon } from "#/components/icons";
import { playCoin, playMiss } from "#/lib/aspire/game-sound";
import {
	type Closing,
	GameError,
	type GameState,
	type GameSummary,
	quitGame,
	type Reveal,
	submitAnswer,
} from "#/lib/aspire/games";
import { type PiggyMood, PiggyProgress } from "./PiggyProgress";

/** Who Wants to Be a Millionaire, played in the thread. */

const COPY = {
	sub: (total: number) => `${total} ${total === 1 ? "question" : "questions"}`,
	leave: "Leave game",
	close: "Close",
	meaning: "Why",
	next: "Next question",
	last: "See the score",
	completeLead: "That is the round.",
	together: "What ties them together",
	exit: "Back to chat",
	exitNote: "Ask me to go deeper on any of these whenever you want.",
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
const CHEERS = [
	"Yay!",
	"Nice one!",
	"Correct!",
	"Great job!",
	"Got it!",
] as const;

/** A, B, C, D — the labels the player can also type. */
const LETTERS = ["A", "B", "C", "D"] as const;

type Outcome = "correct" | "incorrect";

interface Settled {
	question: string;
	reveal: Reveal;
	outcome: Outcome;
	chose: string;
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

	// The piggy is fed from what has actually been resolved, not from the
	// server's running counters, so it cannot get ahead of what is on screen.
	const answered = covered.length;
	const coins = covered.filter((c) => c.outcome === "correct").length;

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
					cheer: CHEERS[Math.min(covered.length, CHEERS.length - 1)],
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

	const leave = () =>
		guard(async () => {
			if (!complete) await quitGame(threadId).catch(() => undefined);
			onChanged(null);
		});

	const asking = settled === null && !complete;

	return (
		<section className="game game--quiz" aria-live="polite">
			<header className="game__head">
				<div>
					<h3 className="game__title">Who Wants to Be a Millionaire?</h3>
					<p className="game__sub">{COPY.sub(total)}</p>
				</div>
				<button
					type="button"
					className="game__leave"
					onClick={leave}
					disabled={busy}
				>
					<ExitIcon />
					{complete ? COPY.close : COPY.leave}
				</button>
			</header>

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
					<p className="game__verdict" data-outcome={settled.outcome}>
						{settled.outcome === "correct" ? (
							<>
								<span className="game__cheer">{settled.cheer}</span>{" "}
								{COPY.right(settled.reveal.answer)}
							</>
						) : (
							COPY.wrong(settled.reveal.answer)
						)}
					</p>
					<p className="game__meaning-label">{COPY.meaning}</p>
					<p className="game__meaning-text">{settled.reveal.explanation}</p>
					<button
						type="button"
						className="game__btn game__btn--go"
						onClick={() => setSettled(null)}
						disabled={busy}
					>
						{summary ? COPY.last : COPY.next}
					</button>
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
				</>
			)}

			{failure ? <p className="game__failure">{failure}</p> : null}
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
			<p className="game__eyebrow">
				<SparkIcon /> {COPY.completeLead}
			</p>
			<p className="game__count">
				{right} of {summary?.total ?? covered.length} saved.
			</p>
			<ul className="game__recap">
				{covered.map((entry) => (
					<li key={entry.question} data-outcome={entry.outcome}>
						<span className="game__recap-mark" aria-hidden="true">
							{entry.outcome === "correct" ? <CheckIcon /> : null}
						</span>
						<span>
							<strong>{entry.question}</strong>
							<br />
							{entry.reveal.answer}
						</span>
					</li>
				))}
			</ul>
			{closing ? (
				<div className="game__closing">
					<p className="game__closing-lead">{COPY.together}</p>
					<p className="game__closing-head">{closing.lead}</p>
					<p className="game__closing-text">{closing.text}</p>
				</div>
			) : null}
			<button
				type="button"
				className="game__btn game__btn--go"
				onClick={onExit}
			>
				{COPY.exit}
			</button>
			<p className="game__exit-note">{COPY.exitNote}</p>
		</div>
	);
}
