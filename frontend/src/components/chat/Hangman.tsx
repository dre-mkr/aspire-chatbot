import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckIcon, LampIcon, SparkIcon } from "#/components/icons";
import { playCoin, playMiss } from "#/lib/aspire/game-sound";
import {
	type Closing,
	GameError,
	type GameState,
	type GameSummary,
	quitGame,
	type Reveal,
	requestHint,
	skipWord,
	submitAnswer,
} from "#/lib/aspire/games";
import { GameHead } from "./GameHead";
import { GAME_COPY } from "./game-copy";

/** Hangman, played in the thread. */

/**
 * How many wrong letters a player gets.
 *
 * Six, which is the traditional number, and enough that a child who guesses
 * every vowel first still has four goes at the consonants.
 */
const LIVES = 6;

const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");

const COPY = {
	title: "Hangman",
	sub: (total: number) => `${total} ${total === 1 ? "word" : "words"}`,
	...GAME_COPY,
	/* Word scramble says "Clue · 1 of 2" and this said "Give me a clue"; the
	   count is the useful half, so both say the same thing now. */
	hint: "Clue",
	next: "Next word",
	completeLead: "That is all of them.",
	got: (word: string) => `${word} — you got it.`,
	lost: (word: string) => `Out of guesses. The word was ${word}.`,
	shown: (word: string) => `The word was ${word}.`,
} as const;

type Outcome = "correct" | "incorrect" | "skipped";

interface Settled {
	reveal: Reveal;
	outcome: Outcome;
}

export function Hangman({
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
	soundOn?: boolean;
}) {
	const [settled, setSettled] = useState<Settled | null>(null);
	const [covered, setCovered] = useState<Array<Settled>>([]);
	const [summary, setSummary] = useState<GameSummary | null>(null);
	const [busy, setBusy] = useState(false);
	const [failure, setFailure] = useState<string | null>(null);

	/**
	 * The board, and the letters tried on THIS word.
	 *
	 * Held here rather than on the server because the server's item loop is
	 * per-word, not per-letter: the engine is told a letter, says whether it is
	 * in the word, and the board is the client's to draw. The word itself never
	 * arrives until the item resolves, so there is nothing here to read the
	 * answer out of.
	 */
	const [board, setBoard] = useState(state.prompt.text);
	const [tried, setTried] = useState<Array<string>>([]);

	const complete = summary !== null && settled === null;

	const wrong = useMemo(
		() => tried.filter((letter) => !board.includes(letter)).length,
		[tried, board],
	);
	const livesLeft = Math.max(0, LIVES - wrong);

	// A new word is a new board. Keyed on the position so the same word twice
	// in a set still resets.
	const itemKey = `${state.prompt.position}:${state.prompt.text}`;
	// biome-ignore lint/correctness/useExhaustiveDependencies: keyed reset
	useEffect(() => {
		setBoard(state.prompt.text);
		setTried([]);
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
			if (done) onSummary?.(done);
			if (next) onChanged(next);
		},
		[onChanged, onSummary],
	);

	const guessLetter = useCallback(
		(letter: string) =>
			guard(async () => {
				if (tried.includes(letter)) return;
				setTried((current) => [...current, letter]);

				const result = await submitAnswer(threadId, letter);
				if (result.unreadable) {
					setFailure(result.unreadable);
					return;
				}

				// The item resolved — the whole word came back.
				if (result.reveal) {
					const right = Boolean(result.correct);
					if (right) playCoin(soundOn);
					else playMiss(soundOn);
					setBoard(result.reveal.answer);
					settle(
						{ reveal: result.reveal, outcome: right ? "correct" : "incorrect" },
						result.game,
						result.summary,
					);
					return;
				}

				// Still going: the server said whether the letter is in the word.
				if (result.correct) {
					playCoin(soundOn);
					// Reveal every position of that letter, from the server's own board
					// if it sent one, otherwise from what is already known.
					setBoard(result.game?.prompt.text ?? board);
				} else {
					playMiss(soundOn);
				}
			}),
		[board, guard, settle, soundOn, threadId, tried],
	);

	const hint = () =>
		guard(async () => {
			const result = await requestHint(threadId);
			if (result.game) onChanged(result.game);
		});

	const reveal = () =>
		guard(async () => {
			const result = await skipWord(threadId);
			setBoard(result.reveal.answer);
			settle(
				{ reveal: result.reveal, outcome: "skipped" },
				result.game,
				result.summary,
			);
		});

	const leave = () =>
		guard(async () => {
			if (!complete) await quitGame(threadId).catch(() => undefined);
			onChanged(null);
		});

	const asking = settled === null && !complete;

	return (
		<section
			className="game game--hangman"
			aria-live="polite"
			aria-label={`${COPY.title}, word ${state.prompt.position} of ${state.prompt.total}`}
		>
			<GameHead
				title={COPY.title}
				sub={COPY.sub(state.prompt.total)}
				position={state.prompt.position}
				total={state.prompt.total}
				complete={complete}
				leaveLabel={complete ? COPY.close : COPY.leave}
				onLeave={leave}
				busy={busy}
			/>

			{/* `.game` sets `overflow: hidden` and this content had no `.game__body`
			 * to sit in, so the 26-key alphabet ran under the card's right edge and
			 * the last key of each row was clipped. */}
			<div className="game__body">
				{failure ? (
					<p className="game__failure" role="alert">
						{failure}
					</p>
				) : null}

				{complete ? (
					<Complete
						covered={covered}
						summary={summary}
						closing={summary?.closing ?? null}
						onExit={leave}
					/>
				) : settled ? (
					<div className="game__resolved">
						<p className="game__word">
							<span aria-hidden="true">
								{settled.reveal.answer.split("").join(" ")}
							</span>
							{/* The spaced letters are for the eye. A screen reader gets the
						    word, because "S A V E" is read out as four letters. */}
							<span className="sr-only">{settled.reveal.answer}</span>
						</p>
						<p className="game__result" data-outcome={settled.outcome}>
							<span className="game__result-icon" aria-hidden="true">
								{settled.outcome === "correct" ? <CheckIcon /> : null}
							</span>
							{settled.outcome === "correct"
								? COPY.got(settled.reveal.answer)
								: settled.outcome === "skipped"
									? COPY.shown(settled.reveal.answer)
									: COPY.lost(settled.reveal.answer)}
						</p>
						<div className="game__meaning">
							<span className="game__meaning-label">
								<SparkIcon size={13} />
								{COPY.meaning}
							</span>
							<p className="game__meaning-text">{settled.reveal.explanation}</p>
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
						{/*
					  The board is read as a word, not as a row of letters. Without the
					  label a screen reader says "H underscore N G underscore A N",
					  which is not what is on the screen and not a word.
					*/}
						<p className="game__word">
							<span aria-hidden="true">{board}</span>
							<span className="sr-only">
								{`The word so far: ${board.replace(/_/g, "blank")}`}
							</span>
						</p>

						<Lives left={livesLeft} of={LIVES} />

						{state.hints.length ? (
							<ul className="game__hints">
								{state.hints.map((line) => (
									<li key={line}>
										<LampIcon /> {line}
									</li>
								))}
							</ul>
						) : null}

						<div className="hangman__keys">
							{ALPHABET.map((letter) => {
								const used = tried.includes(letter);
								const hit = used && board.includes(letter);
								return (
									<button
										key={letter}
										type="button"
										className="hangman__key"
										data-used={used || undefined}
										data-hit={hit || undefined}
										onClick={() => guessLetter(letter)}
										disabled={busy || used || !asking}
										// A tried letter says which way it went in colour alone,
										// which is nothing to a screen reader and nothing to a
										// reader who cannot tell the two washes apart. The name
										// says it in words.
										aria-label={
											hit
												? `${letter}, in the word`
												: used
													? `${letter}, not in the word`
													: letter
										}
									>
										{letter}
									</button>
								);
							})}
						</div>

						<div className="game__actions">
							{state.supports_hints &&
							state.hint_level < state.max_hint_level ? (
								<button
									type="button"
									className="game__btn game__btn--ghost"
									onClick={hint}
									disabled={busy}
								>
									<LampIcon /> {COPY.hint}
								</button>
							) : null}
							<button
								type="button"
								className="game__btn game__btn--ghost"
								onClick={reveal}
								disabled={busy}
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

/** Lives as pips rather than a gallows. */
function Lives({ left, of }: { left: number; of: number }) {
	return (
		<p className="hangman__lives">
			<span aria-hidden="true">
				{Array.from({ length: of }, (_, i) => (
					<span
						// biome-ignore lint/suspicious/noArrayIndexKey: pips are positional; the index IS the identity
						key={`life-${of}-${i}`}
						className="hangman__life"
						data-spent={i >= left || undefined}
					/>
				))}
			</span>
			{/* Six dots under a word mean nothing on their own. A screen reader was
			    told what they were and a child looking at them was not. */}
			<span className="hangman__lives-label" aria-hidden="true">
				{left} {left === 1 ? "guess" : "guesses"} left
			</span>
			<span className="sr-only">{`${left} of ${of} guesses left.`}</span>
		</p>
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
	const got = covered.filter((c) => c.outcome === "correct").length;
	return (
		<div className="game__complete">
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
				{got} of {summary?.total ?? covered.length} without help
			</p>
			<ul className="game__recap">
				{covered.map((entry) => (
					<li key={entry.reveal.answer} data-outcome={entry.outcome}>
						<span>
							<strong>{entry.reveal.answer}</strong>
							<br />
							{entry.reveal.explanation}
						</span>
					</li>
				))}
			</ul>
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
