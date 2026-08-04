/**
 * What a long conversation costs, measured rather than argued.
 *
 * P5-001 and P5-003 were measured findings with no harness behind them — the
 * numbers were taken by hand and could not be re-taken. This is that
 * measurement made repeatable, so "virtualization helped" is a diff in a table
 * rather than a claim.
 *
 * Three things, at four conversation lengths:
 *
 *   long tasks   the >50ms budget breach. Measured across a turn arriving,
 *                because that is when the list re-commits (P5-001).
 *   DOM nodes    scaled linearly at ~17/turn before windowing (P5-003).
 *   JS heap      6.3MB → 68.9MB across the same range, all retained.
 *
 * The transcript renders whole below `VIRTUALIZE_ABOVE` (60) and windows above
 * it, so 20 and 50 are the unwindowed control and 200 and 500 are the cases the
 * change is for. A flat node count across the last two is the whole point.
 *
 *   node .impeccable/preview-server.mjs &
 *   node .impeccable/transcript-scale.mjs
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";
import { createConversationStore } from "./fake-conversations.mjs";
import { handleChatStream } from "./fake-stream.mjs";

const BASE = process.argv[2] ?? "http://localhost:4173";
const CORS = {
	"Access-Control-Allow-Origin": "*",
	"Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
	"Access-Control-Allow-Headers": "Content-Type, Authorization, X-Aspire-Device",
};

/** Long enough that a turn is a realistic height, not a one-liner. */
const ANSWER = [
	"Compound interest means the interest you earned last year earns interest of its own this year.",
	"",
	"- Start early, because time does more work than the amount does",
	"- Keep the money where it compounds rather than where it sits",
	"- Add to it on a schedule, even when the amount is small",
	"",
	"That is why starting early matters more than the amount you start with.",
].join("\n");

const LENGTHS = [20, 50, 200, 500];

const browser = await puppeteer.launch({ headless: "new" });
const rows = [];

for (const turns of LENGTHS) {
	// Its own browser context, not just its own page. The session token lives in
	// this origin's storage, so a second page in the same context signs in as the
	// first one did — and the fresh store below has never issued that token, so
	// every seeded conversation belongs to nobody and the transcript is empty.
	const context = await browser.createBrowserContext();
	const page = await context.newPage();
	await page.setViewport({ width: 1280, height: 800 });
	page.on("pageerror", (e) => console.log(`  [${turns}] pageerror`, String(e).slice(0, 200)));

	const store = createConversationStore();
	await page.setRequestInterception(true);
	page.on("request", async (r) => {
		if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
		const respond = (status, body) =>
			r.respond({
				status,
				contentType: "application/json",
				headers: CORS,
				body: body === null ? "" : JSON.stringify(body),
			});
		if (await store.handle(r, respond)) return;
		if (r.url().endsWith("/chat/stream")) {
			handleChatStream(
				r,
				(body) =>
					r.respond({ status: 200, contentType: "text/event-stream", headers: CORS, body }),
				(sent) => {
					const id = sent.thread_id || "t-scale";
					store.openConversation(id, store.ownerOf(r), sent.message);
					store.recordTurn(id, null, sent.message, {
						role: "assistant",
						text: ANSWER,
						sources: [],
						follow_ups: [],
					});
					return { reply: ANSWER };
				},
			);
			return;
		}
		if (r.url().includes("/api/")) return respond(404, {});
		r.continue();
	});

	// One real turn, to establish the session and let the store own a
	// conversation the way the service would. The store enforces ownership
	// exactly as the service does, so a row conjured out of nothing is invisible.
	await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await page.click("#aspire-composer");
	await page.type("#aspire-composer", "How does compound interest work?");
	await page.keyboard.press("Enter");
	await page.waitForFunction(() => !document.querySelector(".composer__send--stop"), {
		timeout: 40000,
	});
	await new Promise((done) => setTimeout(done, 1200));

	// The rest is appended straight onto the row. Driving 500 turns through the
	// typewriter would measure the harness's patience, not the transcript.
	const threadId = new URL(page.url()).pathname.split("/").pop();
	const row = store.rows.get(threadId);
	if (!row) throw new Error(`the first turn did not create a row (${threadId})`);
	for (let i = row.messages.length; i < turns; i += 2) {
		row.messages.push({ role: "user", text: `Question ${i}. Tell me more about saving.` });
		row.messages.push({ role: "assistant", text: ANSWER, sources: [], follow_ups: [] });
	}

	console.log(`  [${turns}] seeded ${row.messages.length}, opening ${threadId}`);
	await page.goto(`${BASE}/chat/${threadId}`, { waitUntil: "networkidle0" });
	// `.transcript` exists from the first frame — it holds the live region even
	// when there is nothing in it — so waiting for the element measures nothing.
	// Wait for turns to actually be in it.
	await page.waitForFunction(
		() => document.querySelectorAll(".transcript .turn").length > 0,
		{ timeout: 30000 },
	);
	// Scroll to the end, which is what a reader does and what forces the windowed
	// list to measure and release rows.
	await page.evaluate(() => {
		const el = document.querySelector(".thread");
		if (el) el.scrollTop = el.scrollHeight;
	});
	await new Promise((done) => setTimeout(done, 800));

	// Observe from here, then send a turn into the conversation. P5-001 measured
	// long tasks "during a reveal" and that is the case worth measuring: the list
	// re-commits twice per turn, so the cost is paid against however many turns
	// are already in it.
	await page.evaluate(() => {
		window.__long = [];
		new PerformanceObserver((list) => {
			for (const entry of list.getEntries()) window.__long.push(Math.round(entry.duration));
		}).observe({ entryTypes: ["longtask"] });
	});
	await page.click("#aspire-composer");
	await page.type("#aspire-composer", "And what about index funds?");
	await page.keyboard.press("Enter");
	await page.waitForFunction(() => !document.querySelector(".composer__send--stop"), {
		timeout: 40000,
	});
	await new Promise((done) => setTimeout(done, 1200));

	const measured = await page.evaluate(() => ({
		nodes: document.querySelectorAll(".transcript *").length,
		turnsInDom: document.querySelectorAll(".transcript .turn").length,
		windowed: Boolean(document.querySelector(".transcript__window")),
		longest: Math.max(0, ...(window.__long ?? [])),
		over50: (window.__long ?? []).filter((d) => d > 50).length,
	}));
	const heap = await page.evaluate(() => performance.memory?.usedJSHeapSize ?? 0);

	rows.push({ turns, ...measured, heapMB: +(heap / 1048576).toFixed(1) });
	await context.close();
}

console.log("\n  turns  windowed  turns-in-DOM  DOM nodes  longest task  >50ms  heap");
console.log("  ─────  ────────  ────────────  ─────────  ────────────  ─────  ──────");
for (const r of rows) {
	console.log(
		`  ${String(r.turns).padStart(5)}  ${String(r.windowed).padStart(8)}  ` +
			`${String(r.turnsInDom).padStart(12)}  ${String(r.nodes).padStart(9)}  ` +
			`${String(`${r.longest}ms`).padStart(12)}  ${String(r.over50).padStart(5)}  ${r.heapMB}MB`,
	);
}

// The claim, as a check rather than a reading. Below the threshold every turn is
// in the DOM; above it the count stops tracking the conversation's length.
const big = rows.filter((r) => r.windowed);
const bounded =
	big.length >= 2 && big[big.length - 1].turnsInDom <= big[0].turnsInDom * 1.5;
console.log(
	`\n  ${bounded ? "PASS" : "FAIL"}  DOM stops growing with the conversation once windowed`,
);
console.log(
	`  ${rows.every((r) => r.over50 === 0) ? "PASS" : "FAIL"}  no long task over 50ms at any length`,
);

await browser.close();
process.exit(bounded ? 0 : 1);
