/**
 * How long the answer sits finished before its furniture arrives.
 *
 * The sources chip, the copy / Play / Ask again row and the follow-up chips are
 * not part of the reveal — they appear when the turn *settles*. That used to be
 * when the whole run finished, and the run does not finish when the answer does:
 * the follow-up chips are a second model call, so it stayed open for seconds
 * afterwards. The reader watched a complete answer sit there looking unfinished.
 *
 * Everything except the chips has been known since the last token, so everything
 * except the chips is measured here against the end of the reveal.
 *
 *   node .impeccable/preview-server.mjs &
 *   ASPIRE_API_PORT=8123 node .impeccable/settle-latency.mjs
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";
import { chunkText, startSseServer } from "./fake-stream.mjs";

const BASE = process.argv[2] ?? "http://localhost:4173";
const PORT = Number(process.env.ASPIRE_API_PORT ?? 8123);

/**
 * How long the service spends writing chips after announcing the turn.
 *
 * Measured against the running backend at two to five seconds. The whole point
 * of the split is that this number stops mattering to anything but the chips,
 * so the stub uses a deliberately cruel one.
 */
const CHIPS_MS = 3000;

const REPLY = [
	"ASPIRE participation lasts **at least five years or until the participant turns 18, whichever is later**.",
	"",
	"- Savings and investment returns unlock at the end",
	"- A certificate of completion is issued",
	"",
	"This means participation may continue beyond age 18 if the five-year minimum has not yet been completed.",
].join("\n");

/**
 * `ASPIRE_LIVE=1` points the harness at whatever the build points at.
 *
 * The stub is the instrument -- reproducible, and cruel about the chip delay in
 * a way the real service is only sometimes. The live run is the acceptance:
 * real retrieval, a real second model call, real timing.
 */
const LIVE = !!process.env.ASPIRE_LIVE;
const QUESTION = process.argv[3] ?? "How long does ASPIRE participation last?";

const server = LIVE ? null : await startSseServer({ port: PORT });
if (server) {
server.state.chunks = chunkText(REPLY, "words", 3);
server.state.gap = 45;
server.state.tailGap = CHIPS_MS;
server.state.done = {
	reply: REPLY,
	thread_id: "t",
	// `Source` is `{ content, metadata }` — the shape `/chat` actually returns.
	// A fixture shaped like a link crashes `Sources` on `metadata.question`.
	sources: [
		{
			content: "Participation runs for at least five years, or until the participant turns 18.",
			metadata: { question: "How long does participation last?", category: "Rules" },
		},
		{
			content: "Savings and investment returns unlock at the end of the programme.",
			metadata: { question: "When do savings unlock?", category: "Savings" },
		},
	],
	follow_ups: ["Who is eligible?", "How do I apply?"],
	game_started: null,
	eligibility_started: null,
};
}

const browser = await puppeteer.launch({ headless: "new" });
const p = await browser.newPage();
await p.setViewport({ width: 1280, height: 900 });
await p.goto(`${BASE}/`, { waitUntil: "networkidle2" });
await p.evaluate(() => localStorage.clear());
await p.goto(`${BASE}/`, { waitUntil: "networkidle2" });

// One sample per animation frame: what the answer said, and which of its
// trimmings had appeared by then.
await p.evaluate(() => {
	window.__s = [];
	const read = () => {
		const turn = [...document.querySelectorAll(".transcript .turn--assistant")].pop();
		const answer = turn?.querySelector(".answer");
		const text = [...(answer?.children ?? [])]
			.filter((el) => el.tagName === "P" || el.tagName === "UL" || el.tagName === "OL")
			.map((el) => el.textContent)
			.join("\n");
		window.__s.push({
			t: performance.now(),
			chars: text.length,
			// Both are laid out during the reveal and revealed in place, so their
			// presence says nothing. `data-pending` is what the reader can see: it
			// is on `.answer__tail` -- which wraps both -- for exactly as long as
			// the answer is still arriving.
			sources: !!turn?.querySelector(".answer__tail:not([data-pending]) .sources"),
			actions: !!turn?.querySelector(".answer__tail:not([data-pending]) .answer-actions"),
			chips: document.querySelectorAll(".follow-ups:not([data-pending]) .follow-up").length > 0,
		});
		window.__raf = requestAnimationFrame(read);
	};
	read();
});

await p.click("#aspire-composer");
await p.type("#aspire-composer", QUESTION);
await p.keyboard.press("Enter");
const sentAt = await p.evaluate(() => performance.now());

await p.waitForFunction(
	() => document.querySelectorAll(".follow-ups:not([data-pending]) .follow-up").length > 0,
	{ timeout: LIVE ? 120000 : 60000, polling: 32 },
);
await new Promise((r) => setTimeout(r, 400));

const all = await p.evaluate(() => {
	cancelAnimationFrame(window.__raf);
	return window.__s;
});
// Only this turn. The recorder starts at page load, and anything it saw
// before the question was asked belongs to a different turn or to none.
const samples = all.filter((s) => s.t >= sentAt);

const at = (pred) => samples.find(pred)?.t ?? null;
// The reveal is done when the character count stops growing.
const finalChars = samples[samples.length - 1].chars;
const answerDone = at((s) => s.chars === finalChars);
const firstText = at((s) => s.chars > 0);
const sourcesAt = at((s) => s.sources);
const actionsAt = at((s) => s.actions);
const chipsAt = at((s) => s.chips);

let fails = 0;
const say = (label, ok, detail = "") => {
	if (!ok) fails += 1;
	console.log(`  ${ok ? "PASS" : "FAIL"}  ${label}${detail ? ` — ${detail}` : ""}`);
};

console.log(
	LIVE
		? "\n── the answer's furniture, against the running service ──"
		: `\n── the answer's furniture, against a stub that takes ${CHIPS_MS}ms over its chips ──`,
);
console.log(`     first word            +0ms`);
console.log(`     answer complete       +${Math.round(answerDone - firstText)}ms`);
console.log(`     sources chip          +${Math.round(sourcesAt - firstText)}ms`);
console.log(`     copy / Ask again row  +${Math.round(actionsAt - firstText)}ms`);
console.log(`     follow-up chips       +${Math.round(chipsAt - firstText)}ms\n`);

say(
	"the sources chip does not wait for the follow-ups",
	sourcesAt - answerDone < 400,
	`${Math.round(sourcesAt - answerDone)}ms after the answer finished`,
);
say(
	"the action row does not wait for the follow-ups",
	actionsAt - answerDone < 400,
	`${Math.round(actionsAt - answerDone)}ms after the answer finished`,
);
say(
	"the chips still arrive, once they exist",
	chipsAt !== null && chipsAt > sourcesAt,
	`${Math.round(chipsAt - answerDone)}ms after the answer finished`,
);

console.log(`\n${fails === 0 ? "ALL PASS" : `${fails} FAIL`}`);
await browser.close();
server?.server.close();
process.exit(fails === 0 ? 0 : 1);
