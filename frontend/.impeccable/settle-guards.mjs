/**
 * The settling rule's own claims, run against the adversarial corpus.
 *
 * `settled.ts` releases text before its line is finished, which is only safe
 * because of two properties it asserts about itself:
 *
 *   `assertPrefixLocal`  — the moment a line is shown, its kind is already final
 *   `assertAppendOnly`   — what is shown only ever grows
 *
 * This runs both against the real parser and the real settling rule, over every
 * growth sequence in the corpus and over answers shaped like the ones the
 * service actually returns. These are the cases that made revealed text move
 * before there was a rule at all, so they are the ones that have to pass now.
 *
 *   node --import ./.impeccable/ts-resolve.mjs .impeccable/settle-guards.mjs
 *
 * Review-only. Never built or shipped.
 */
import { assertAppendOnly, assertPrefixLocal, settledText } from "../src/lib/aspire/settled.ts";
import { parseAnswer } from "../src/lib/aspire/knowledge.ts";
import { ADVERSARIAL } from "./fake-stream.mjs";
import { REPLY } from "./reveal-sim.mjs";

let fails = 0;
const say = (label, ok, detail = "") => {
	if (!ok) fails += 1;
	console.log(`  ${ok ? "PASS" : "FAIL"}  ${label}${detail ? ` — ${detail}` : ""}`);
};

const TEXTS = [
	["the recorded answer", REPLY],
	...ADVERSARIAL.map((c) => [c.name, c.chunks.join("")]),
	[
		"prose that keeps growing a paragraph",
		"Compound interest is the effect of earning returns on your returns.\nIt is why starting early matters more than starting big.\nEven small amounts add up.",
	],
	["a hyphen inside a word", "Long-term saving beats short-term guessing.\n"],
	["a number that is not a list", "1.5 million people are enrolled.\nThat is a lot.\n"],
	["bold at the start of a line", "**Key point**: start early.\nIt matters.\n"],
	["a link arriving in pieces", "Visit [the site](https://aspire.gov.kn/) to apply.\n"],
];

console.log("\n── a line's kind is final the moment it is shown ──────────────");
for (const [name, text] of TEXTS) {
	const problem = assertPrefixLocal(text.split("\n"));
	say(name, problem === null, problem ?? "");
}

console.log("\n── what is shown only ever grows ─────────────────────────────");
for (const [name, text] of TEXTS) {
	const problem = assertAppendOnly(text);
	say(name, problem === null, problem ?? "");
}

console.log("\n── the settled prefix always parses to a prefix of the whole ──");
for (const [name, text] of TEXTS) {
	// The stronger, end-to-end statement: at every point in the stream, the
	// blocks the reader can see are a prefix-wise subset of the finished ones.
	const whole = parseAnswer(text);
	let problem = null;
	for (let cut = 1; cut <= text.length && !problem; cut += 1) {
		const blocks = parseAnswer(settledText(text.slice(0, cut), false));
		if (blocks.length > whole.length) {
			problem = `${blocks.length} blocks shown but the answer only has ${whole.length}`;
			break;
		}
		for (let i = 0; i < blocks.length; i += 1) {
			const shown = blocks[i];
			const final = whole[i];
			if (!final || shown.kind !== final.kind) {
				problem = `block ${i} is ${shown.kind} at ${cut} characters but ${final?.kind ?? "absent"} in the answer`;
				break;
			}
			if (shown.kind === "paragraph") {
				if (!final.text.startsWith(shown.text)) {
					problem = `block ${i} shows "${shown.text.slice(-40)}" which the answer does not begin with`;
					break;
				}
			} else {
				if (shown.items.length > final.items.length) {
					problem = `block ${i} shows ${shown.items.length} items; the answer has ${final.items.length}`;
					break;
				}
				for (let j = 0; j < shown.items.length; j += 1) {
					if (!final.items[j].startsWith(shown.items[j])) {
						problem = `block ${i} item ${j} shows "${shown.items[j]}" which "${final.items[j]}" does not begin with`;
						break;
					}
				}
			}
		}
	}
	say(name, problem === null, problem ?? "");
}

console.log(`\n${fails === 0 ? "ALL PASS" : `${fails} FAIL`}`);
process.exit(fails === 0 ? 0 : 1);
