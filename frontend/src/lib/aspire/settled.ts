/**
 * Which of a growing reply is safe to put on screen.
 *
 * The typewriter reveals text a few words at a time. When the text was already
 * complete that was trivially safe. Now it arrives in pieces, and the naive
 * approach — re-parse the whole buffer every tick and index into the result —
 * is a bug with a very specific symptom: a line that was a paragraph becomes a
 * list item the moment a space lands after its hyphen, and everything already
 * on screen shifts. `stream-corpus.mjs` reproduces that in eight places.
 *
 * So the buffer is split in two.
 *
 *   **Settled** — text that can no longer be re-read. Append-only, stable
 *   indices, and the only thing the typewriter is allowed to touch.
 *
 *   **Provisional tail** — the last, unterminated line. It may still change
 *   what it is, so it is never revealed with block semantics.
 *
 * ## Why the boundary is a newline
 *
 * `parseAnswer` classifies each line by that line's own content and nothing
 * else: `BULLET.test(line)` decides list-versus-prose, a blank line closes
 * whatever is open, and no rule consults the line before or after. So the
 * instant a line's terminating newline arrives, what that line *is* has been
 * decided forever. Blocks can still grow — a following prose line joins the
 * paragraph above it — but growth is appending, and appending never moves what
 * has already been read.
 *
 * That is what buys a one-LINE lag instead of a one-block lag. A block-level
 * lag would hold an entire paragraph back, which on long prose is the sluggish
 * feeling this whole change exists to remove.
 *
 * The property is not assumed. `assertLineLocal` states it as an executable
 * claim, and the corpus checks it against the real parser under chunking
 * designed to break it. If the renderer ever gains a construct that reads its
 * neighbours — a real table, a fenced code block, a setext heading — that guard
 * fails and this file has to become more conservative before anything ships.
 */
import { type AnswerBlock, parseAnswer } from "./knowledge";

/**
 * The blocks that may be revealed, given everything received so far.
 *
 * `ended` collapses the distinction: once the service has said the turn is
 * over, the trailing line is never going to change and the whole buffer
 * settles at once.
 */
export function settledBlocks(buffer: string, ended: boolean): Array<AnswerBlock> {
	if (ended) return parseAnswer(buffer);

	const lastBreak = buffer.lastIndexOf("\n");
	// Nothing has been terminated yet, so nothing is safe. The reader sees the
	// thinking indicator for exactly as long as this is true, which on a real
	// reply is one line.
	if (lastBreak === -1) return [];

	return parseAnswer(buffer.slice(0, lastBreak + 1));
}

/**
 * Whether a block may be advanced past, or might still grow.
 *
 * Only the last settled block can gain more: another line joining a paragraph,
 * another item joining a list. Anything with a block after it is closed, and
 * once the turn has ended so is the last one.
 *
 * Getting this wrong in the permissive direction is what would strand a
 * paragraph half-revealed — the typewriter would step past it and never come
 * back for the words that arrived afterwards.
 */
export function blockIsClosed(
	index: number,
	blocks: Array<AnswerBlock>,
	ended: boolean,
): boolean {
	return ended || index < blocks.length - 1;
}

/**
 * The claim this module rests on, as something that can fail.
 *
 * Classification must depend on the line alone. If it does, a terminated line
 * is immutable and the settled region can never be rewritten.
 *
 * Checked by running the parser over each line in isolation and over the same
 * line surrounded by every kind of neighbour it could have. A construct whose
 * meaning changes with its context shows up here as a mismatch.
 *
 * Exported rather than inlined into a test so it travels with the rule it
 * protects: whoever extends the renderer meets it in the same file that
 * explains why it matters.
 */
export function assertLineLocal(lines: Array<string>): string | null {
	const neighbours = ["", "text", "- item", "1. item", "> quote", "```", "|a|b|", "---", "==="];

	for (const line of lines) {
		if (!line.trim()) continue;
		const alone = parseAnswer(`${line}\n`);
		const aloneKind = alone[0]?.kind ?? "none";

		for (const before of neighbours) {
			for (const after of neighbours) {
				const blocks = parseAnswer(`${before}\n${line}\n${after}\n`);
				// Find how `line` was classified with company: it is whichever
				// block carries its text.
				const needle = line.trim().replace(/^\s*(?:[-*•]|\d+[.)])\s+/, "").trim();
				const found = blocks.find((block) =>
					block.kind === "paragraph"
						? block.text.includes(needle)
						: block.items.some((item) => item.includes(needle)),
				);
				const kindWithNeighbours = found?.kind ?? "none";
				if (kindWithNeighbours !== aloneKind) {
					return `"${line}" is ${aloneKind} alone but ${kindWithNeighbours} between "${before}" and "${after}"`;
				}
			}
		}
	}
	return null;
}
