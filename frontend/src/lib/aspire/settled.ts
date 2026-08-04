/**
 * Which of a growing reply is safe to put on screen.
 *
 * The typewriter reveals text a few words at a time. When the text was already
 * complete that was trivially safe. It arrives in pieces now, and the naive
 * approach — re-parse the whole buffer every tick and index into the result —
 * is a bug with a very specific symptom: a line that was a paragraph becomes a
 * list item the moment a space lands after its hyphen, and everything already
 * on screen shifts. `stream-corpus.mjs` reproduces that in eight places.
 *
 * So the buffer is split into a settled region and a held tail.
 *
 *   **Settled** — text that can no longer be re-read. Append-only, stable
 *   indices, and the only thing the typewriter is allowed to touch.
 *
 *   **Held** — the part that could still turn into something else, plus the
 *   partial word at the very end.
 *
 * ## Why the boundary is a word, not a line
 *
 * It was a line, and that was the whole problem. `parseAnswer` classifies each
 * line by that line's own content, so the instant a line's terminating newline
 * arrived, what that line *was* had been decided forever — correct, and far too
 * conservative. A markdown paragraph is one line. Holding until the newline
 * meant holding an entire paragraph, so the reveal could only ever advance in
 * paragraph-sized jumps: it emptied its buffer in a fraction of a second, froze
 * for as long as the model took to write the next paragraph, then emptied it
 * again. `reveal-sim.mjs` measured a 2.16-second freeze mid-answer at a
 * realistic 25 tokens a second. That is the stall this file exists to remove.
 *
 * The finer boundary comes from a stronger reading of the same property. A
 * line's classification is decided by its *prefix*: `BULLET` needs a marker and
 * a space, `HEADING` needs its hashes and a space, and both live at the start of
 * the line. Once a character has landed that no marker can still absorb, the
 * line's kind is settled even though the line is not finished. Everything after
 * that point is content being appended to a block whose identity is already
 * fixed — and appending never moves what has already been read.
 *
 * So the hold shrinks from "one whole paragraph" to "one ambiguous prefix, and
 * then one partial word". At 25 tokens a second that is roughly 150ms of lag
 * instead of several seconds of freeze.
 *
 * The property is not assumed. `assertPrefixLocal` states it as an executable
 * claim, and the corpus checks it against the real parser under chunking
 * designed to break it. If the renderer ever gains a construct that reads its
 * neighbours — a real table, a fenced code block, a setext heading — that guard
 * fails and this file has to become more conservative before anything ships.
 */
import { type AnswerBlock, parseAnswer } from "./knowledge";

/**
 * A trailing line that has not yet said what it is.
 *
 * Matches a line consisting of nothing but optional indentation, at most one
 * thing that could begin a block, and optional trailing space. In that state
 * `-` might become `- item` or `-5 degrees`, `*` might become `* item` or
 * `**bold**`, and `1.` might become `1. item` or `1.5 million` — so none of it
 * may be shown.
 *
 * The trailing `\s*` matters as much as the marker does: `parseAnswer` trims
 * each line before classifying it, so `"- "` would parse as the paragraph `"-"`
 * and put a literal hyphen on screen a tick before it became a bullet.
 */
const UNDECIDED = /^\s*(?:[-*•>]|\d+[.)]?|#{1,6})?\s*$/;

/**
 * The prefix of the buffer that can be parsed and shown.
 *
 * `ended` collapses the distinction: once the service has said the turn is over,
 * nothing can change what it is and the whole buffer settles at once.
 */
export function settledText(buffer: string, ended: boolean): string {
	if (ended) return buffer;

	const lastBreak = buffer.lastIndexOf("\n");
	// Every completed line, terminator included. Empty until the first newline.
	const closed = buffer.slice(0, lastBreak + 1);
	const tail = buffer.slice(lastBreak + 1);

	// The tail could still become a bullet, a heading or a quote. Nothing of it
	// is safe, including the marker itself.
	if (UNDECIDED.test(tail)) return closed;

	// The tail's kind is decided, so its words may be shown — except the last
	// one, which is probably half-written. Revealing "gov" and then growing it
	// into "government-owned" is the one kind of movement a reader notices.
	const lastSpace = tail.lastIndexOf(" ");
	if (lastSpace === -1) return closed;

	const head = tail.slice(0, lastSpace);
	// Dropping the partial word can put the line straight back into the state
	// the check above just rejected: `"- open"` has a decided kind, but cutting
	// at its only space leaves `"-"`, which parses as a paragraph containing a
	// hyphen. The tail being decided is not enough — the part actually shown has
	// to be decided too, and the corpus fails here loudly when it is not.
	if (UNDECIDED.test(head)) return closed;
	return closed + head;
}

/**
 * The blocks that may be revealed, given everything received so far.
 *
 * The last block returned may still grow — a paragraph gaining words, a list
 * gaining items — which is why `blockIsClosed` exists and why the typewriter
 * must consult it before stepping past anything.
 */
export function settledBlocks(
	buffer: string,
	ended: boolean,
): Array<AnswerBlock> {
	return parseAnswer(settledText(buffer, ended));
}

/**
 * Whether a block may be advanced past, or might still grow.
 *
 * Only the last settled block can gain more: another word joining a paragraph,
 * another item joining a list. Anything with a block after it is closed, and
 * once the turn has ended so is the last one.
 *
 * Getting this wrong in the permissive direction is what strands content — the
 * typewriter steps past a block, the block grows, and the words that arrived
 * afterwards are never revealed at all. They then appear in one frame when the
 * finished answer replaces the revealed one, which is the "everything lands at
 * once" ending this whole file is trying to avoid.
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
 * Classification must depend on the line's own prefix. If it does, then the
 * moment `settledText` is willing to show a line, that line's kind is already
 * final, and the settled region can never be rewritten.
 *
 * Checked by growing each line one character at a time — which is what the wire
 * actually does — and, at every prefix the settling rule would release,
 * comparing how that line is classified against how the finished line is
 * classified. A construct whose meaning arrives later than its first word shows
 * up here as a mismatch.
 *
 * Exported rather than inlined into a test so it travels with the rule it
 * protects: whoever extends the renderer meets it in the same file that
 * explains why it matters.
 */
export function assertPrefixLocal(lines: Array<string>): string | null {
	for (const line of lines) {
		if (!line.trim()) continue;
		const whole = parseAnswer(`${line}\n`);
		const finalKind = whole[0]?.kind ?? "none";

		for (let cut = 1; cut <= line.length; cut += 1) {
			// What the buffer looks like with `cut` characters of this line in
			// hand and no newline yet.
			const revealed = settledText(line.slice(0, cut), false);
			if (!revealed.trim()) continue;

			const blocks = parseAnswer(revealed);
			const kind = blocks[blocks.length - 1]?.kind ?? "none";
			if (kind !== finalKind) {
				return `"${line}" shows as ${kind} at "${revealed}" but is ${finalKind} once complete`;
			}
		}
	}
	return null;
}

/**
 * The other half of the claim: what is shown never stops being shown.
 *
 * `assertPrefixLocal` checks that a line's *kind* is stable. This checks that
 * its *text* only ever grows — that no prefix reveals a character the finished
 * render then takes away. Together they are the whole no-movement guarantee.
 */
export function assertAppendOnly(text: string): string | null {
	let previous = "";
	for (let cut = 1; cut <= text.length; cut += 1) {
		const revealed = settledText(text.slice(0, cut), false);
		if (!revealed.startsWith(previous)) {
			return `at ${cut} characters the settled text stopped extending: "${previous.slice(-40)}" → "${revealed.slice(-40)}"`;
		}
		previous = revealed;
	}
	if (!settledText(text, true).startsWith(previous)) {
		return `the finished text does not extend what was revealed: "${previous.slice(-40)}"`;
	}
	return null;
}
