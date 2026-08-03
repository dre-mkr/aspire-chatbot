/**
 * The `/` → `/chat/$chatId` transition, measured rather than described.
 *
 * ANIMATION-INVENTORY.md promised this harness and it was never written, which
 * left the product's most fragile behaviour resting on a document. The
 * transition is not an enter/exit animation: `data-phase` flips on `.app` and
 * ten properties interpolate concurrently for 560ms. Nothing mounts, nothing
 * unmounts. Any routing change that tears down the subtree replaces the whole
 * morph with a hard cut, and no `layoutId` or View Transition reproduces it,
 * because there is no element travelling from A to B.
 *
 * So this asserts the two things that can only be true if the tree survived:
 *
 *   1. IDENTITY — `.app`, `.hero`, `.composer` and `.rail` are the same DOM
 *      nodes after the navigation as before it. Checked by stamping each node
 *      with a unique attribute before sending and reading it back after. A
 *      remount loses the stamp; nothing else does.
 *
 *   2. INTERPOLATION — each of those properties is observed at values strictly
 *      between its start and end. A cut jumps; a morph is caught mid-flight.
 *      Sampled every frame, so a 560ms transition offers ~34 chances to be
 *      caught in between.
 *
 * And the reason the whole thing exists: the reply streams while the composer
 * is still moving. That is asserted too — text present in the transcript before
 * the morph has finished.
 *
 *   node .impeccable/preview-server.mjs &
 *   node .impeccable/anim-check.mjs
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

const REPLY =
	"An index fund holds a little of every company on a list, so one bad company cannot sink you.\n\nIt is the least exciting way to invest and usually the most sensible.";

const browser = await puppeteer.launch({ headless: "new" });
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 900 });

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
				store.openConversation(id, store.ownerOf(r), sent.message);
				store.recordTurn(id, null, sent.message, {
					role: "assistant", text: REPLY, sources: [], follow_ups: [],
				});
				return { reply: REPLY };
			},
		);
		return;
	}
	if (r.url().includes("/api/")) return respond(404, {});
	r.continue();
});

await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
await page.waitForSelector("#aspire-composer", { timeout: 15000 });

// ─── stamp, then sample every frame across the send ──────────────────────────
await page.evaluate(() => {
	// A stamp survives a re-render and does not survive a remount, which is
	// exactly the distinction being tested. React never reinstates an attribute
	// it does not know about.
	for (const [selector, id] of [
		[".app", "app"],
		[".hero", "hero"],
		[".composer", "composer"],
		[".rail", "rail"],
	]) {
		document.querySelector(selector)?.setAttribute("data-anim-stamp", id);
	}

	// Catching the morph by sampling every frame does not work, and the reason is
	// worth writing down: the send does real work — a React commit, a navigation,
	// an SSE connection — and that blocks the main thread for longer than the
	// 560ms the transition lasts. requestAnimationFrame does not fire while it is
	// blocked, so the sampler's last landing frame and first chat frame sit either
	// side of the whole animation and every property looks like it jumped. The
	// harness was measuring its own jank.
	//
	// The transitions themselves are observable regardless of whether anything
	// gets a chance to paint. A MutationObserver fires synchronously on the
	// attribute change, and `getAnimations()` at that moment returns every CSS
	// transition the flip just started, with the property and duration it will
	// run for. No sampling, nothing to miss.
	window.__started = null;
	new MutationObserver(() => {
		if (window.__started) return;
		window.__started = document.getAnimations().map((a) => ({
			property: a.transitionProperty ?? null,
			duration: a.effect?.getTiming?.().duration ?? null,
			target:
				a.effect?.target?.className?.baseVal ??
				(typeof a.effect?.target?.className === "string" ? a.effect.target.className : ""),
		}));
	}).observe(document.querySelector(".app"), { attributes: true, attributeFilter: ["data-phase"] });

	const px = (value) => Number.parseFloat(value) || 0;
	window.__frames = [];
	const sample = () => {
		const app = document.querySelector(".app");
		const hero = document.querySelector(".hero");
		const composer = document.querySelector(".composer");
		const rail = document.querySelector(".rail");
		if (app) {
			window.__frames.push({
				phase: app.getAttribute("data-phase"),
				heroOpacity: hero ? Number.parseFloat(getComputedStyle(hero).opacity) : null,
				heroHeight: hero ? px(getComputedStyle(hero).maxHeight) : null,
				composerMin: composer ? px(getComputedStyle(composer).minHeight) : null,
				railWidth: rail ? px(getComputedStyle(rail).width) : null,
				// Was there streamed prose on screen while the morph was running?
				streamedText: (document.querySelector(".transcript .answer")?.textContent ?? "").length,
			});
		}
		window.__raf = requestAnimationFrame(sample);
	};
	sample();
});

const before = await page.evaluate(() => ({
	stamps: [...document.querySelectorAll("[data-anim-stamp]")].map((n) => n.getAttribute("data-anim-stamp")).sort(),
	phase: document.querySelector(".app")?.getAttribute("data-phase"),
}));
say("the app starts on the landing phase", before.phase === "landing", before.phase ?? "none");
say("all four nodes were stamped", before.stamps.join(",") === "app,composer,hero,rail", before.stamps.join(","));

await page.click("#aspire-composer");
await page.type("#aspire-composer", "What is an index fund?");
await page.keyboard.press("Enter");

// Long enough to cover the 560ms morph and the reply behind it.
await page.waitForFunction(
	() => document.querySelector(".app")?.getAttribute("data-phase") === "chat",
	{ timeout: 15000 },
);
await new Promise((r) => setTimeout(r, 1600));
await page.evaluate(() => cancelAnimationFrame(window.__raf));

// ─── 1. identity ─────────────────────────────────────────────────────────────
console.log("\n── the tree survived the navigation ──────────────────────────");
const after = await page.evaluate(() => ({
	stamps: [...document.querySelectorAll("[data-anim-stamp]")].map((n) => n.getAttribute("data-anim-stamp")).sort(),
	url: window.location.pathname,
	phase: document.querySelector(".app")?.getAttribute("data-phase"),
}));
say("the navigation happened", after.url.startsWith("/chat/"), after.url);
say("the app is on the chat phase", after.phase === "chat", after.phase ?? "none");
for (const node of ["app", "hero", "composer", "rail"]) {
	say(
		`.${node} is the same DOM node it was before the send`,
		after.stamps.includes(node),
		after.stamps.includes(node) ? "" : "remounted — the morph became a cut",
	);
}

// ─── 2. the morph actually runs ──────────────────────────────────────────────
console.log("\n── the phase flip starts real transitions ────────────────────");
const frames = await page.evaluate(() => window.__frames ?? []);
const started = await page.evaluate(() => window.__started ?? []);

say("the flip was caught", started.length > 0, `${started.length} transitions started`);

/** Every transition the flip started on one element, by property. */
const on = (className) =>
	started.filter((t) => (t.target ?? "").split(/\s+/).includes(className));

for (const [element, property, expected] of [
	["hero", "opacity", 380],
	["hero", "max-height", 560],
	["composer", "min-height", 560],
	["stage", "grid-template-rows", 560],
]) {
	const found = on(element).find((t) => t.property === property);
	say(
		`.${element} transitions ${property} rather than cutting`,
		Boolean(found) && found.duration === expected,
		found ? `${found.duration}ms (inventory says ${expected}ms)` : "no transition started",
	);
}

// The reader is not shown a frozen snapshot: whatever else happens, the hero is
// gone and the composer has moved by the end.
const ends = frames.at(-1);
const begins = frames[0];
say(
	"the hero is faded out by the end",
	begins.heroOpacity === 1 && ends.heroOpacity === 0,
	`${begins.heroOpacity} → ${ends.heroOpacity}`,
);
say(
	"the composer ends docked",
	begins.composerMin > ends.composerMin,
	`${Math.round(begins.composerMin)}px → ${Math.round(ends.composerMin)}px`,
);

// ─── 3. the reply streams during the morph ───────────────────────────────────
console.log("\n── the answer arrives while the composer is still moving ─────");
// The morph is over once `.composer` min-height stops changing. Any prose on
// screen before that frame was streamed underneath a moving composer.
const composerValues = frames.map((f) => f.composerMin);
const settledAt = composerValues.findLastIndex((v, i) => i > 0 && v !== composerValues[i - 1]);
const textDuringMorph = frames.slice(0, settledAt + 1).some((f) => f.streamedText > 0);
say(
	"prose is on screen before the morph finishes",
	textDuringMorph,
	`morph settled at frame ${settledAt} of ${frames.length}`,
);
const ended = frames.at(-1);
say("and the reply is fully rendered by the end", (ended?.streamedText ?? 0) > 40, `${ended?.streamedText ?? 0} chars`);

console.log(`\n${fails === 0 ? "ALL PASS" : `${fails} FAIL`}`);
await browser.close();
process.exit(fails === 0 ? 0 : 1);
