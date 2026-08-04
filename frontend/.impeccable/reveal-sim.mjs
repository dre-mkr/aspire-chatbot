/**
 * What the reveal actually does, tick by tick, without a browser.
 *
 * The browser harness (`live-drain.mjs`) proves that nothing already on screen
 * ever moves. It does not measure the property the reveal is *for*: that words
 * keep arriving at a steady rate. This does, by replaying the real tick loop
 * over a chunk schedule with real timestamps and recording the visible text at
 * every tick.
 *
 *   node .impeccable/reveal-sim.mjs
 *
 * Review-only. Never built or shipped.
 */
import { blockIsClosed, settledBlocks } from "../src/lib/aspire/settled.ts";
import { parseAnswer } from "../src/lib/aspire/knowledge.ts";

const TICK_MS = 40;
const SMOOTH_TICKS = 8;
const MIN_RATE = 0.3;
const MAX_RATE = 5;
const MIN_RATE_ENDED = 2.5;
const MAX_RATE_ENDED = 8;

const blockWords = (b) =>
	b.kind === "paragraph"
		? b.text
			? b.text.split(" ").length
			: 0
		: b.items.reduce((n, i) => n + (i ? i.split(" ").length : 0), 0);

function sliceBlock(block, words) {
	if (block.kind === "paragraph") {
		return { kind: "paragraph", text: block.text.split(" ").slice(0, words).join(" ") };
	}
	const items = [];
	let left = words;
	for (const item of block.items) {
		if (left <= 0) break;
		const parts = item.split(" ");
		items.push(left >= parts.length ? item : parts.slice(0, left).join(" "));
		left -= parts.length;
	}
	return { kind: "list", items };
}

const paceFor = (pending, ended) => {
	const rate = pending / SMOOTH_TICKS;
	return ended
		? Math.min(MAX_RATE_ENDED, Math.max(MIN_RATE_ENDED, rate))
		: Math.min(MAX_RATE, Math.max(MIN_RATE, rate));
};

function pendingWords(state) {
	let total = -state.wordIndex;
	for (let i = state.blockIndex; i < state.answer.blocks.length; i += 1) {
		total += blockWords(state.answer.blocks[i]);
	}
	return Math.max(0, total);
}

/** The answer from the recording, verbatim. */
export const REPLY = [
	"**A portion of each ASPIRE contribution is invested in shares of local, government-owned entities**, including:",
	"",
	"- St. Kitts-Nevis-Anguilla National Bank",
	"- St. Kitts-Nevis Cable Communications Ltd, known as The Cable",
	"",
	"The ASPIRE Council and financial managers oversee the investment strategy. Dividends—payments made from investments—are reinvested to support long-term growth.",
	"",
	"Investment values can change. Participants receive quarterly statements to keep them informed. This information was last checked on 30 July 2026.",
].join("\n");

/** Splits text into model-sized tokens (~4 chars), which is how it arrives. */
export function tokenize(text, size = 4) {
	const out = [];
	for (let i = 0; i < text.length; i += size) out.push(text.slice(i, i + size));
	return out;
}

const textOf = (blocks) =>
	blocks
		.map((b) => (b.kind === "paragraph" ? b.text : b.items.join("\n")))
		.join("\n");

/**
 * Replays one turn and returns a sample per tick.
 *
 * `tokensPerSecond` paces arrival; the loop is driven by a virtual clock so a
 * 30-second answer is measured in milliseconds.
 */
export function simulate({ reply = REPLY, tokensPerSecond = 45, tokenSize = 4 } = {}) {
	const tokens = tokenize(reply, tokenSize);
	const arrivalMs = 1000 / tokensPerSecond;

	let buffer = "";
	let cursor = null;
	let next = 0;
	const samples = [];
	let settledAt = null;

	for (let t = 0; t < 120000; t += TICK_MS) {
		// Deliver every token whose time has come.
		while (next < tokens.length && next * arrivalMs <= t) {
			buffer += tokens[next];
			next += 1;
			const blocks = settledBlocks(buffer, false);
			if (!cursor) {
				if (blocks.length > 0) {
					cursor = {
						answer: { blocks },
						blockIndex: 0,
						wordIndex: 0,
						credit: 0,
						built: [],
						ended: false,
					};
				}
			} else {
				cursor.answer = { ...cursor.answer, blocks };
			}
		}
		// The turn ends: the payload is authoritative and `ended` flips.
		if (next >= tokens.length && cursor && !cursor.ended) {
			cursor.answer = { blocks: parseAnswer(reply) };
			cursor.ended = true;
		}

		if (cursor) {
			const state = cursor;
			const pending = pendingWords(state);
			if (pending === 0 && state.ended) {
				// finishStream: the whole answer joins the transcript. With the
				// controller draining to zero first, this should change nothing.
				samples.push({ t, text: textOf(state.answer.blocks), done: true });
				settledAt = t;
				break;
			}
			if (pending > 0) {
				state.credit += paceFor(pending, state.ended);
				const budget = Math.floor(state.credit);
				if (budget >= 1) {
					state.credit -= budget;
					let left = budget;
					while (left > 0) {
						const block = state.answer.blocks[state.blockIndex];
						if (!block) break;
						const total = blockWords(block);
						const take = Math.min(left, total - state.wordIndex);
						if (take > 0) {
							state.wordIndex += take;
							left -= take;
							state.built[state.blockIndex] = sliceBlock(block, state.wordIndex);
						}
						if (state.wordIndex < total) break;
						if (!blockIsClosed(state.blockIndex, state.answer.blocks, state.ended)) break;
						state.blockIndex += 1;
						state.wordIndex = 0;
					}
				}
			}
			samples.push({ t, text: textOf(state.built.filter(Boolean)), done: false });
		} else {
			samples.push({ t, text: "", done: false });
		}
	}

	return { samples, settledAt, arrivalEndMs: tokens.length * arrivalMs };
}

/**
 * How long a screen may sit unchanged before a reader calls it stuck.
 *
 * Not a round number pulled from nowhere: below roughly a quarter-second a gap
 * reads as the space between words, and past about half a second it reads as
 * the thing having stopped. 400ms is the conservative side of that line.
 *
 * The distinction matters for judging this harness's output. At 25 tokens a
 * second the model produces about one word every 55ms, so a correct reveal
 * MUST show gaps of that order — it cannot draw words that do not exist yet.
 * Counting those as stalls would be counting the model's speed as a bug.
 */
const STALL_MS = 400;

/** Turns a sample series into the numbers that describe how it felt. */
export function report(samples) {
	const firstWord = samples.find((s) => s.text.length > 0);
	const gaps = [];
	let runStart = null;
	for (let i = 1; i < samples.length; i += 1) {
		const grew = samples[i].text.length > samples[i - 1].text.length;
		if (!grew && samples[i - 1].text.length > 0) {
			if (runStart === null) runStart = samples[i - 1].t;
		} else if (runStart !== null) {
			gaps.push({ from: runStart, ms: samples[i].t - runStart });
			runStart = null;
		}
	}
	const last = samples[samples.length - 1];
	const beforeLast = samples[samples.length - 2];

	// Nothing on screen may ever be un-shown or rewritten.
	let rewrite = null;
	for (let i = 1; i < samples.length && !rewrite; i += 1) {
		if (!samples[i].text.startsWith(samples[i - 1].text)) {
			rewrite = `at t=${samples[i].t}ms: "...${samples[i - 1].text.slice(-30)}" → "...${samples[i].text.slice(-30)}"`;
		}
	}

	return {
		firstWordMs: firstWord ? firstWord.t : null,
		endMs: last?.t ?? null,
		worstGapMs: gaps.reduce((m, g) => Math.max(m, g.ms), 0),
		stalls: gaps.filter((g) => g.ms >= STALL_MS).sort((a, b) => b.ms - a.ms),
		snapChars: last?.done ? last.text.length - (beforeLast?.text.length ?? 0) : 0,
		finalText: last?.text ?? "",
		rewrite,
	};
}

if (import.meta.url.endsWith(process.argv[1].replace(/\\/g, "/"))) {
	const expected = textOf(parseAnswer(REPLY));
	let fails = 0;
	const say = (label, ok, detail = "") => {
		if (!ok) fails += 1;
		console.log(`  ${ok ? "PASS" : "FAIL"}  ${label}${detail ? ` — ${detail}` : ""}`);
	};

	for (const tps of [15, 25, 45, 80]) {
		const { samples, arrivalEndMs } = simulate({ tokensPerSecond: tps });
		const r = report(samples);
		console.log(`\n── ${tps} tokens/s (the wire finishes at ${Math.round(arrivalEndMs)}ms) ──`);
		console.log(`     first word at ${r.firstWordMs}ms · finished at ${r.endMs}ms · worst gap ${r.worstGapMs}ms`);
		say("the first word arrives within 400ms", r.firstWordMs !== null && r.firstWordMs <= 400, `${r.firstWordMs}ms`);
		say(`no gap reaches ${STALL_MS}ms`, r.stalls.length === 0, r.stalls.map((s) => `${s.ms}ms at ${s.from}ms`).join(", "));
		say("nothing appears in one frame at the end", r.snapChars === 0, `${r.snapChars} characters`);
		say("nothing already shown is ever rewritten", r.rewrite === null, r.rewrite ?? "");
		say("the finished reveal is the whole answer", r.finalText === expected,
			r.finalText === expected ? `${r.finalText.length} characters` : `${r.finalText.length} vs ${expected.length}`);
	}

	console.log(`\n${fails === 0 ? "ALL PASS" : `${fails} FAIL`}`);
	process.exit(fails === 0 ? 0 : 1);
}
