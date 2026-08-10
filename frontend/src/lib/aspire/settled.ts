/** Which of a growing reply is safe to put on screen. */
// Explicit `.ts`, like every other import in the modules `node --test` reaches.
import { type AnswerBlock, parseAnswer } from "./knowledge.ts";

/** A trailing line that has not yet said what it is. */
const UNDECIDED = /^\s*(?:[-*•>]|\d+[.)]?|#{1,6})?\s*$/;

/** The prefix of the buffer that can be parsed and shown. */
export function settledText(buffer: string, ended: boolean): string {
	if (ended) return buffer;

	const lastBreak = buffer.lastIndexOf("\n");
	// Every completed line, terminator included. Empty until the first newline.
	const closed = buffer.slice(0, lastBreak + 1);
	const tail = buffer.slice(lastBreak + 1);

	// The tail could still become a bullet, a heading or a quote.
	if (UNDECIDED.test(tail)) return closed;

	// The tail's kind is decided, so its words may be shown — except the last one, which is probably half-written.
	const lastSpace = tail.lastIndexOf(" ");
	if (lastSpace === -1) return closed;

	const head = tail.slice(0, lastSpace);
	// Dropping the partial word can put the line straight back into the state the check above just rejected: `"- op…
	if (UNDECIDED.test(head)) return closed;
	return closed + head;
}

/** The blocks that may be revealed, given everything received so far. */
export function settledBlocks(
	buffer: string,
	ended: boolean,
): Array<AnswerBlock> {
	return parseAnswer(settledText(buffer, ended));
}

/** Whether a block may be advanced past, or might still grow. */
export function blockIsClosed(
	index: number,
	blocks: Array<AnswerBlock>,
	ended: boolean,
): boolean {
	return ended || index < blocks.length - 1;
}

/** The claim this module rests on, as something that can fail. */
export function assertPrefixLocal(lines: Array<string>): string | null {
	for (const line of lines) {
		if (!line.trim()) continue;
		const whole = parseAnswer(`${line}\n`);
		const finalKind = whole[0]?.kind ?? "none";

		for (let cut = 1; cut <= line.length; cut += 1) {
			// What the buffer looks like with `cut` characters of this line in hand and no newline yet.
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

/** The other half of the claim: what is shown never stops being shown. */
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
