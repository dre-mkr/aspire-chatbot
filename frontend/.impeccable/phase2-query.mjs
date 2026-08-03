/**
 * Phase 2: the Query boundary and the completion handoff.
 *
 * Four claims, each checked against the running app rather than the source:
 *
 *   1. No query holds a partial answer. The rule the whole refactor exists to
 *      enforce, so it is asserted against the live cache while a reply is
 *      mid-reveal — the one moment it could be violated.
 *   2. Gamification refreshes only after the turn has settled, never during it.
 *   3. The game card still outlives the server session. A finished game returns
 *      null from the endpoint, and the card must stay until it is dismissed.
 *      Query returning null must not take it off screen.
 *   4. The request pattern is not worse than the effects it replaced.
 *
 * The cache is read through the QueryClient the app actually uses, reached via
 * the router instance on `window`. Counting requests at the network layer is
 * what makes claim 2 falsifiable: an assertion about when a refetch happens has
 * to observe the wire, not the code.
 *
 *   node .impeccable/preview-server.mjs &
 *   node .impeccable/phase2-query.mjs
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";
import { handleChatStream } from "./fake-stream.mjs";


const BASE = process.argv[2] ?? "http://localhost:4173";
const CORS = {
	"Access-Control-Allow-Origin": "*",
	"Access-Control-Allow-Methods": "GET,POST,OPTIONS",
	"Access-Control-Allow-Headers": "Content-Type, Authorization, X-Aspire-Device",
};

const LONG = Array.from(
	{ length: 7 },
	(_, i) =>
		`Paragraph ${i + 1}. An index fund holds a little of every company on a list, so instead of betting on one name you own a slice of hundreds at once.`,
).join("\n\n");

const CARD = {
	game_type: "true_false",
	display_name: "True or false",
	prompt: { kind: "statement", text: "An index fund spreads risk.", position: 1, total: 5, choices: [] },
	supports_hints: false,
	hint_level: 0,
	max_hint_level: 0,
	hints: [],
	attempts: 0,
	solved: 0,
	skipped: 0,
	language: "en",
	persona: null,
};

let fails = 0;
const say = (label, ok, detail = "") => {
	if (!ok) fails += 1;
	console.log(`  ${ok ? "PASS" : "FAIL"}  ${label}${detail ? " — " + detail : ""}`);
};

const browser = await puppeteer.launch({ headless: "new" });

/**
 * `gamePlan` lets a test change what /api/games/state returns over time, which
 * is how "the session ended" is simulated: same endpoint, now answering null.
 */
async function open({ startGame = false, gamePlan = null } = {}) {
	const page = await browser.newPage();
	await page.setViewport({ width: 1280, height: 900 });
	const calls = { chat: 0, gameState: 0, eligState: 0, title: 0 };
	const marks = [];
	let gameCall = 0;

	await page.setRequestInterception(true);
	page.on("request", async (r) => {
		const u = r.url();
		if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });

		// `/chat/stream` is the transport now; `/chat` stays as the fallback.
		if (
			handleChatStream(r, (body) =>
				r.respond({ status: 200, contentType: "text/event-stream", headers: CORS, body }),
				(sent) => {
					// Same counters the `/chat` branch keeps, so assertions about
					// request ordering still describe the real sequence.
					calls.chat += 1;
					marks.push({ what: "chat", t: Date.now() });
					const startsGame = startGame && calls.chat === 1;
					return {
						reply: startsGame ? "" : LONG,
						gameStarted: startsGame
							? { game_type: "true_false", display_name: "True or false", kind: "statement", total: 5 }
							: null,
					};
				},
			)
		)
			return;

		if (u.endsWith("/chat")) {
			calls.chat += 1;
			marks.push({ what: "chat", t: Date.now() });
			const sent = JSON.parse(r.postData() || "{}");
			// Only the opening turn starts a game. Applying it to every turn made
			// the second question start a second game, which legitimately replaces
			// the card — and would have been read as the card being lost.
			const startsGame = startGame && calls.chat === 1;
			return r.respond({
				status: 200,
				contentType: "application/json",
				headers: CORS,
				body: JSON.stringify({
					reply: startsGame ? "" : LONG,
					thread_id: sent.thread_id || "t",
					sources: [],
					follow_ups: [],
					...(startsGame
						? { game_started: { game_type: "true_false", display_name: "True or false", kind: "statement", total: 5 } }
						: {}),
				}),
			});
		}

		if (u.includes("/api/games/state")) {
			calls.gameState += 1;
			marks.push({ what: "gameState", t: Date.now() });
			const active = gamePlan ? gamePlan(gameCall++) : startGame;
			return r.respond({
				status: 200,
				contentType: "application/json",
				headers: CORS,
				body: JSON.stringify({ active, game: active ? CARD : null }),
			});
		}

		if (u.includes("/api/eligibility/state")) {
			calls.eligState += 1;
			return r.respond({
				status: 200,
				contentType: "application/json",
				headers: CORS,
				body: JSON.stringify({ active: false, language: "en", question: null, result: null, answered: 0, total: 0, labels: {} }),
			});
		}

		if (u.endsWith("/api/title")) {
			calls.title += 1;
			return r.respond({ status: 200, contentType: "application/json", headers: CORS, body: '{"title":"Index funds"}' });
		}
		if (u.includes("/api/")) return r.respond({ status: 404, contentType: "application/json", headers: CORS, body: "{}" });
		r.continue();
	});

	await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await page.evaluate(() => localStorage.clear());
	await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	return { page, calls, marks };
}

/** Every cache entry, as the app's own QueryClient sees it. */
const cache = (page) =>
	page.evaluate(() => {
		// The router instance TanStack Start puts on the page; the QueryClient
		// lives in its context, which is where the app itself reads it from.
		const qc = window.__TSR_ROUTER__?.options?.context?.queryClient;
		if (!qc) return null;
		return qc
			.getQueryCache()
			.getAll()
			.map((q) => ({ key: q.queryKey, state: q.state.status, data: q.state.data }));
	});

const ask = async (page, text = "What is an index fund?") => {
	await page.click("#aspire-composer");
	await page.type("#aspire-composer", text);
	await page.keyboard.press("Enter");
};
const settled = (page) =>
	page.waitForFunction(() => !document.querySelector(".composer__send--stop"), { timeout: 25000, polling: 50 });

// ─── 1. No query holds a partial answer, checked mid-reveal ──────────────────
console.log("\n── no query function returns partial or streaming data ─");
{
	const { page } = await open();
	await ask(page);
	// Mid-reveal: the one moment a leak could exist.
	await page.waitForFunction(
		() => document.querySelectorAll('.transcript [aria-busy="true"] .answer > p').length >= 2,
		{ timeout: 20000, polling: 40 },
	);
	const mid = await cache(page);
	if (mid === null) {
		say("the app's QueryClient is reachable for inspection", false, "not exposed");
	} else {
		const asString = JSON.stringify(mid);
		const revealed = await page.evaluate(
			() => document.querySelector('.transcript [aria-busy="true"] .answer > p')?.textContent?.slice(0, 40) ?? "",
		);
		say("a reply is genuinely mid-reveal at this moment", revealed.length > 10, `"${revealed.slice(0, 30)}…"`);
		say(
			"no cache entry contains the text being revealed",
			revealed.length > 10 && !asString.includes(revealed.slice(0, 30)),
		);
		const keys = mid.map((e) => JSON.stringify(e.key));
		say("cache holds only server resources", keys.every((k) => /games|eligibility|conversations/.test(k)), keys.join(" "));
		// The reveal must not be writing to the cache on every tick.
		//
		// Checked as "no cache entry ever contains the answer" rather than "the
		// cache is byte-identical". Now that the reveal starts with the first
		// token instead of after the whole reply, ordinary server state — the
		// conversation list loading, the turn's own invalidation — legitimately
		// lands while text is still arriving. The rule was never "the cache is
		// frozen during a reveal"; it is that the reveal is not in it.
		await new Promise((r) => setTimeout(r, 300));
		const later = await cache(page);
		const leaked = JSON.stringify(later).includes(revealed.slice(0, 30));
		say("no cache entry holds the answer while tokens arrive", !leaked);
		say(
			"and nothing streaming-shaped appears as a new key",
			later.every((e) => /games|eligibility|conversations/.test(JSON.stringify(e.key))),
			later.map((e) => JSON.stringify(e.key)).join(" "),
		);
	}
	await page.close();
}

// ─── 2. Gamification refreshes only after completion ─────────────────────────
console.log("\n── gamification refreshes only on settled turns ───────");
{
	const { page, calls, marks } = await open();
	await ask(page);
	await page.waitForFunction(
		() => document.querySelectorAll('.transcript [aria-busy="true"] .answer > p').length >= 2,
		{ timeout: 20000, polling: 40 },
	);
	const duringReveal = calls.gameState;
	await settled(page);
	await new Promise((r) => setTimeout(r, 900));
	const afterSettle = calls.gameState;

	say("no game-state request is made while the reply is revealing", duringReveal === 0, `${duringReveal} during`);
	say("exactly one is made once the turn settles", afterSettle - duringReveal === 1, `${afterSettle - duringReveal} after`);
	// Ordering, from the wire: the refresh follows the reply, never precedes it.
	const order = marks.map((m) => m.what).join(" → ");
	say("the refresh follows the reply", /chat → gameState/.test(order), order);

	// Idle must not poll. The old effect did not, and Query's defaults would.
	await new Promise((r) => setTimeout(r, 1500));
	say("sitting idle triggers no further requests", calls.gameState === afterSettle, `${calls.gameState} total`);
	await page.close();
}

// ─── 3. The finished game's card outlives the server session ────────────────
console.log("\n── a finished game keeps its card ────────────────────");
{
	// First state call says the game is running; every later one says it is over.
	const { page } = await open({ startGame: true, gamePlan: (n) => n === 0 });
	await ask(page, "Can we play true or false?");
	await page.waitForSelector(".game", { timeout: 20000 });
	say("the card appears when the game starts", true);

	// A second turn settles, which invalidates and refetches — now returning null.
	await settled(page);
	await ask(page, "Thanks!");
	await settled(page);
	await new Promise((r) => setTimeout(r, 1200));

	const stillThere = await page.evaluate(() => !!document.querySelector(".game"));
	const cached = await cache(page);
	// The disabled query registers a key with an empty thread id too, so match on
	// the entry that actually names this conversation.
	const gameEntry = cached?.find((e) => e.key[0] === "games" && e.key[2]);
	say("the server now reports no session", gameEntry?.data === null, JSON.stringify(gameEntry?.data));
	say("but the card is still on screen", stillThere);
	await page.close();
}

// ─── 4. Request volume is no worse than the effects it replaced ─────────────
console.log("\n── request pattern ──────────────────────────────────");
{
	const { page, calls } = await open();
	await ask(page);
	await settled(page);
	await new Promise((r) => setTimeout(r, 800));
	await ask(page, "And bonds?");
	await settled(page);
	await new Promise((r) => setTimeout(r, 1200));
	// Two turns, two refreshes. The effects this replaced fired on
	// [threadId, messages.length, settled] and produced the same count.
	say("two turns produce two game-state reads", calls.gameState === 2, `${calls.gameState}`);
	say("two turns produce two eligibility reads", calls.eligState === 2, `${calls.eligState}`);
	await page.close();
}

console.log(`\n${fails === 0 ? "ALL PASS" : `${fails} FAIL`}`);
await browser.close();
process.exit(fails === 0 ? 0 : 1);
