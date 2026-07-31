/**
 * The shape of an assistant answer, and how the service's text becomes one.
 *
 * The backend returns one markdown string. The transcript renders ordered
 * blocks, and the typewriter reveals them a few words at a time, so the reply
 * is parsed into blocks once on arrival rather than re-parsed on every tick.
 */

export type AnswerBlock =
	| { kind: "paragraph"; text: string }
	| { kind: "list"; items: Array<string> };

export interface Answer {
	blocks: Array<AnswerBlock>;
	followUps: Array<string>;
}

/** `- item`, `* item`, or `1. item`. */
const BULLET = /^\s*(?:[-*•]|\d+[.)])\s+/;
/** Leading `#`s and trailing `#`s from a markdown heading. */
const HEADING = /^\s*#{1,6}\s+|\s+#+\s*$/g;

/**
 * Parses the service's markdown into transcript blocks.
 *
 * Handles what the system prompt actually asks the model for — prose and
 * bullets — and degrades gracefully for anything else it emits anyway.
 */
export function parseAnswer(markdown: string): Array<AnswerBlock> {
	const blocks: Array<AnswerBlock> = [];
	let paragraph: Array<string> = [];
	let items: Array<string> = [];

	const flushParagraph = () => {
		if (paragraph.length === 0) return;
		blocks.push({ kind: "paragraph", text: paragraph.join(" ") });
		paragraph = [];
	};

	const flushList = () => {
		if (items.length === 0) return;
		blocks.push({ kind: "list", items });
		items = [];
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
				: block.items.map((item) => `• ${plain(item)}`).join("\n"),
		)
		.join("\n\n");
}

/** One rendered run of an answer. Bold nests, because links appear inside it. */
export type InlineNode =
	| { kind: "text"; text: string }
	| { kind: "bold"; children: Array<InlineNode> }
	| { kind: "link"; text: string; href: string };

/**
 * Complete markdown link: `[label](target)`.
 *
 * The target tolerates one level of nested parentheses so a pathological
 * `(javascript:alert(1))` is consumed whole and refused, rather than being cut
 * at the inner bracket and leaving a stray `)` in the prose.
 */
const MD_LINK = /\[([^\]]*)\]\(((?:[^()\s]|\([^)\s]*\))*)\)/;
/**
 * A link the typewriter has only half-revealed. Every closing character is
 * optional, so `[label`, `[label]`, and `[label](htt` all match and render as
 * the bare label.
 */
const PARTIAL_LINK = /\[([^\]]*)(?:\](?:\([^)]*)?)?$/;

/**
 * A URL, a bare domain, or an email address sitting loose in prose.
 * Bare domains need an explicit TLD so "St. Kitts" and "1.5" are left alone.
 */
const AUTOLINK =
	/https?:\/\/[^\s<>()]+|[\w.+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+|(?:[a-z0-9-]+\.)+(?:kn|com|org|net|gov|edu|io|co|uk)(?:\/[^\s<>()]*)?/gi;

/**
 * Turn a target into something safe to put in `href`.
 *
 * The text comes from a language model, so `javascript:` and `data:` targets
 * are refused outright rather than sanitised; anything unrecognised renders as
 * plain text instead of becoming a link.
 */
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
function parseLinks(segment: string): Array<InlineNode> {
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

	// Mid-stream the closing `)` may not have arrived yet. Show the label rather
	// than raw brackets: it is about to become a link, and flashing `[` reads
	// as a glitch.
	const partial = rest.match(PARTIAL_LINK);
	if (partial) {
		const head = rest.slice(0, partial.index);
		if (head) nodes.push(...autolink(head));
		if (partial[1]) nodes.push({ kind: "text", text: partial[1] });
		return nodes;
	}

	if (rest) nodes.push(...autolink(rest));
	return nodes;
}

/**
 * Parse one block of answer text into renderable runs.
 *
 * Bold is resolved first because the model routinely writes a link inside it
 * (`**[aspire.gov.kn](https://aspire.gov.kn/)**`), so links have to be found
 * within bold rather than beside it.
 *
 * The typewriter reveals a few words per tick, so half-written markup arrives
 * constantly. An unterminated `**` is treated as bold and an unterminated link
 * renders as its label; both settle correctly once the rest lands.
 */
export function parseInline(text: string): Array<InlineNode> {
	const nodes: Array<InlineNode> = [];
	let rest = text;

	while (rest.length > 0) {
		const open = rest.indexOf("**");
		if (open === -1) {
			nodes.push(...parseLinks(rest));
			break;
		}

		if (open > 0) nodes.push(...parseLinks(rest.slice(0, open)));

		const after = rest.slice(open + 2);
		const close = after.indexOf("**");
		if (close === -1) {
			if (after) nodes.push({ kind: "bold", children: parseLinks(after) });
			break;
		}

		nodes.push({ kind: "bold", children: parseLinks(after.slice(0, close)) });
		rest = after.slice(close + 2);
	}

	return nodes.filter((node) => node.kind !== "text" || node.text.length > 0);
}

/**
 * Prompts offered on the landing screen, before there is any conversation.
 *
 * These are the questions people actually arrive with, in the order they tend to
 * ask them: what is this, am I eligible, how do I join, what does it cost. Each
 * one is the lead question of one of the knowledge base's largest categories
 * (Overview, Eligibility, Application), so every chip lands on a well-covered
 * answer rather than a dead end.
 *
 * Keep them short enough to stay on one line — they render as pills — and keep
 * the wording close to the knowledge base's own phrasing, which is what makes
 * retrieval hit cleanly.
 */
export const starterPrompts = [
	"What is the ASPIRE Programme?",
	"Who is eligible to join ASPIRE?",
	"How do I apply for ASPIRE?",
	"Does it cost anything to join?",
] as const;
