/** The settled-block parser, extended so a directive can sit inside the flow. */
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
	/** How many characters of prose had arrived when it was emitted. */
	afterChars: number;
}

/** The ordered mixture of prose blocks and directives. */
export function timeline(
	buffer: string,
	ended: boolean,
	directives: Array<PlacedDirective>,
): Array<TimelineEntry> {
	const blocks = settledBlocks(buffer, ended);
	if (directives.length === 0) {
		return blocks.map((block, index) => ({ kind: "prose", block, index }));
	}

	// Where each block ends, in characters of the settled buffer.
	const settled = settledText(buffer, ended);
	const ends = blockEndOffsets(settled, blocks);

	const entries: Array<TimelineEntry> = [];
	const pending = [...directives].sort((a, b) => a.ordinal - b.ordinal);
	let next = 0;

	blocks.forEach((block, index) => {
		// Anything emitted STRICTLY before this block finished belongs above it.
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

	// Whatever is left came after all the settled prose.
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

/** The character offset at which each block ends in the settled buffer. */
function blockEndOffsets(
	settled: string,
	blocks: Array<AnswerBlock>,
): Array<number> {
	const offsets: Array<number> = [];
	let cursor = 0;
	let open: "paragraph" | "list" | null = null;

	// `split` keeps the terminators out, so each line costs its own length plus one for the newline it was split on.
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

	// Pad or trim to match the block count.
	while (offsets.length < blocks.length) offsets.push(settled.length);
	return offsets.slice(0, blocks.length);
}

/** How many prose blocks the timeline holds. */
export function proseCount(entries: Array<TimelineEntry>): number {
	return entries.filter((entry) => entry.kind === "prose").length;
}

/** The claim this module rests on, as something that can fail. */
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
