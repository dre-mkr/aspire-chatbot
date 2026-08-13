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

	// The tail's kind is decided, so show its words — bar the last, likely half-typed.
	const lastSpace = tail.lastIndexOf(" ");
	if (lastSpace === -1) return closed;

	const head = tail.slice(0, lastSpace);
	// Dropping the partial word can put the line back into the state just rejected.
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

