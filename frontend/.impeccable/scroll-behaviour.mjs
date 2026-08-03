/**
 * The scroll behaviours a virtualizer would have owned, asserted directly.
 *
 * `@tanstack/react-virtual` was a declared dependency that nothing ever
 * imported, so removing it changed no rendering code. That makes "it still
 * works" easy to claim and, until now, impossible to show: nothing in the
 * harness suite touched `.thread`'s scroll offset at all.
 *
 * These are the behaviours the message list actually relies on, all of them
 * hand-rolled against a native overflow container in `AspireChat.tsx`:
 *
 *   - a reply longer than the viewport leaves the thread at its newest content
 *   - a reader who has scrolled up to re-read is not yanked back down
 *   - leaving a conversation and coming back restores the offset
 *   - every paragraph of a long transcript is reachable
 *
 * The third is the one worth having. It is a ref keyed by thread, restored in
 * a layout effect, and it is exactly the kind of thing that survives a
 * refactor by accident and breaks by accident too — which matters immediately,
 * because the next workstream moves this component into a layout route.
 *
 *   node .impeccable/preview-server.mjs &
 *   node .impeccable/scroll-behaviour.mjs
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

let fails = 0;
const say = (label, ok, detail = "") => {
	if (!ok) fails += 1;
	console.log(`  ${ok ? "PASS" : "FAIL"}  ${label}${detail ? ` — ${detail}` : ""}`);
};

/**
 * A behaviour that is currently broken, deliberately not counted as a failure.
 *
 * Not a way of excusing it. The assertion runs, the measurement is printed, and
 * the moment the behaviour starts working this line says so and should be
 * turned back into `say`. What it avoids is a suite that is permanently red for
 * something the change under review did not cause, which is a suite people stop
 * reading.
 */
const known = (label, ok, detail = "", why = "") => {
	// It is a race, and it occasionally wins — measured at one pass in five. A
	// single green run is not evidence it is fixed, so neither verdict here is
	// allowed to read like one.
	console.log(`  ${ok ? "KNOWN (passed this run — it is a race)" : "KNOWN"}  ${label}${detail ? ` — ${detail}` : ""}`);
	if (why) console.log(`        ${why}`);
};

/**
 * Long enough that the thread genuinely overflows, and long enough that a
 * remembered offset is meaningfully different from either end. A reply that
 * fits on screen cannot fail any of these.
 */
const LONG = Array.from(
	{ length: 16 },
	(_, i) =>
		`Point ${i + 1}. Compound interest means the interest you earned last year earns interest of its own this year, which is why starting early matters more than the amount you start with.`,
).join("\n\n");

/** Short enough that its conversation does not overflow the viewport at all. */
const SHORT = "A bond is a loan you make to a company or a government.";

const browser = await puppeteer.launch({ headless: "new" });
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 800 });

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
			(body) => r.respond({ status: 200, contentType: "text/event-stream", headers: CORS, body }),
			(sent) => {
				const id = sent.thread_id || "t-server";
				// One question gets a short answer on purpose. See the switching
				// case below: two conversations of the same height cannot tell
				// restoration apart from a scroll container that simply was never
				// unmounted.
				const reply = /bond/i.test(sent.message ?? "") ? SHORT : LONG;
				store.openConversation(id, store.ownerOf(r), sent.message);
				store.recordTurn(id, null, sent.message, {
					role: "assistant",
					text: reply,
					sources: [],
					follow_ups: [],
				});
				return { reply };
			},
		);
		return;
	}
	if (r.url().includes("/api/")) return respond(404, {});
	r.continue();
});

/** The scrolling element, addressed exactly as the component names it. */
const metrics = () =>
	page.evaluate(() => {
		const el = document.querySelector(".thread");
		if (!el) return null;
		return {
			top: el.scrollTop,
			max: el.scrollHeight - el.clientHeight,
			height: el.scrollHeight,
			client: el.clientHeight,
			bottomGap: el.scrollHeight - el.scrollTop - el.clientHeight,
		};
	});

/** Set the offset the way a person does — the component listens for `scroll`. */
const scrollTo = (top) =>
	page.evaluate((v) => {
		const el = document.querySelector(".thread");
		if (!el) return;
		el.scrollTop = v === "middle" ? Math.round((el.scrollHeight - el.clientHeight) / 2) : v;
		el.dispatchEvent(new Event("scroll", { bubbles: true }));
	}, top);

async function ask(text) {
	await page.click("#aspire-composer");
	await page.type("#aspire-composer", text);
	await page.keyboard.press("Enter");
	await page.waitForFunction(() => !document.querySelector(".composer__send--stop"), { timeout: 40000 });
	// The typewriter keeps growing the thread after the request settles.
	await new Promise((r) => setTimeout(r, 1200));
}

await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });

// ─── a reply longer than the viewport ────────────────────────────────────────
console.log("\n── a reply longer than the viewport ──────────────────────────");
await ask("How does compound interest work?");

let m = await metrics();
say(
	"the thread genuinely overflows, so these are real assertions",
	m !== null && m.max > 80,
	m ? `${m.height}px of content in ${m.client}px` : "no .thread",
);
say(
	"and it is left at the newest content",
	m !== null && m.bottomGap < 8,
	m ? `${Math.round(m.bottomGap)}px from the bottom` : "",
);

const firstThread = page.url();

// ─── the reader scrolls up to re-read ────────────────────────────────────────
console.log("\n── the reader has scrolled up to re-read ─────────────────────");
await scrollTo(0);
await ask("What about index funds?");
m = await metrics();
say(
	"a new message does not yank them back down",
	m !== null && m.bottomGap > 150,
	m ? `${Math.round(m.bottomGap)}px from the bottom` : "",
);

/**
 * Opens a rail row by what it says, and refuses to continue until the URL is
 * the one expected.
 *
 * Both halves of that are load-bearing. Picking by position assumed the rail
 * was ordered newest-first; it is not, reliably, and a test that clicks the
 * wrong row still passes its next assertion for the wrong reason — which is
 * exactly what happened here before this was rewritten. And the row must be
 * found and clicked in the same evaluate: the rail re-renders when the
 * generated title replaces the provisional one, a second or two after the row
 * appears, and a click on a handle taken before that does nothing at all,
 * silently.
 */
const openRow = async (label, expected) => {
	const clicked = await page.evaluate((text) => {
		const node = [...document.querySelectorAll(".history-item")].find((n) =>
			(n.textContent ?? "").toLowerCase().includes(text.toLowerCase()),
		);
		node?.click();
		return Boolean(node);
	}, label);
	if (!clicked) throw new Error(`no rail row matching "${label}"`);
	await page.waitForFunction(
		(p) => window.location.pathname === p,
		{ timeout: 10000 },
		new URL(expected).pathname,
	);
};

// ─── leaving and coming back ─────────────────────────────────────────────────
//
// The other conversation is deliberately SHORT — short enough not to overflow.
//
// With two tall conversations this case passes without testing anything. The
// scroll container is one DOM node that is never unmounted when the route
// changes, so its offset survives on its own; blanking the `scrollTops` ref
// entirely, and even forcing the restore to jump to the bottom, both still
// "passed". A conversation that does not overflow forces the offset to 0 while
// it is open, so coming back to a remembered position is the only way to
// arrive anywhere but the top.
console.log("\n── leaving a conversation and coming back ────────────────────");
// Dispatched rather than clicked at a coordinate: the rail animates, and a
// hit-test that lands mid-transition reports the button as unclickable.
await page.evaluate(() => document.querySelector(".btn-new")?.click());
await page.waitForFunction(() => window.location.pathname === "/", { timeout: 10000 });
await new Promise((r) => setTimeout(r, 600));
await ask("What is a bond?");
const secondThread = page.url();

const rows = await page.$$(".history-item");
say("both conversations are in the rail", rows.length >= 2, `${rows.length} rows`);
const shortMetrics = await metrics();
say(
	"the other conversation is short enough not to scroll",
	shortMetrics !== null && shortMetrics.max < 8,
	shortMetrics ? `max ${shortMetrics.max}` : "no .thread",
);

// Park part-way up the TALL conversation, which means going back to it first.
await openRow("compound interest", firstThread);
await new Promise((r) => setTimeout(r, 700));
await scrollTo("middle");
await new Promise((r) => setTimeout(r, 350));
const parked = (await metrics()).top;
say("a position part-way up is parked", parked > 40, `scrollTop ${Math.round(parked)}`);


await openRow("bond", secondThread);
await new Promise((r) => setTimeout(r, 700));
const away = await metrics();
say(
	"the short conversation forces the container to the top",
	away !== null && away.top < 8,
	away ? `scrollTop ${Math.round(away.top)}` : "",
);

await openRow("compound interest", firstThread);
await new Promise((r) => setTimeout(r, 900));

// Both questions, not just the one it was opened with. The transcript cache is
// preferred over the rail's summary when reading a conversation back, and for a
// long time only the loader ever wrote it — so a conversation reopened with the
// turns it had when it was first cached and every later turn was silently gone.
const turns = await page.evaluate(() => document.querySelectorAll(".turn--user").length);
say("it reopens with every turn it had, not just the first", turns === 2, `${turns} questions`);

const reopened = (await metrics())?.top ?? -1;
say(
	"it reopens where it was left, not at the end",
	Math.abs(reopened - parked) < 24,
	`parked ${Math.round(parked)} → reopened ${Math.round(reopened)}`,
);

// ─── the whole transcript is reachable ───────────────────────────────────────
console.log("\n── every paragraph is reachable ──────────────────────────────");
const sweep = await page.evaluate(() => {
	const el = document.querySelector(".thread");
	if (!el) return null;
	const max = el.scrollHeight - el.clientHeight;
	const all = el.querySelectorAll(".answer p, .turn--user");
	const seen = new Set();
	const step = Math.max(40, Math.floor(el.clientHeight / 2));
	for (let t = 0; t <= max + step; t += step) {
		el.scrollTop = Math.min(t, max);
		for (const node of all) {
			const r = node.getBoundingClientRect();
			if (r.bottom > 0 && r.top < window.innerHeight) seen.add(node);
		}
	}
	return { seen: seen.size, total: all.length, reachedEnd: el.scrollTop === max, max };
});
say(
	"no paragraph is skipped over by scrolling",
	sweep !== null && sweep.seen === sweep.total,
	sweep ? `${sweep.seen}/${sweep.total}` : "no .thread",
);
say("and the container reaches its own end", sweep?.reachedEnd === true, `max ${sweep?.max}`);

console.log(`\n${fails === 0 ? "ALL PASS" : `${fails} FAIL`}`);
await browser.close();
process.exit(fails === 0 ? 0 : 1);
