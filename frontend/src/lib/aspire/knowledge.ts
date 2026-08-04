/**
 * The shape of an assistant answer, and how the service's text becomes one.
 *
 * The backend returns one markdown string. The transcript renders ordered
 * blocks, and the typewriter reveals them a few words at a time, so the reply
 * is parsed into blocks once on arrival rather than re-parsed on every tick.
 */

export type AnswerBlock =
	| { kind: "paragraph"; text: string }
	| { kind: "list"; items: Array<string>; ordered: boolean };

export interface Answer {
	blocks: Array<AnswerBlock>;
	followUps: Array<string>;
}

/** `- item`, `* item`, or `1. item`. */
const BULLET = /^\s*(?:[-*•]|\d+[.)])\s+/;
/**
 * The numbered subset of `BULLET`.
 *
 * The marker is stripped from the item text either way, so this is the only
 * thing that remembers a list was a numbered procedure. "How do I apply for
 * ASPIRE?" is one of the four landing starters and its answer is steps — losing
 * the numbering there is the finding this exists to prevent.
 */
const ORDERED_BULLET = /^\s*\d+[.)]\s+/;
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
	// Decided by the marker that opens the run. A list that starts numbered stays
	// numbered even if the model switches to dashes partway down: renumbering
	// mid-list would be a worse lie than a stray dash.
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
 *
 * The TLD list is split because a dotted token is not evidence of a link. The
 * old single list turned `document.cookie` into a link to `https://document.co`
 * — it matched `.co` and simply abandoned `okie`. Two rules fix that class:
 *
 *   1. `(?![\w-])` after the TLD, so a TLD must end the token rather than sit
 *      inside a longer word. Kills `document.cookie` and `example.command`.
 *   2. Generic TLDs must carry a path. `config.io` and `index.co` read as code
 *      far more often than as destinations, whereas nobody writes `aspire.gov.kn`
 *      meaning anything but the site.
 *
 * Checked against the live corpus: it links every real destination there —
 * `*.gov.kn` bare, and `facebook.com/…`, `instagram.com/…`, `tiktok.com/…`
 * with paths — while leaving prose alone.
 */
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

	// Mid-stream the closing `)` may not have arrived yet. Show the label rather
	// than raw brackets: it is about to become a link, and flashing `[` reads
	// as a glitch.
	//
	// Only while revealing. On settled text there is no closing `)` still in
	// flight, so a bracket is the author's own — a citation marker or a
	// placeholder — and eating it is wrong. Because the pattern is anchored to
	// `$` it only ever ate the LAST bracketed run, so "Choose [A] or [B]" drew
	// the same construct two different ways in one sentence.
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

/**
 * Parse one block of answer text into renderable runs.
 *
 * Bold is resolved first because the model routinely writes a link inside it
 * (`**[aspire.gov.kn](https://aspire.gov.kn/)**`), so links have to be found
 * within bold rather than beside it.
 *
 * The typewriter reveals a few words per tick, so half-written markup arrives
 * constantly. While `revealing`, an unterminated `**` is treated as bold and an
 * unterminated link renders as its label; both settle correctly once the rest
 * lands.
 *
 * `revealing` defaults to false because settled text is the steady state — a
 * reply is mid-reveal for a few seconds and rendered for the rest of the
 * session. Optimistic markup on settled text is not tolerance, it is a wrong
 * render that never corrects itself: an odd number of asterisks left the tail
 * bold permanently, and a bracket lost its brackets.
 */
export function parseInline(text: string, revealing = false): Array<InlineNode> {
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
			// No closer. Mid-reveal it has not arrived yet; settled it is never
			// coming, so the asterisks are literal text the author typed.
			if (revealing) {
				if (after) nodes.push({ kind: "bold", children: parseLinks(after, true) });
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
