/**
 * The New chat lifecycle: the 13 acceptance tests, run against the production
 * preview.
 *
 *   node .impeccable/preview-server.mjs &
 *   node .impeccable/newchat.mjs
 *
 * The backend is stubbed, deliberately. Every assertion here is about the
 * client — when a chat is committed, what the URL does, whether a tree
 * remounts, which entry animations run. Model output is the backend's problem
 * and has its own tests.
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";
import { handleChatStream } from "./fake-stream.mjs";

import { createConversationStore } from "./fake-conversations.mjs";

const BASE = process.argv[2] ?? "http://localhost:4173";
const CORS = {
	"Access-Control-Allow-Origin": "*",
	"Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
	"Access-Control-Allow-Headers": "Content-Type, Authorization, X-Aspire-Device",
};

let fails = 0;
const results = [];
const say = (n, label, ok, detail = "") => {
	if (!ok) fails += 1;
	results.push({ n, label, ok, detail });
	console.log(`  ${ok ? "PASS" : "FAIL"}  ${n}. ${label}${detail ? " — " + detail : ""}`);
};

const browser = await puppeteer.launch({ headless: "new" });

async function open({ title = "Index fund basics", chatStatus = 200, chatDelay = 0, width = 1280, height = 800, reply = "An index fund holds a little of every company on a list.", forceThreadId = null } = {}) {
	const page = await browser.newPage();
	await page.setViewport({ width, height });
	const seen = { chat: [], title: [] };
	// History is server state now, so the harness needs a service to be the
	// history OF. See fake-conversations.mjs.
	const store = createConversationStore();

	await page.setRequestInterception(true);
	page.on("request", async (r) => {
		if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });

		const answered = await store.handle(r, (status, body) =>
			r.respond({
				status,
				contentType: "application/json",
				headers: CORS,
				body: body === null ? "" : JSON.stringify(body),
			}),
		);
		if (answered) return;

		// `/chat/stream` is the transport now; `/chat` stays as the fallback.
		//
		// This branch has to honour EVERY option the `/chat` branch honours, not
		// just the reply text. Skipping `chatDelay` made the answer arrive before
		// the test could look for the question, and skipping `chatStatus` turned
		// the failed-send scenario into a successful one — both of which read as
		// product regressions when they were gaps in the stub.
		if (r.url().endsWith("/chat/stream")) {
			// Recorded before the delay, exactly as the `/chat` branch does. A
			// test that inspects the page mid-flight has to be able to see that
			// the request was made, not only that it finished.
			{
				const raw = JSON.parse(r.postData() || "{}");
				seen.chat.push({ ...raw, ...(raw.forwardedProps ?? {}) });
			}
			if (chatDelay) await new Promise((x) => setTimeout(x, chatDelay));
			if (chatStatus !== 200) {
				return r.respond({
					status: chatStatus,
					contentType: "application/json",
					headers: CORS,
					body: '{"detail":"The assistant is temporarily unavailable."}',
				});
			}
			handleChatStream(
				r,
				(body) =>
					r.respond({ status: 200, contentType: "text/event-stream", headers: CORS, body }),
				(sent) => {
					const id = forceThreadId || sent.thread_id || "t-server";
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

		if (r.url().endsWith("/chat")) {
			const sent = JSON.parse(r.postData() || "{}");
			seen.chat.push(sent);
			// The service opens the conversation and records the question BEFORE
			// it tries to answer, so a failed first send still leaves a chat that
			// can be reopened and re-asked. Mirrored here or the failure paths
			// would test a service that does not exist.
			store.openConversation(
				sent.thread_id || "t-server",
				store.ownerOf(r),
				sent.message,
			);
			if (chatDelay) await new Promise((x) => setTimeout(x, chatDelay));
			if (chatStatus !== 200) {
				return r.respond({ status: chatStatus, contentType: "application/json", headers: CORS, body: '{"detail":"The assistant is temporarily unavailable."}' });
			}
			const threadId = forceThreadId || sent.thread_id || "t-server";
			// The service persists the turn as it answers; so does this.
			store.recordTurn(threadId, store.ownerOf(r), sent.message, {
				role: "assistant",
				text: reply,
				sources: [],
				follow_ups: [],
			});
			return r.respond({
				status: 200,
				contentType: "application/json",
				headers: CORS,
				body: JSON.stringify({
					reply,
					// Echoes whatever the client sent, exactly as the real service
					// does — unless a test deliberately makes it disagree.
					thread_id: threadId,
					sources: [],
					follow_ups: [],
				}),
			});
		}
		if (r.url().endsWith("/api/title")) {
			seen.title.push(JSON.parse(r.postData() || "{}"));
			return r.respond({ status: 200, contentType: "application/json", headers: CORS, body: JSON.stringify({ title }) });
		}
		if (r.url().includes("/api/games/")) return r.respond({ status: 404, contentType: "application/json", headers: CORS, body: "{}" });
		r.continue();
	});

	await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await page.evaluate(() => localStorage.clear());
	await page.reload({ waitUntil: "networkidle2" });
	return { page, seen, store };
}

/**
 * What history exists, read where history now lives.
 *
 * This used to read `localStorage["aspire.conversations.v1"]`, because that was
 * the store. It is not any more: conversations belong to the service and the
 * client caches them. Reading the old key would now report an empty history for
 * a product whose rail is full — an assertion about a location rather than about
 * behaviour, and one that fails for the wrong reason.
 */
const stored = (page) =>
	page.evaluate(() => {
		const qc = window.__TSR_ROUTER__?.options?.context?.queryClient;
		if (!qc) return [];
		// Keyed by owner now — `["conversations", <userId>]` — so the list is
		// found by prefix rather than by an exact key. That the owner is IN the
		// key is what stops one identity ever reading another's.
		const entry = qc
			.getQueryCache()
			.getAll()
			.find((q) => q.queryKey[0] === "conversations" && q.queryKey.length === 2 && Array.isArray(q.state.data));
		return entry?.state.data ?? [];
	});
const path = (page) => page.evaluate(() => location.pathname);
const focused = (page) => page.evaluate(() => document.activeElement?.id ?? "");
const rows = (page) => page.evaluate(() => [...document.querySelectorAll(".history-item")].map((b) => b.textContent.trim()));
const settle = (ms = 400) => new Promise((r) => setTimeout(r, ms));

/**
 * Reaches a rail control the way a user has to.
 *
 * On the landing screen the rail is collapsed to zero width at every width, so
 * the gradient can run full-bleed — which means both "New chat" and the history
 * list sit behind the floating drawer trigger there. Clicking them directly
 * only works from inside a conversation on a wide screen.
 */
const viaRail = async (page, selector, index = 0) => {
	const shut = await page.evaluate(() => !!document.querySelector(".rail-open"));
	if (shut) {
		await page.click(".rail-open");
		await settle(400);
	}
	const targets = await page.$$(selector);
	if (!targets[index]) throw new Error(`no ${selector}[${index}]`);
	await targets[index].click();
	await settle(500);
};

/**
 * Counts SPA navigations.
 *
 * Has to be reinstalled after any real page load: a `goto` replaces the
 * document and takes the patch with it, which silently turned the double-press
 * assertion into a test of nothing.
 */
const trackNavs = (page) =>
	page.evaluate(() => {
		window.__alive = true;
		window.__navs = 0;
		if (window.__tracked) return;
		window.__tracked = true;
		const push = history.pushState.bind(history);
		const replace = history.replaceState.bind(history);
		history.pushState = (...a) => { window.__navs += 1; return push(...a); };
		history.replaceState = (...a) => { window.__navs += 1; return replace(...a); };
	});

const send = async (page, text) => {
	await page.type("#aspire-composer", text);
	await page.keyboard.press("Enter");
};
const awaitAnswer = (page) => page.waitForFunction(() => !document.querySelector(".composer__send--stop"), { timeout: 20000 });

// Stamps every node we must not lose, so "same DOM node" is checkable rather
// than assumed. ANIMATION-INVENTORY.md says a remount replaces the 560ms morph
// with a hard cut; this is how that claim gets tested.
const stamp = (page) =>
	page.evaluate(() => {
		let i = 0;
		for (const sel of [".app", ".hero", ".composer", ".rail", ".thread"]) {
			const el = document.querySelector(sel);
			if (el) el.dataset.identity = `id-${sel}-${i++}`;
		}
	});
const stamps = (page) =>
	page.evaluate(() =>
		[".app", ".hero", ".composer", ".rail", ".thread"].map((sel) => document.querySelector(sel)?.dataset.identity ?? "GONE"),
	);

console.log("\n═══ New chat lifecycle — 13 acceptance tests ═══\n");

/* 1 ── Load `/`. Cursor in the composer. No sidebar entry. */
{
	const { page } = await open();
	await settle();
	const id = await focused(page);
	const entries = await stored(page);
	say(1, "Load `/`: composer focused, no history entry", id === "aspire-composer" && entries.length === 0, `focus=${id || "none"} entries=${entries.length}`);
	await page.close();
}

/* 2 ── Navigate away and back. Still nothing. */
{
	const { page } = await open();
	await settle();
	await page.goto(`${BASE}/chat/does-not-exist`, { waitUntil: "networkidle2" });
	await settle();
	const afterUnknown = await path(page);
	await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await settle();
	const entries = await stored(page);
	say(2, "Navigate away and back: still no entry", entries.length === 0, `entries=${entries.length}, unknown id redirected to ${afterUnknown}`);
	await page.close();
}

/* 3 ── Send. URL becomes /chat/:id, no reload, nodes survive, message first. */
{
	const { page, seen } = await open({ chatDelay: 1200 });
	await settle();
	await stamp(page);

	// `__alive` survives a param change and not a reload, which is the difference
	// test 3 is actually asserting.
	await trackNavs(page);

	await send(page, "What is an index fund?");
	// Mid-flight: the answer has not come back yet.
	await settle(500);

	const midUrl = await path(page);
	const bubble = await page.evaluate(() => document.querySelector(".turn--user .bubble")?.textContent ?? "");
	const answered = await page.evaluate(() => !!document.querySelector(".turn--assistant .answer p"));
	const alive = await page.evaluate(() => window.__alive === true);
	const after = await stamps(page);
	const intact = after.every((s) => s.startsWith("id-"));
	// The user's own message animates; that is the one entrance that should run.
	const entering = await page.evaluate(() => !!document.querySelector('.turn--user[data-enter]'));

	say(
		3,
		"First send: /chat/:id, no reload, no remount, message before response",
		midUrl.startsWith("/chat/") && alive && intact && bubble.includes("index fund") && !answered && entering,
		`url=${midUrl} noReload=${alive} nodesKept=${intact} answerYet=${answered} riseOnUserTurn=${entering}`,
	);

	// Same request carried the minted id, so the server never minted a second.
	const sentId = seen.chat[0]?.thread_id;
	say(
		"3b",
		"The id in the URL is the id that was sent",
		typeof sentId === "string" && midUrl === `/chat/${sentId}`,
		`sent=${sentId}`,
	);

	/* 4 ── Sidebar entry appears immediately, at the top of Today. */
	const entries = await stored(page);
	const label = (await rows(page))[0] ?? "";
	const group = await page.evaluate(() => document.querySelector(".rail__group-title")?.textContent ?? "");
	const active = await page.evaluate(() => document.querySelector('.history-item[aria-current="true"]')?.textContent?.trim() ?? "");
	say(
		4,
		"Sidebar entry appears immediately, top of Today, active",
		entries.length === 1 && group === "Today" && label.includes("index fund") && active.includes("index fund"),
		`entries=${entries.length} group=${group} label="${label}"`,
	);

	/* 5 ── Response completes → crossfade to the generated title. */
	await awaitAnswer(page);
	await settle(900);
	const titleRow = (await rows(page))[0] ?? "";
	const bar = await page.evaluate(() => document.querySelector(".titlebar__text")?.textContent ?? "");
	const docTitle = await page.title();
	// Both surfaces animate the swap rather than substituting the text.
	const fades = await page.evaluate(() => {
		const names = (el) => (el ? getComputedStyle(el).animationName : "none");
		return { row: names(document.querySelector(".xfade__in")), bar: names(document.querySelector(".titlebar__text")) };
	});
	say(
		5,
		"Response completes: sidebar + top bar carry the generated title, document.title syncs",
		titleRow === "Index fund basics" && bar === "Index fund basics" && docTitle.startsWith("Index fund basics") && fades.row === "fade-in" && fades.bar === "fade-in",
		`row="${titleRow}" bar="${bar}" doc="${docTitle}" fade=${fades.row}/${fades.bar}`,
	);

	/* 6 ── Refresh restores title and conversation. */
	const url = await page.evaluate(() => location.href);
	await page.goto(url, { waitUntil: "networkidle2" });
	await settle(600);
	const restoredBar = await page.evaluate(() => document.querySelector(".titlebar__text")?.textContent ?? "");
	const turns = await page.evaluate(() => document.querySelectorAll(".turn").length);
	const restoredPath = await path(page);
	// Nothing restored may replay its entrance.
	const replayed = await page.evaluate(() => document.querySelectorAll(".turn[data-enter]").length);
	say(
		6,
		"Refresh: title and full conversation restore",
		restoredPath.startsWith("/chat/") && restoredBar === "Index fund basics" && turns === 2 && replayed === 0,
		`path=${restoredPath} bar="${restoredBar}" turns=${turns} replayedEntrances=${replayed}`,
	);

	/* 7 ── New chat: empty state, focused composer, history kept. */
	await trackNavs(page);
	await page.click(".btn-new");
	await settle(600);
	const p7 = await path(page);
	const phase = await page.evaluate(() => document.querySelector(".app")?.dataset.phase);
	const f7 = await focused(page);
	const kept = (await stored(page)).length;
	say(
		7,
		"New chat: empty state, focused composer, previous chat kept",
		p7 === "/" && phase === "landing" && f7 === "aspire-composer" && kept === 1,
		`path=${p7} phase=${phase} focus=${f7 || "none"} history=${kept}`,
	);

	/* 8 ── Two halves, because the button lives in two places.
	 *
	 * On the landing screen the rail is collapsed to zero width by design, so
	 * "New chat" is only reachable through the drawer there. A rapid double
	 * press is therefore only physically possible from inside a conversation,
	 * where the rail is a column — that is 8a. The no-op-while-already-empty
	 * case is reached the way a user actually reaches it from the empty state,
	 * via the keyboard — that is 8b. */
	await viaRail(page, ".history-item");
	// Both clicks dispatched synchronously against the same node, which is what a
	// genuine rapid double press does. Puppeteer's own `.click()` re-resolves the
	// element and waits for it to be clickable, so it can never race the guard —
	// by its second call the first navigation has already landed.
	await page.evaluate(() => {
		window.__navs = 0;
		const button = document.querySelector(".btn-new");
		button.click();
		button.click();
	});
	await settle(700);
	const navs = await page.evaluate(() => window.__navs);
	const still = (await stored(page)).length;
	say(
		"8a",
		"Rapid double press from a chat: exactly one navigation, no duplicate",
		navs === 1 && still === 1 && (await path(page)) === "/",
		`navigations=${navs} history=${still}`,
	);

	await page.evaluate(() => { window.__navs = 0; });
	await page.type("#aspire-composer", "half a thought");
	for (let i = 0; i < 2; i += 1) {
		await page.keyboard.down("Control");
		await page.keyboard.down("Shift");
		await page.keyboard.press("KeyO");
		await page.keyboard.up("Shift");
		await page.keyboard.up("Control");
	}
	await settle(600);
	const navs2 = await page.evaluate(() => window.__navs);
	const draftKept = await page.evaluate(() => document.querySelector("#aspire-composer").value);
	const still2 = (await stored(page)).length;
	const f8 = await focused(page);
	say(
		"8b",
		"New chat while already empty: no navigation, no duplicate, draft and focus kept",
		navs2 === 0 && still2 === 1 && draftKept === "half a thought" && f8 === "aspire-composer",
		`navigations=${navs2} history=${still2} draft="${draftKept}" focus=${f8 || "none"}`,
	);

	await page.close();
}

/* 9 ── Open an old chat. No entry animation replays. */
{
	// Long enough that the thread genuinely overflows. Two one-line turns do not
	// scroll at 800px, so the earlier scroll assertion was setting scrollTop on
	// an element with nowhere to go and reading back the 0 it never left.
	const long = Array.from(
		{ length: 14 },
		(_, i) => `Paragraph ${i + 1}. An index fund holds a little of every company on a list, which is what spreads the risk.`,
	).join("\n\n");
	const { page } = await open({ reply: long });
	await settle();
	await send(page, "What is an index fund?");
	await awaitAnswer(page);
	await settle(600);

	await page.click(".btn-new");
	await settle(500);
	await viaRail(page, ".history-item");

	const replayed = await page.evaluate(() => document.querySelectorAll(".turn[data-enter]").length);
	const turns = await page.evaluate(() => document.querySelectorAll(".turn").length);
	const p = await path(page);
	say(9, "Reopening a chat replays no entry animation", replayed === 0 && turns === 2 && p.startsWith("/chat/"), `turns=${turns} withEntrance=${replayed} path=${p}`);

	/* Scroll position is remembered per conversation. */
	const overflow = await page.evaluate(() => {
		const t = document.querySelector(".thread");
		return t.scrollHeight - t.clientHeight;
	});
	await page.evaluate(() => { document.querySelector(".thread").scrollTop = 40; });
	await settle(300);
	const set = await page.evaluate(() => Math.round(document.querySelector(".thread").scrollTop));
	await page.click(".btn-new");
	await settle(400);
	await viaRail(page, ".history-item");
	const top = await page.evaluate(() => Math.round(document.querySelector(".thread").scrollTop));
	say("9b", "Scroll position preserved per conversation", set === 40 && top === 40, `overflow=${overflow}px set=${set} restored=${top}`);
	await page.close();
}

/* 10 ── Gibberish opener: the service declines, provisional label stands. */
{
	const { page, seen } = await open({ title: null });
	await settle();
	await send(page, "asdfgh");
	await awaitAnswer(page);
	await settle(900);
	const row = (await rows(page))[0] ?? "";
	const bar = await page.evaluate(() => document.querySelector(".titlebar__text")?.textContent ?? "");
	say(
		10,
		"NO_TITLE opener: provisional label kept, nothing invented",
		seen.title.length === 1 && row === "asdfgh" && bar === "asdfgh",
		`titleCalls=${seen.title.length} row="${row}" bar="${bar}"`,
	);
	await page.close();
}

/* 11 ── Language reaches the title call. */
{
	const { page, seen } = await open({ title: "Fondos indexados explicados" });
	await settle();
	await page.evaluate(() => {
		localStorage.setItem("aspire.voice.prefs.v1", JSON.stringify({ autoSpeak: false, speed: "1.25", language: "es" }));
	});
	await page.reload({ waitUntil: "networkidle2" });
	await settle(400);
	await send(page, "Que es un fondo indexado?");
	await awaitAnswer(page);
	await settle(900);
	const row = (await rows(page))[0] ?? "";
	say(
		11,
		"Spanish session: the title call carries language=es and the title lands",
		seen.title[0]?.language === "es" && row === "Fondos indexados explicados",
		`language=${seen.title[0]?.language} row="${row}"`,
	);

	/* 12 ── Voice speed survives starting a new chat. */
	await page.click(".btn-new");
	await settle(500);
	const speed = await page.evaluate(() => JSON.parse(localStorage.getItem("aspire.voice.prefs.v1")).speed);
	const lang = await page.evaluate(() => JSON.parse(localStorage.getItem("aspire.voice.prefs.v1")).language);
	say(12, "Voice speed and language survive a new chat", speed === "1.25" && lang === "es", `speed=${speed} language=${lang}`);
	await page.close();
}

/* 13 ── 320px: New chat from the drawer closes it and leaves the composer usable. */
{
	const { page } = await open({ width: 320, height: 568 });
	await settle();
	await send(page, "What is an index fund?");
	await awaitAnswer(page);
	await settle(600);

	await page.click(".titlebar__menu");
	await settle(400);
	const opened = await page.evaluate(() => !!document.querySelector(".rail-scrim"));
	await page.click(".btn-new");
	await settle(600);

	const scrim = await page.evaluate(() => !!document.querySelector(".rail-scrim"));
	const inert = await page.evaluate(() => document.querySelector(".workspace")?.hasAttribute("inert"));
	// Usable means it can actually be typed into, not merely visible.
	await page.click("#aspire-composer");
	await page.type("#aspire-composer", "hi");
	const typed = await page.evaluate(() => document.querySelector("#aspire-composer").value);
	const p = await path(page);
	say(
		13,
		"320px: drawer opens, New chat closes it and the composer is usable",
		opened && !scrim && !inert && typed === "hi" && p === "/",
		`drawerOpened=${opened} scrimAfter=${scrim} workspaceInert=${inert} typed="${typed}" path=${p}`,
	);
	await page.close();
}

/* Extra ── the failure case §5 demands: a committed chat must stay recoverable. */
{
	const { page } = await open({ chatStatus: 502 });
	await settle();
	await send(page, "What is an index fund?");
	await awaitAnswer(page);
	await settle(500);
	const kept = await page.evaluate(() => document.querySelector(".turn--user .bubble")?.textContent ?? "");
	const retry = await page.evaluate(() => [...document.querySelectorAll(".text-btn")].some((b) => b.textContent.includes("Try again")));

	// And still recoverable after leaving and coming back.
	await page.click(".btn-new");
	await settle(400);
	await viaRail(page, ".history-item");
	const question = await page.evaluate(() => document.querySelector(".turn--user .bubble")?.textContent ?? "");
	const retryAfter = await page.evaluate(() => [...document.querySelectorAll(".text-btn")].some((b) => b.textContent.includes("Try again")));
	say(
		"§5",
		"Failed first send: message kept, retry offered, still recoverable on reopen",
		kept.includes("index fund") && retry && question.includes("index fund") && retryAfter,
		`kept=${!!kept} retry=${retry} afterReopen=${retryAfter}`,
	);
	await page.close();
}

/* Extra ── a server that answers with a different thread id must not be able to
 * destroy the conversation on screen.
 *
 * This is the shape of a real defect that the first version of this file could
 * not see, because its stub always echoed the id back. The design suite's stub
 * returns a hardcoded one, and that was enough to wipe the answer and leave the
 * never-got-an-answer turn in its place. */
{
	const { page } = await open({ forceThreadId: "some-other-id" });
	await settle();
	await send(page, "What is an index fund?");
	await awaitAnswer(page);
	await settle(700);
	const answered = await page.evaluate(() => !!document.querySelector(".turn--assistant .answer p"));
	const orphaned = await page.evaluate(() => document.body.textContent.includes("never got an answer"));
	const url = await path(page);
	const entries = await stored(page);
	say(
		"§rb",
		"A disagreeing thread_id in the response does not orphan the chat",
		answered && !orphaned && url.startsWith("/chat/") && entries.length === 1,
		`answerShown=${answered} orphanTurn=${orphaned} url=${url} entries=${entries.length}`,
	);
	await page.close();
}

/* Extra ── the keyboard shortcut. */
{
	const { page } = await open();
	await settle();
	await send(page, "What is an index fund?");
	await awaitAnswer(page);
	await settle(500);
	await page.keyboard.down("Control");
	await page.keyboard.down("Shift");
	await page.keyboard.press("KeyO");
	await page.keyboard.up("Shift");
	await page.keyboard.up("Control");
	await settle(600);
	const p = await path(page);
	const phase = await page.evaluate(() => document.querySelector(".app")?.dataset.phase);
	say("§4", "Ctrl+Shift+O starts a new chat", p === "/" && phase === "landing", `path=${p} phase=${phase}`);
	await page.close();
}

await browser.close();
console.log(`\n${fails === 0 ? "All green." : `${fails} failing.`}\n`);
process.exit(fails === 0 ? 0 : 1);
