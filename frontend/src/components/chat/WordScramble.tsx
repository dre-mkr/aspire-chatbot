import { useCallback, useEffect, useRef, useState } from "react";
import {
	CheckIcon,
	ExitIcon,
	RetryIcon,
	ShuffleIcon,
	SparkIcon,
} from "#/components/icons";
import {
	GameError,
	type GameState,
	type GameSummary,
	quitGame,
	requestHint,
	skipWord,
	submitAnswer,
} from "#/lib/aspire/games";

/** The word scramble, played in the thread. */

/* Counts come from the set, never from the copy. */
const COPY = {
	title: "Word scramble",
	sub: (total: number) =>
		`Warm-up set · ${total} ${total === 1 ? "word" : "words"}`,
	leave: "Leave game",
	close: "Close",
	lead: "Unscramble these letters.",
	help: "Click a letter to place it, or drag it into a slot.",
	clue: "Clue",
	noClues: "No clues left",
	shuffle: "Shuffle",
	skip: "Skip this word",
	check: "Check it",
	wrong: "Same letters, different order — take one out and try another spot.",
	meaning: "What it means in ASPIRE terms",
	next: "Next word",
	last: (total: number) => `See all ${total}`,
	revealed: (word: string) => `No trouble — the word was ${word}.`,
	completeLead: (total: number) => `That is the set — all ${total}.`,
	together: "What they mean together",
	exit: "Back to chat",
	exitNote: "Ask me about any of these words whenever you want.",
} as const;

type Copy = typeof COPY;

/** Tiles sit at slight angles so the tray reads as loose letters, not a keyboard. */
const ROTATIONS = [
	"-1.6deg",
	"1.4deg",
	"-0.8deg",
	"1.8deg",
	"-1.2deg",
	"0.9deg",
	"-1.7deg",
	"1.1deg",
];

interface Placed {
	ch: string;
	/** Index in the tray this letter came from, so it can go home. */
	from: number;
}

interface Learned {
	word: string;
	definition: string;
	correct: boolean;
}

interface WordScrambleProps {
	threadId: string;
	/** Current server state. The parent owns fetching it. */
	state: GameState;
	/** Fires whenever the server state moves on; null once the game is over. */
	onChanged: (state: GameState | null) => void;
	/** Fires once, with the final numbers, the moment the set resolves. */
	onSummary?: (summary: GameSummary) => void;
}

export function WordScramble({
	threadId,
	state,
	onChanged,
	onSummary,
}: WordScrambleProps) {
	const copy = COPY;

	const [tray, setTray] = useState<Array<string>>([]);
	const [used, setUsed] = useState<Array<boolean>>([]);
	const [slots, setSlots] = useState<Array<Placed | null>>([]);
	const [wrong, setWrong] = useState<string | null>(null);
	const [shake, setShake] = useState(0);
	const [resolved, setResolved] = useState<Learned | null>(null);
	const [learned, setLearned] = useState<Array<Learned>>([]);
	const [summary, setSummary] = useState<GameSummary | null>(null);
	const [busy, setBusy] = useState(false);
	const [failure, setFailure] = useState<string | null>(null);
	const dragFrom = useRef<number | null>(null);

	// Rebuild the tray whenever the server moves to a different word.
	const wordKey = `${state.prompt.position}:${state.prompt.text}`;
	// biome-ignore lint/correctness/useExhaustiveDependencies: keyed reset
	useEffect(() => {
		const letters = state.prompt.text.split("");
		setTray(letters);
		setUsed(letters.map(() => false));
		setSlots(letters.map(() => null));
		setWrong(null);
	}, [wordKey]);

	const filled = slots.filter(Boolean).length;
	const complete = summary !== null && resolved === null;
	const canCheck = filled === slots.length && filled > 0 && !busy;

	const place = useCallback(
		(index: number) => {
			if (used[index] || resolved) return;
			const target = slots.indexOf(null);
			if (target < 0) return;
			setUsed((current) => current.map((u, i) => (i === index ? true : u)));
			setSlots((current) =>
				current.map((s, i) =>
					i === target ? { ch: tray[index], from: index } : s,
				),
			);
			setWrong(null);
		},
		[resolved, slots, tray, used],
	);

	const unplace = useCallback(
		(index: number) => {
			const placed = slots[index];
			if (!placed || resolved) return;
			setUsed((current) =>
				current.map((u, i) => (i === placed.from ? false : u)),
			);
			setSlots((current) => current.map((s, i) => (i === index ? null : s)));
			setWrong(null);
		},
		[resolved, slots],
	);

	const shuffle = useCallback(() => {
		const order = tray.map((_, i) => i);
		for (let i = order.length - 1; i > 0; i--) {
			const j = Math.floor(Math.random() * (i + 1));
			[order[i], order[j]] = [order[j], order[i]];
		}
		const remap = new Map(order.map((old, next) => [old, next]));
		setTray(order.map((i) => tray[i]));
		setUsed(order.map((i) => used[i]));
		// Slots keep their letters; only the tray index each came from moves.
		setSlots((current) =>
			current.map((s) =>
				s ? { ch: s.ch, from: remap.get(s.from) ?? s.from } : null,
			),
		);
	}, [tray, used]);

	/** Records a finished word and, if the set is done, the closing summary. */
	const settle = useCallback(
		(entry: Learned, next: GameState | null, done: GameSummary | null) => {
			setLearned((current) => [...current, entry]);
			setResolved(entry);
			setSummary(done);
			// The final numbers go up the moment they exist -- the launcher needs them to report the real score, and `onCha…
			if (done) onSummary?.(done);
			if (next) onChanged(next);
		},
		[onChanged, onSummary],
	);

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

	const check = () =>
		guard(async () => {
			const attempt = slots.map((s) => s?.ch ?? "").join("");
			const result = await submitAnswer(threadId, attempt);
			if (result.unreadable) {
				setFailure(result.unreadable);
				return;
			}
			if (!result.correct) {
				setWrong(attempt);
				setShake((n) => n + 1);
				return;
			}
			settle(
				{
					word: attempt,
					definition: result.teaching_note ?? "",
					correct: true,
				},
				result.game,
				result.summary,
			);
		});

	const clue = () =>
		guard(async () => {
			const result = await requestHint(threadId);
			if (result.reveal) {
				settle(
					{
						word: result.reveal.answer,
						definition: result.reveal.explanation,
						correct: false,
					},
					result.game,
					result.summary,
				);
				return;
			}
			if (result.game) onChanged(result.game);
		});

	const skip = () =>
		guard(async () => {
			const result = await skipWord(threadId);
			settle(
				{
					word: result.reveal.answer,
					definition: result.reveal.explanation,
					correct: false,
				},
				result.game,
				result.summary,
			);
		});

	const leave = () =>
		guard(async () => {
			// A game already finished has no session left to quit.
			if (!complete && state) {
				await quitGame(threadId).catch(() => undefined);
			}
			onChanged(null);
		});

	const advance = () => {
		setResolved(null);
		if (summary) return; // the complete panel takes over
		setWrong(null);
	};

	const outOfClues = state.hint_level >= state.max_hint_level;

	return (
		<section
			className="game"
			aria-label={`${copy.title}, word ${state.prompt.position} of ${state.prompt.total}`}
		>
			<header className="game__head">
				<span className="game__badge" aria-hidden="true">
					<SparkIcon />
				</span>
				<span className="game__title">{copy.title}</span>
				<span className="game__sub">{copy.sub(state.prompt.total)}</span>

				{/* Decorative: the section's own label already announces which word this is, and four unlabelled dots read as no… */}
				<div className="game__steps" aria-hidden="true">
					{Array.from({ length: state.prompt.total }, (_, i) => {
						const n = i + 1;
						const done = n < state.prompt.position;
						const now = n === state.prompt.position && !complete;
						return (
							<span
								key={n}
								className="game__step"
								data-state={done ? "done" : now ? "now" : "next"}
								title={`Word ${n}`}
							>
								{done ? <CheckIcon /> : now ? n : null}
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
				{failure ? (
					<p className="game__failure" role="alert">
						{failure}
					</p>
				) : null}

				{complete ? (
					<CompletePanel
						copy={copy}
						learned={learned}
						summary={summary}
						total={state.prompt.total}
						onExit={leave}
					/>
				) : resolved ? (
					<ResolvedPanel
						copy={copy}
						resolved={resolved}
						isLast={summary !== null}
						solved={learned.filter((l) => l.correct).length}
						total={state.prompt.total}
						onNext={advance}
					/>
				) : (
					<>
						<p className="game__lead">{copy.lead}</p>

						<div className="game__tray">
							{tray.map((ch, i) => (
								<button
									// biome-ignore lint/suspicious/noArrayIndexKey: tray position is the identity
									key={i}
									type="button"
									className="tile tile--tray"
									data-spent={used[i] || undefined}
									style={
										{
											"--rot": ROTATIONS[i % ROTATIONS.length],
										} as React.CSSProperties
									}
									draggable={!used[i]}
									onDragStart={() => {
										dragFrom.current = i;
									}}
									onClick={() => place(i)}
									disabled={used[i] || busy}
									aria-label={used[i] ? "Letter used" : `Place letter ${ch}`}
								>
									{used[i] ? "" : ch}
								</button>
							))}
						</div>

						<div
							className="game__slots"
							data-shake={wrong ? shake : undefined}
							key={`slots-${shake}-${wrong ? "w" : "ok"}`}
						>
							{slots.map((s, j) => (
								<button
									// biome-ignore lint/suspicious/noArrayIndexKey: positional
									key={j}
									type="button"
									className="tile tile--slot"
									data-filled={s ? true : undefined}
									data-wrong={wrong ? true : undefined}
									onClick={() => unplace(j)}
									onDragOver={(event) => event.preventDefault()}
									onDrop={(event) => {
										event.preventDefault();
										if (dragFrom.current !== null) {
											place(dragFrom.current);
											dragFrom.current = null;
										}
									}}
									disabled={busy}
									aria-label={
										s
											? `Remove letter ${s.ch} from position ${j + 1}`
											: `Empty slot ${j + 1}`
									}
								>
									{s?.ch ?? ""}
								</button>
							))}
						</div>

						{/* <output> rather than a div with role=status: this announces the result of the check the child just ran. */}
						{wrong ? (
							<output className="game__wrong">
								<RetryIcon />
								<span>{copy.wrong}</span>
							</output>
						) : null}

						{state.hints.length > 0 ? (
							<div className="game__clues">
								{state.hints.map((text, i) => (
									<p key={text} className="game__clue">
										<span className="game__clue-label">
											Clue {i + 1} of {state.max_hint_level}
										</span>
										<span>{text}</span>
									</p>
								))}
							</div>
						) : null}

						<p className="game__help">{copy.help}</p>

						<div className="game__actions">
							<button
								type="button"
								className="game__btn game__btn--clue"
								onClick={clue}
								disabled={outOfClues || busy}
							>
								<SparkIcon />
								{outOfClues
									? copy.noClues
									: `${copy.clue} · ${state.hint_level + 1} of ${state.max_hint_level}`}
							</button>
							<button
								type="button"
								className="game__btn game__btn--quiet"
								onClick={shuffle}
								disabled={busy}
							>
								<ShuffleIcon />
								{copy.shuffle}
							</button>
							<button
								type="button"
								className="game__btn game__btn--ghost"
								onClick={skip}
								disabled={busy}
							>
								{copy.skip}
							</button>
							<button
								type="button"
								className="game__btn game__btn--go"
								onClick={check}
								disabled={!canCheck}
							>
								<CheckIcon />
								{copy.check}
							</button>
						</div>
					</>
				)}
			</div>
		</section>
	);
}

function ResolvedPanel({
	copy,
	resolved,
	isLast,
	solved,
	total,
	onNext,
}: {
	copy: Copy;
	resolved: Learned;
	isLast: boolean;
	solved: number;
	total: number;
	onNext: () => void;
}) {
	return (
		<>
			<p className="game__result" data-correct={resolved.correct || undefined}>
				<span className="game__result-icon" aria-hidden="true">
					<CheckIcon />
				</span>
				{resolved.correct
					? `You got ${resolved.word}.`
					: copy.revealed(resolved.word)}
			</p>

			<div className="game__answer">
				{resolved.word.split("").map((ch, i) => (
					<span
						// biome-ignore lint/suspicious/noArrayIndexKey: positional
						key={i}
						className="tile tile--answer"
						data-earned={resolved.correct || undefined}
					>
						{ch}
					</span>
				))}
			</div>

			<div className="game__meaning">
				<span className="game__meaning-label">
					<SparkIcon size={13} />
					{copy.meaning}
				</span>
				<span className="game__meaning-word">{resolved.word}</span>
				<p className="game__meaning-text">{resolved.definition}</p>
			</div>

			<div className="game__actions">
				<button
					type="button"
					className="game__btn game__btn--go"
					onClick={onNext}
				>
					{isLast ? copy.last(total) : copy.next}
				</button>
				<span className="game__count">
					{solved} of {total} solved
				</span>
			</div>
		</>
	);
}

function CompletePanel({
	copy,
	learned,
	summary,
	total,
	onExit,
}: {
	copy: Copy;
	learned: Array<Learned>;
	summary: GameSummary | null;
	/** From the set, not from `learned`: a skipped word is still part of it. */
	total: number;
	onExit: () => void;
}) {
	return (
		<>
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
				{copy.completeLead(total)}
			</p>

			<div className="game__pills">
				{learned.map((l) => (
					<span key={l.word} className="game__pill">
						{l.word}
					</span>
				))}
			</div>

			<div className="game__meaning">
				<span className="game__meaning-label">
					<SparkIcon size={13} />
					{copy.together}
				</span>
				<p className="game__meaning-text">
					You <strong>SAVE</strong> money, you <strong>INVEST</strong> what you
					saved, and it earns <strong>INTEREST</strong> while it sits. That is
					how <strong>MONEY</strong> grows while you wait — and why the order
					matters.
				</p>
			</div>

			<div className="game__actions">
				<button
					type="button"
					className="game__btn game__btn--go"
					onClick={onExit}
				>
					{copy.exit}
				</button>
				<span className="game__count">
					{summary
						? `${summary.solved} of ${summary.total} solved · ${summary.hints_used} clue${summary.hints_used === 1 ? "" : "s"}`
						: copy.exitNote}
				</span>
			</div>
		</>
	);
}
