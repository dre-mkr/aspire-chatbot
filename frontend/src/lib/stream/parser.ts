/**
 * The settled-block parser, extended so a directive can sit inside the flow.
 *
 * `lib/aspire/settled.ts` already answers "how much of a growing reply is safe
 * to put on screen", and its answer is subtle and hard-won -- see its own
 * docstring for the paragraph-freeze it exists to remove. Nothing here changes
 * it. This module wraps it and adds the one thing the v2 protocol needs: prose
 * and directives arrive interleaved by ordinal, and the typewriter has to walk
 * both in order.
 *
 * ## A directive is a TERMINAL SETTLED BLOCK
 *
 * That phrase carries three separate commitments.
 *
 *   **Terminal.** Once a directive is in the timeline it never changes and it
 *   never grows. Prose blocks can gain words; a directive cannot gain fields.
 *
 *   **Settled.** Everything before it is settled by construction: the server
 *   emitted it at an ordinal, so every token with a lower ordinal is already
 *   final. The typewriter may reveal all of it without waiting.
 *
 *   **Atomic.** It renders whole or not at all. The server never emits a
 *   partial one -- `StreamInterceptor` buffers widget JSON precisely so this
 *   is true -- and this module never splits one.
 *
 * ## The completion flash, and not reintroducing it
 *
 * The flash was: the typewriter revealed a prefix, then the finished answer
 * replaced the revealed one in a single frame, and everything appeared at once.
 * The fix was that the settled region is append-only and the reveal walks it
 * rather than being replaced by it.
 *
 * Adding directives could reintroduce it in one specific way: if a directive
 * arriving caused the prose timeline to be rebuilt from scratch, every block
 * would be new and the reveal would restart. `timeline()` therefore keeps prose
 * blocks and directives in ONE array whose prose entries are produced by the
 * same `settledBlocks` call as before, so a directive is inserted *between*
 * blocks and never inside the sequence that the reveal is indexing into.
 * `assertNoFlash` states that as an executable claim.
 */
import type { AnswerBlock } from "../aspire/knowledge.ts";
import {
	blockIsClosed,
	settledBlocks,
	settledText,
} from "../aspire/settled.ts";
import type { Directive } from "./types.ts";

export type { AnswerBlock };
export { settledText, settledBlocks, blockIsClosed };

/** One prose block, with the ordinal of the last token that contributed to it. */
export interface ProseEntry {
	kind: "prose";
	block: AnswerBlock;
	/** Index within the prose-only sequence. The reveal indexes by this. */
	index: number;
}

/** One directive, at the ordinal the server gave it. */
export interface DirectiveEntry {
	kind: "directive";
	directive: Directive;
	ordinal: number;
}

export type TimelineEntry = ProseEntry | DirectiveEntry;

/** A directive and where it sits in the prose. */
export interface PlacedDirective {
	directive: Directive;
	ordinal: number;
	/**
	 * How many characters of prose had arrived when it was emitted.
	 *
	 * Recorded by the client as tokens land, because ordinals count EVENTS and
	 * the parser works in characters. Converting once, at arrival, beats
	 * re-deriving it on every render tick.
	 */
	afterChars: number;
}

/**
 * The ordered mixture of prose blocks and directives.
 *
 * Prose comes from `settledBlocks`, unchanged, so every property that module
 * guarantees still holds. Directives are spliced in at the block boundary
 * nearest the character offset they were emitted at -- a directive can only
 * ever sit BETWEEN blocks, never inside a paragraph, because a paragraph
 * interrupted by a card is a paragraph that has to re-flow around it.
 */
export function timeline(
	buffer: string,
	ended: boolean,
	directives: Array<PlacedDirective>,
): Array<TimelineEntry> {
	const blocks = settledBlocks(buffer, ended);
	if (directives.length === 0) {
		return blocks.map((block, index) => ({ kind: "prose", block, index }));
	}

	// Where each block ends, in characters of the settled buffer. Blocks are
	// produced in order and the settled text is append-only, so a running
	// cursor is enough -- and it means this is linear rather than a search per
	// directive.
	const settled = settledText(buffer, ended);
	const ends = blockEndOffsets(settled, blocks);

	const entries: Array<TimelineEntry> = [];
	const pending = [...directives].sort((a, b) => a.ordinal - b.ordinal);
	let next = 0;

	blocks.forEach((block, index) => {
		// Anything emitted STRICTLY before this block finished belongs above it.
		//
		// Strict, not `<=`, and the boundary is the common case rather than an
		// edge one: a directive emitted at the exact moment a paragraph ended is
		// a directive about that paragraph, and `<=` would render it above the
		// sentence it refers to.
		while (next < pending.length && pending[next].afterChars < ends[index]) {
			entries.push({
				kind: "directive",
				directive: pending[next].directive,
				ordinal: pending[next].ordinal,
			});
			next += 1;
		}
		entries.push({ kind: "prose", block, index });
	});

	// Whatever is left came after all the settled prose. Directives arriving
	// during a turn are the normal case for chips and citations, which the
	// server deliberately emits last.
	for (; next < pending.length; next += 1) {
		entries.push({
			kind: "directive",
			directive: pending[next].directive,
			ordinal: pending[next].ordinal,
		});
	}

	return entries;
}

/** Matches `parseAnswer`'s bullet rule. Kept in step by `blockEndOffsets`. */
const BULLET = /^\s*(?:[-*•]|\d+[.)])\s+/;

/**
 * The character offset at which each block ends in the settled buffer.
 *
 * Computed by re-walking the LINES with the same grouping rule `parseAnswer`
 * uses -- consecutive prose lines are one paragraph, consecutive bullets are
 * one list, a blank line closes whatever is open.
 *
 * The obvious implementation is to search the buffer for each block's own text,
 * and it is wrong in a way that is invisible in a single-line test: `parseAnswer`
 * joins a multi-line paragraph WITH SPACES, so the block's text does not occur
 * in the buffer at all once a paragraph spans two lines. Every offset then
 * collapses to the end of the document and every directive renders above all
 * the prose.
 *
 * If the two ever drift, the failure is a directive one block out of place --
 * visible, non-fatal, and caught by `parser.test.ts`.
 */
function blockEndOffsets(
	settled: string,
	blocks: Array<AnswerBlock>,
): Array<number> {
	const offsets: Array<number> = [];
	let cursor = 0;
	let open: "paragraph" | "list" | null = null;

	// `split` keeps the terminators out, so each line costs its own length plus
	// one for the newline it was split on. Tracking that explicitly is what
	// keeps the offsets comparable with the client's character count.
	const lines = settled.split("\n");
	lines.forEach((line, index) => {
		const length = line.length + (index < lines.length - 1 ? 1 : 0);
		const kind: "paragraph" | "list" | null = !line.trim()
			? null
			: BULLET.test(line)
				? "list"
				: "paragraph";

		if (open !== null && kind !== open) {
			offsets.push(cursor);
			open = null;
		}
		cursor += length;
		if (kind !== null) open = kind;
	});

	if (open !== null) offsets.push(cursor);

	// Pad or trim to match the block count. A mismatch means the grouping rule
	// above has drifted from `parseAnswer`; padding with the document end puts
	// the extra directives last, which is the harmless direction.
	while (offsets.length < blocks.length) offsets.push(settled.length);
	return offsets.slice(0, blocks.length);
}

/**
 * How many prose blocks the timeline holds.
 *
 * The reveal counts prose, not entries: a directive is not something to type
 * out a word at a time.
 */
export function proseCount(entries: Array<TimelineEntry>): number {
	return entries.filter((entry) => entry.kind === "prose").length;
}

/**
 * The claim this module rests on, as something that can fail.
 *
 * Adding directives must not reintroduce the completion flash. The flash comes
 * from the revealed sequence being REPLACED rather than extended, so the check
 * is that the prose sequence produced at every prefix is a prefix of the one
 * produced at the end -- with directives present throughout.
 *
 * Exported rather than inlined into a test so it travels with the rule it
 * protects, exactly as `assertPrefixLocal` does in `settled.ts`.
 */
export function assertNoFlash(
	text: string,
	directives: Array<PlacedDirective>,
): string | null {
	let previous: Array<string> = [];
	for (let cut = 1; cut <= text.length; cut += 1) {
		const visible = directives.filter((d) => d.afterChars <= cut);
		const entries = timeline(text.slice(0, cut), false, visible);
		const prose = entries
			.filter((entry): entry is ProseEntry => entry.kind === "prose")
			.map((entry) => renderBlock(entry.block));

		for (let index = 0; index < previous.length; index += 1) {
			const before = previous[index];
			const after = prose[index];
			if (after === undefined) {
				return `at ${cut} characters block ${index} disappeared: "${before.slice(-40)}"`;
			}
			if (!after.startsWith(before)) {
				return `at ${cut} characters block ${index} was rewritten: "${before.slice(-40)}" -> "${after.slice(-40)}"`;
			}
		}
		previous = prose;
	}

	const final = timeline(text, true, directives)
		.filter((entry): entry is ProseEntry => entry.kind === "prose")
		.map((entry) => renderBlock(entry.block));
	for (let index = 0; index < previous.length; index += 1) {
		if (!final[index]?.startsWith(previous[index])) {
			return `the finished timeline does not extend block ${index}`;
		}
	}
	return null;
}

function renderBlock(block: AnswerBlock): string {
	return block.kind === "paragraph" ? block.text : block.items.join("\n");
}
