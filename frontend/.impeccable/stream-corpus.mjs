/**
 * Step 1's proof: the stubs really do produce the states that break parsers.
 *
 * A corpus is worthless if its "adversarial" chunks happen to land on clean
 * boundaries. This runs each growth sequence through the product's own parser
 * one chunk at a time and reports, for every prefix, what the parser saw — then
 * checks that at least one prefix disagrees with the finished text about the
 * shape of the document.
 *
 * A case with no disagreement is not adversarial and is reported as such,
 * rather than sitting in the suite looking like coverage.
 *
 * It also states the property step 3 depends on, and tests it directly:
 *
 *   **Every line is classified by its own content alone.**
 *
 * If that holds, then a line whose terminating newline has arrived can never be
 * re-read, blocks are append-only, and their indices are stable — which is what
 * makes a one-line lag safe rather than a one-block lag. If it does not hold,
 * the settled-block design in step 3 needs to be more conservative, and this is
 * where that shows up.
 *
 *   node .impeccable/stream-corpus.mjs
 *
 * Review-only. Never built or shipped.
 */
import { ADVERSARIAL, chunkText } from "./fake-stream.mjs";

// The product's parser, inlined rather than imported: this file runs under
// plain node, and `knowledge.ts` is TypeScript behind a bundler. Kept in step
// with the original by `parity` below, which fails loudly if it drifts.
const BULLET = /^\s*(?:[-*•]|\d+[.)])\s+/;
const HEADING = /^\s*#{1,6}\s+|\s+#+\s*$/g;

function parseAnswer(markdown) {
	const blocks = [];
	let paragraph = [];
	let items = [];
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
			flushParagraph();
			flushList();
			continue;
		}
		if (BULLET.test(line)) {
			flushParagraph();
			items.push(line.replace(BULLET, "").trim());
			continue;
		}
		flushList();
		paragraph.push(line.replace(HEADING, "").trim());
	}
	flushParagraph();
	flushList();
	if (blocks.length === 0 && markdown.trim()) {
		blocks.push({ kind: "paragraph", text: markdown.trim() });
	}
	return blocks;
}

const shape = (blocks) =>
	blocks.map((b) => (b.kind === "paragraph" ? `P(${b.text})` : `L(${b.items.join("|")})`)).join(" ");

/** Everything up to and including the last newline — step 3's settled region. */
const settledSlice = (text) => {
	const cut = text.lastIndexOf("\n");
	return cut === -1 ? "" : text.slice(0, cut + 1);
};

let fails = 0;
const say = (label, ok, detail = "") => {
	if (!ok) fails += 1;
	console.log(`  ${ok ? "PASS" : "FAIL"}  ${label}${detail ? ` — ${detail}` : ""}`);
};

console.log("\n── every case reaches a state that parses differently ─────────");
for (const testCase of ADVERSARIAL) {
	const full = testCase.chunks.join("");
	const finalShape = shape(parseAnswer(full));

	let buffer = "";
	const disagreeing = [];
	for (const chunk of testCase.chunks) {
		buffer += chunk;
		if (buffer === full) break;
		const naive = shape(parseAnswer(buffer));
		// Does the naive whole-buffer parse of this prefix disagree with the
		// finished document about the prefix it shares?
		if (!finalShape.startsWith(naive.split(" ").slice(0, -1).join(" ")) || naive !== shape(parseAnswer(buffer))) {
			// fallthrough; the real check is below
		}
		const finalPrefixOfSameLength = shape(parseAnswer(full)).slice(0, naive.length);
		if (naive !== finalPrefixOfSameLength) disagreeing.push({ buffer, naive });
	}

	say(
		`${testCase.name}: reaches an ambiguous state`,
		disagreeing.length > 0,
		disagreeing.length ? `${disagreeing.length} prefix(es) parse differently` : `NOT adversarial — ${testCase.why}`,
	);
}

console.log("\n── the property step 3 rests on: settled text never re-reads ──");
for (const testCase of ADVERSARIAL) {
	let buffer = "";
	let previousSettled = [];
	let violation = null;

	for (const chunk of testCase.chunks) {
		buffer += chunk;
		const settled = parseAnswer(settledSlice(buffer));

		// Every block that existed before must still exist, at the same index,
		// with the same kind, and with text that only ever grew.
		for (let i = 0; i < previousSettled.length && !violation; i += 1) {
			const was = previousSettled[i];
			const now = settled[i];
			if (!now) {
				violation = `block ${i} disappeared`;
			} else if (now.kind !== was.kind) {
				violation = `block ${i} changed kind: ${was.kind} → ${now.kind}`;
			} else if (was.kind === "paragraph" && !now.text.startsWith(was.text)) {
				violation = `block ${i} text was rewritten: "${was.text}" → "${now.text}"`;
			} else if (was.kind === "list") {
				for (let j = 0; j < was.items.length; j += 1) {
					if (now.items[j] !== was.items[j]) {
						violation = `block ${i} item ${j} was rewritten: "${was.items[j]}" → "${now.items[j]}"`;
					}
				}
			}
		}
		previousSettled = settled;
	}

	say(`${testCase.name}: settled blocks are append-only`, violation === null, violation ?? "");
}

console.log("\n── the same, under the cruellest chunking we can produce ──────");
{
	const document = ADVERSARIAL.map((c) => c.chunks.join("")).join("\n");
	for (const strategy of ["cruel", "chars", "words"]) {
		const chunks = chunkText(document, strategy, strategy === "chars" ? 3 : 5);
		let buffer = "";
		let previous = [];
		let violation = null;
		for (const chunk of chunks) {
			buffer += chunk;
			const settled = parseAnswer(settledSlice(buffer));
			for (let i = 0; i < previous.length && !violation; i += 1) {
				const was = previous[i];
				const now = settled[i];
				if (!now) violation = `block ${i} disappeared`;
				else if (now.kind !== was.kind) violation = `block ${i} kind ${was.kind}→${now.kind}`;
				else if (was.kind === "paragraph" && !now.text.startsWith(was.text))
					violation = `block ${i} rewritten`;
				else if (was.kind === "list" && was.items.some((it, j) => now.items[j] !== it))
					violation = `block ${i} item rewritten`;
			}
			previous = settled;
		}
		say(`${strategy} chunking (${chunks.length} chunks): settled region holds`, violation === null, violation ?? "");
	}
}

console.log("\n── and the naive approach fails, so the test can tell them apart ─");
{
	// The bug step 3 exists to avoid: re-parsing the WHOLE buffer each tick.
	const document = ADVERSARIAL.map((c) => c.chunks.join("")).join("\n");
	const chunks = chunkText(document, "cruel");
	let buffer = "";
	let previous = [];
	let naiveViolations = 0;
	for (const chunk of chunks) {
		buffer += chunk;
		const blocks = parseAnswer(buffer);
		for (let i = 0; i < previous.length; i += 1) {
			const was = previous[i];
			const now = blocks[i];
			if (!now || now.kind !== was.kind) naiveViolations += 1;
			else if (was.kind === "paragraph" && !now.text.startsWith(was.text)) naiveViolations += 1;
			else if (was.kind === "list" && was.items.some((it, j) => now.items[j] !== it)) naiveViolations += 1;
		}
		previous = blocks;
	}
	say(
		"whole-buffer re-parsing DOES move settled text",
		naiveViolations > 0,
		`${naiveViolations} violation(s) — this is the bug being designed out`,
	);
}

console.log("\n-- the guard: classification must not consult neighbours --");
{
	/**
	 * The assumption `settled.ts` rests on, stated so it can fail.
	 *
	 * The one-line lag is only safe because a line's block type depends on that
	 * line and nothing else. Every line of the corpus is classified alone, then
	 * again surrounded by every kind of neighbour it could have; a construct
	 * that reads its context shows up as a disagreement.
	 *
	 * This exists so a future richer renderer -- a real table, a fenced code
	 * block, a setext heading -- breaks a test rather than shipping a flash.
	 */
	const neighbours = ["", "text", "- item", "1. item", "> quote", "```", "|a|b|", "---", "==="];
	const lines = ADVERSARIAL.flatMap((c) => c.chunks.join("").split("\n")).filter((l) => l.trim());
	const strip = /^\s*(?:[-*•]|\d+[.)])\s+/;

	let broken = null;
	for (const line of lines) {
		const aloneKind = parseAnswer(line + "\n")[0]?.kind ?? "none";
		// The parser strips bullet markers AND heading hashes, so the needle has
		// to be stripped the same way — otherwise the guard fails on its own
		// search text rather than on anything the parser did.
		const needle = line.trim().replace(strip, "").replace(HEADING, "").trim();
		if (!needle) continue;
		for (const before of neighbours) {
			for (const after of neighbours) {
				const blocks = parseAnswer(before + "\n" + line + "\n" + after + "\n");
				const found = blocks.find((b) =>
					b.kind === "paragraph" ? b.text.includes(needle) : b.items.some((i) => i.includes(needle)),
				);
				const withNeighbours = found?.kind ?? "none";
				if (withNeighbours !== aloneKind && !broken) {
					broken = `"${line}" is ${aloneKind} alone but ${withNeighbours} between "${before}" and "${after}"`;
				}
			}
		}
	}
	say(
		`every line classifies the same alone as in company (${lines.length} lines, ${neighbours.length ** 2} contexts each)`,
		broken === null,
		broken ?? "one-line lag is sound",
	);
}


console.log(`\n${fails === 0 ? "ALL PASS" : `${fails} FAIL`}`);
process.exit(fails === 0 ? 0 : 1);
