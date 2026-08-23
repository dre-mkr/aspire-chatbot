import { CheckIcon, ExitIcon, SparkIcon } from "#/components/icons";

/**
 * The header the four games share, because until now they had two.
 *
 * Word scramble and true-or-false wore a badged single line — spark chip, name,
 * count, step dots, leave — while Millionaire and Hangman wore an unbadged
 * two-line block with no dots and no progress at all. Two of the four also
 * marked the name up as a `<span>` and the other two as an `<h3>`, so a screen
 * reader's heading outline changed depending on which game was running.
 *
 * One header, one element, one set of dots, driven from `prompt.position` —
 * which is the server's count and therefore the only one that survives a
 * remount. Millionaire was deriving its progress from a client-side array and
 * showing "0 of 8" on question three.
 */
export function GameHead({
	title,
	sub,
	position,
	total,
	complete,
	currentSettled = false,
	leaveLabel,
	onLeave,
	busy,
}: {
	title: string;
	/** The count line: "5 words to unscramble", "8 questions". */
	sub: string;
	/** 1-based, from `state.prompt.position`. */
	position: number;
	total: number;
	complete: boolean;
	/**
	 * The item at `position` has already been answered.
	 *
	 * True or false resolves in place — the statement stays on screen with its
	 * explanation under it — so its current dot has to read as done while the
	 * position is still the same. The other three move on, and pass nothing.
	 */
	currentSettled?: boolean;
	leaveLabel: string;
	onLeave: () => void;
	busy: boolean;
}) {
	return (
		<header className="game__head">
			<span className="game__badge" aria-hidden="true">
				<SparkIcon />
			</span>
			<h3 className="game__title">{title}</h3>
			<span className="game__sub">{sub}</span>

			{/* Decorative: the section label already names the position, so bare
			    dots would be noise read twice. */}
			<div className="game__steps" aria-hidden="true">
				{Array.from({ length: total }, (_, i) => {
					const n = i + 1;
					const done = n < position || (n === position && currentSettled);
					const now = n === position && !done && !complete;
					return (
						<span
							key={n}
							className="game__step"
							data-state={done ? "done" : now ? "now" : "next"}
							title={`${n} of ${total}`}
						>
							{done ? <CheckIcon /> : now ? n : null}
						</span>
					);
				})}
			</div>

			<button
				type="button"
				className="game__leave"
				onClick={onLeave}
				disabled={busy}
			>
				<ExitIcon />
				{leaveLabel}
			</button>
		</header>
	);
}
