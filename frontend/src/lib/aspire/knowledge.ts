/** The shape of an assistant answer, and how the service's text becomes one. */

import type { Directive } from "../stream/types";

export type AnswerBlock =
	| { kind: "paragraph"; text: string }
	| { kind: "list"; items: Array<string>; ordered: boolean };

export interface Answer {
	blocks: Array<AnswerBlock>;
	followUps: Array<string>;
	/** What the turn asked the client to render alongside the prose. */
	directives?: Array<Directive>;
}

/** `- item`, `* item`, or `1. item`. */
const BULLET = /^\s*(?:[-*•]|\d+[.)])\s+/;
/** The numbered subset of `BULLET`. */
const ORDERED_BULLET = /^\s*\d+[.)]\s+/;
/** Leading `#`s and trailing `#`s from a markdown heading. */
const HEADING = /^\s*#{1,6}\s+|\s+#+\s*$/g;

/** Parses the service's markdown into transcript blocks. */
export function parseAnswer(markdown: string): Array<AnswerBlock> {
	const blocks: Array<AnswerBlock> = [];
	let paragraph: Array<string> = [];
	let items: Array<string> = [];
	// Decided by the marker that opens the run.
	let ordered = false;

	const flushParagraph = () => {
		if (paragraph.length === 0) return;
		blocks.push({ kind: "paragraph", text: paragraph.join(" ") });
		paragraph = [];
	};

	const flushList = () => {
		if (items.length === 0) return;
		blocks.push({ kind: "list", items, ordered });
		items = [];
		ordered = false;
	};

	for (const rawLine of markdown.replace(/\r\n/g, "\n").split("\n")) {
		const line = rawLine.trim();

		if (!line) {
			// A blank line closes whatever was open.
			flushParagraph();
			flushList();
			continue;
		}

		if (BULLET.test(line)) {
			// A bullet interrupts prose without needing a blank line first.
			flushParagraph();
			if (items.length === 0) ordered = ORDERED_BULLET.test(line);
			items.push(line.replace(BULLET, "").trim());
			continue;
		}

		flushList();
		paragraph.push(line.replace(HEADING, "").trim());
	}

	flushParagraph();
	flushList();

	// An answer that parsed to nothing would render as an empty bubble.
	if (blocks.length === 0 && markdown.trim()) {
		blocks.push({ kind: "paragraph", text: markdown.trim() });
	}

	return blocks;
}

/** Drops markdown syntax. For the clipboard and for screen-reader output. */
function plain(text: string) {
	return (
		text
			// A link becomes "label (target)", unless the label already is the target.
			.replace(
				/\[([^\]]*)\]\(([^)\s]*)\)/g,
				(_match, label: string, href: string) => {
					const bare = href.replace(/^https?:\/\//i, "").replace(/\/$/, "");
					return label.trim() === bare ? bare : `${label} (${bare})`;
				},
			)
			.replace(/\*\*(.+?)\*\*/g, "$1")
			.replace(/`([^`]+)`/g, "$1")
	);
}

/** Flattens an answer to text — used for the clipboard and for announcements. */
export function answerToText(blocks: Array<AnswerBlock>) {
	return blocks
		.map((block) =>
			block.kind === "paragraph"
				? plain(block.text)
				: block.items
						.map(
							(item, index) =>
								`${block.ordered ? `${index + 1}.` : "•"} ${plain(item)}`,
						)
						.join("\n"),
		)
		.join("\n\n");
}

/** One rendered run of an answer. Bold nests, because links appear inside it. */
export type InlineNode =
	| { kind: "text"; text: string }
	| { kind: "bold"; children: Array<InlineNode> }
	| { kind: "link"; text: string; href: string };

/** Complete markdown link: `[label](target)`. */
const MD_LINK = /\[([^\]]*)\]\(((?:[^()\s]|\([^)\s]*\))*)\)/;
/** A link the typewriter has only half-revealed. */
const PARTIAL_LINK = /\[([^\]]*)(?:\](?:\([^)]*)?)?$/;

/** A URL, a bare domain, or an email address sitting loose in prose. */
const NATIONAL_TLD = "kn|gov|org|edu";
const GENERIC_TLD = "com|net|io|co|uk";
const AUTOLINK = new RegExp(
	[
		// Explicit scheme: always a link, path or not.
		"https?://[^\\s<>()]+",
		// Email address.
		"[\\w.+-]+@[a-z0-9-]+(?:\\.[a-z0-9-]+)+",
		// Bare national/institutional domain, path optional.
		`(?:[a-z0-9-]+\\.)+(?:${NATIONAL_TLD})(?![\\w-])(?:/[^\\s<>()]*)?`,
		// Bare generic domain, path required.
		`(?:[a-z0-9-]+\\.)+(?:${GENERIC_TLD})(?![\\w-])/[^\\s<>()]*`,
	].join("|"),
	"gi",
);

/** Turn a target into something safe to put in `href`. */
export function safeHref(raw: string): string | null {
	const value = raw.trim();
	if (!value) return null;
	if (/^https?:\/\//i.test(value)) return value;
	if (/^mailto:/i.test(value)) return value;
	if (/^[\w.+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+$/i.test(value))
		return `mailto:${value}`;
	if (/^(?:[a-z0-9-]+\.)+[a-z]{2,}(?:\/[^\s]*)?$/i.test(value))
		return `https://${value}`;
	return null;
}

/** Links a run of plain prose, leaving everything else as text. */
function autolink(segment: string): Array<InlineNode> {
	const nodes: Array<InlineNode> = [];
	let last = 0;

	for (const match of segment.matchAll(AUTOLINK)) {
		const start = match.index ?? 0;
		// A sentence-ending period must not be swallowed into the target.
		const raw = match[0].replace(/[.,;:!?)]+$/, "");
		const href = safeHref(raw);

		if (start > last)
			nodes.push({ kind: "text", text: segment.slice(last, start) });
		if (href) nodes.push({ kind: "link", text: raw, href });
		else nodes.push({ kind: "text", text: raw });

		// Push back whatever punctuation was trimmed off the end.
		const trailing = match[0].slice(raw.length);
		if (trailing) nodes.push({ kind: "text", text: trailing });
		last = start + match[0].length;
	}

	if (last < segment.length)
		nodes.push({ kind: "text", text: segment.slice(last) });
	return nodes;
}

/** Resolves markdown links, then autolinks whatever prose is left. */
function parseLinks(segment: string, revealing: boolean): Array<InlineNode> {
	const nodes: Array<InlineNode> = [];
	let rest = segment;

	for (let match = MD_LINK.exec(rest); match; match = MD_LINK.exec(rest)) {
		const [whole, label, target] = match;
		const index = match.index;
		if (index > 0) nodes.push(...autolink(rest.slice(0, index)));

		const href = safeHref(target);
		const text = label.trim() || target;
		if (href) nodes.push({ kind: "link", text, href });
		else nodes.push({ kind: "text", text });

		rest = rest.slice(index + whole.length);
	}

	// Mid-stream the closing `)` may not have arrived yet.
	if (revealing) {
		const partial = rest.match(PARTIAL_LINK);
		if (partial) {
			const head = rest.slice(0, partial.index);
			if (head) nodes.push(...autolink(head));
			if (partial[1]) nodes.push({ kind: "text", text: partial[1] });
			return nodes;
		}
	}

	if (rest) nodes.push(...autolink(rest));
	return nodes;
}

/** Parse one block of answer text into renderable runs. */
export function parseInline(
	text: string,
	revealing = false,
): Array<InlineNode> {
	const nodes: Array<InlineNode> = [];
	let rest = text;

	while (rest.length > 0) {
		const open = rest.indexOf("**");
		if (open === -1) {
			nodes.push(...parseLinks(rest, revealing));
			break;
		}

		if (open > 0) nodes.push(...parseLinks(rest.slice(0, open), revealing));

		const after = rest.slice(open + 2);
		const close = after.indexOf("**");
		if (close === -1) {
			// No closer.
			if (revealing) {
				if (after)
					nodes.push({ kind: "bold", children: parseLinks(after, true) });
			} else {
				nodes.push({ kind: "text", text: "**" });
				if (after) nodes.push(...parseLinks(after, false));
			}
			break;
		}

		nodes.push({
			kind: "bold",
			children: parseLinks(after.slice(0, close), revealing),
		});
		rest = after.slice(close + 2);
	}

	return nodes.filter((node) => node.kind !== "text" || node.text.length > 0);
}

/**
 * Prompts offered on the landing screen, before there is any conversation.
 *
 * All four used to be programme questions, so nothing on the landing page
 * revealed that the assistant also teaches lessons and runs games -- a reader
 * had to already know to ask. Two of them additionally opened the eligibility
 * wizard rather than answering, because they were worded exactly like the
 * intent patterns; that half is fixed in `intents.py`, and these now cover the
 * four things this assistant actually does: explain the programme, help you
 * join it, teach, and play.
 *
 * The wording is load-bearing. "Can we play a game?" reaches `wants_game`
 * without naming one, so the reply offers the games this reader's band may
 * have rather than launching a game they cannot. "Teach me about saving"
 * reaches `wants_lesson`. Both verified against the predicates rather than
 * assumed -- the last set was not.
 */
export const starterPrompts = [
	"What is the ASPIRE Programme?",
	"How do I apply for ASPIRE?",
	"Teach me about saving",
	"Can we play a game?",
] as const;
