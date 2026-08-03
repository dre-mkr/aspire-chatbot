/**
 * The reserved tail, as a control rather than as pixels.
 *
 * The flash audit proves the answer stops blinking. This proves the mechanism
 * that replaced the blink is not merely invisible but correct: the action row
 * and the suggestion chips occupy their final space for the whole reveal, they
 * are unreachable while they are transparent, and they become fully usable the
 * moment the answer settles.
 *
 * Reserving space is only an improvement if the reserved controls cannot be
 * tabbed into or clicked while they are pretending not to be there.
 *
 *   node .impeccable/preview-server.mjs &
 *   node .impeccable/flash-tail.mjs
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";
import { handleChatStream } from "./fake-stream.mjs";


const BASE = process.argv[2] ?? "http://localhost:4173";
const CORS = {
	"Access-Control-Allow-Origin": "*",
	"Access-Control-Allow-Methods": "GET,POST,OPTIONS",
	"Access-Control-Allow-Headers": "Content-Type, X-Aspire-Device",
};

const REPLY = Array.from(
	{ length: 8 },
	(_, i) =>
		`Paragraph ${i + 1}. An index fund holds a little of every company on a list, so instead of betting on one name you own a slice of hundreds at the same time.`,
).join("\n\n");

const SOURCES = [
	{ content: "An index fund tracks a market index.", metadata: { question: "What is an index fund?" } },
];
const FOLLOW_UPS = ["How much do I need to start?", "What is compound interest?"];

let fails = 0;
const say = (label, ok, detail = "") => {
	if (!ok) fails += 1;
	console.log(`  ${ok ? "PASS" : "FAIL"}  ${label}${detail ? " — " + detail : ""}`);
};

const browser = await puppeteer.launch({ headless: "new" });

async function open({ reducedMotion = false } = {}) {
	const page = await browser.newPage();
	await page.setViewport({ width: 1280, height: 900 });
	if (reducedMotion) {
		await page.emulateMediaFeatures([{ name: "prefers-reduced-motion", value: "reduce" }]);
	}
	await page.setRequestInterception(true);
	page.on("request", async (r) => {
		if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
		// `/chat/stream` is the transport now; `/chat` stays as the fallback.
		// Both are served from the same fixture so they cannot drift apart.
		if (
			handleChatStream(r, (body) =>
				r.respond({ status: 200, contentType: "text/event-stream", headers: CORS, body }),
				{ reply: REPLY, sources: SOURCES, followUps: FOLLOW_UPS },
			)
		)
			return;

		if (r.url().endsWith("/chat")) {
			const sent = JSON.parse(r.postData() || "{}");
			return r.respond({
				status: 200,
				contentType: "application/json",
				headers: CORS,
				body: JSON.stringify({
					reply: REPLY,
					thread_id: sent.thread_id || "t",
					sources: SOURCES,
					follow_ups: FOLLOW_UPS,
				}),
			});
		}
		if (r.url().endsWith("/api/title")) {
			return r.respond({ status: 200, contentType: "application/json", headers: CORS, body: '{"title":"Index funds"}' });
		}
		if (r.url().includes("/api/")) {
			return r.respond({ status: 404, contentType: "application/json", headers: CORS, body: "{}" });
		}
		r.continue();
	});
	await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await page.evaluate(() => localStorage.clear());
	await page.reload({ waitUntil: "networkidle2" });
	return page;
}

/** Everything about the tail and the chips that this test cares about. */
const state = (page) =>
	page.evaluate(() => {
		const tail = document.querySelector(".answer__tail");
		const chips = document.querySelector(".follow-ups");
		const box = (el) => {
			if (!el) return null;
			const r = el.getBoundingClientRect();
			return { h: Math.round(r.height), w: Math.round(r.width) };
		};
		return {
			busy: !!document.querySelector('.transcript [aria-busy="true"]'),
			tail: tail
				? {
						pending: tail.hasAttribute("data-pending"),
						inert: tail.hasAttribute("inert"),
						opacity: Number(getComputedStyle(tail).opacity),
						...box(tail),
						buttons: tail.querySelectorAll("button").length,
						hasSources: !!tail.querySelector(".sources"),
					}
				: null,
			chips: chips
				? {
						pending: chips.hasAttribute("data-pending"),
						inert: chips.hasAttribute("inert"),
						opacity: Number(getComputedStyle(chips).opacity),
						...box(chips),
						count: chips.querySelectorAll("button").length,
					}
				: null,
		};
	});

const ask = async (page, q = "What is an index fund?") => {
	await page.waitForSelector("#aspire-composer");
	await page.click("#aspire-composer");
	await page.type("#aspire-composer", q);
	await page.keyboard.press("Enter");
};

// ─── 1. During the reveal ────────────────────────────────────────────────────
console.log("\n── while the answer is revealing ──────────────────────");
{
	const page = await open();
	await ask(page);
	await page.waitForFunction(
		() => document.querySelectorAll('.transcript [aria-busy="true"] .answer > p').length >= 3,
		{ timeout: 20000, polling: 50 },
	);
	const mid = await state(page);

	say("the tail exists before the answer settles", !!mid.tail && mid.busy, mid.tail ? `${mid.tail.h}px tall` : "absent");
	say("the tail is laid out, not collapsed", (mid.tail?.h ?? 0) > 0, `${mid.tail?.h}px`);
	say("the tail is transparent while revealing", mid.tail?.pending === true && mid.tail?.opacity === 0, `opacity ${mid.tail?.opacity}`);
	say("the tail is inert while revealing", mid.tail?.inert === true);
	say("the sources chip is reserved too", mid.tail?.hasSources === true);
	say("the follow-up chips are laid out while revealing", (mid.chips?.h ?? 0) > 0, `${mid.chips?.h}px, ${mid.chips?.count} chips`);
	say("the follow-up chips are transparent and inert", mid.chips?.pending === true && mid.chips?.opacity === 0 && mid.chips?.inert === true);

	// The point of `inert`: a transparent control that still takes Tab is worse
	// than one that moves. Walk the tab ring and prove nothing in the tail is on it.
	const reachable = await page.evaluate(() => {
		const inTail = [...document.querySelectorAll(".answer__tail button, .follow-ups button")];
		return inTail.filter((b) => b.checkVisibility?.({ checkOpacity: false }) && !b.closest("[inert]")).length;
	});
	say("no reserved control is reachable while revealing", reachable === 0, `${reachable} reachable`);

	// Heights recorded now, to compare with the settled ones below.
	await page.waitForFunction(() => !document.querySelector('.transcript [aria-busy="true"]'), { timeout: 20000, polling: 50 });
	await new Promise((r) => setTimeout(r, 600));
	const done = await state(page);

	console.log("\n── once it has settled ───────────────────────────────");
	say("the tail becomes visible", done.tail?.pending === false && done.tail?.opacity === 1, `opacity ${done.tail?.opacity}`);
	say("the tail is no longer inert", done.tail?.inert === false);
	say("the tail did not change size when it appeared", done.tail?.h === mid.tail?.h, `${mid.tail?.h}px → ${done.tail?.h}px`);
	say("the chips became visible without resizing", done.chips?.opacity === 1 && done.chips?.h === mid.chips?.h, `${mid.chips?.h}px → ${done.chips?.h}px`);
	say("the chips are no longer inert", done.chips?.inert === false);

	// And they actually work.
	const copied = await page.evaluate(async () => {
		const btn = document.querySelector(".answer__tail .icon-btn");
		if (!btn) return "no button";
		btn.click();
		await new Promise((r) => setTimeout(r, 120));
		return btn.querySelector(".sr-only")?.textContent ?? "";
	});
	say("the Copy button in the revealed tail works", /copied/i.test(copied), copied);

	const askedAgain = await page.evaluate(() => {
		const chip = document.querySelector(".follow-ups .follow-up");
		return chip ? chip.textContent.trim() : null;
	});
	say("a follow-up chip is present and labelled", !!askedAgain, askedAgain ?? "");

	await page.close();
}

// ─── 2. Reduced motion: no reveal at all, so nothing may be reserved ─────────
console.log("\n── prefers-reduced-motion: reduce ────────────────────");
{
	const page = await open({ reducedMotion: true });
	await ask(page);
	await page.waitForFunction(() => document.querySelectorAll(".transcript .answer-actions").length > 0, {
		timeout: 20000,
		polling: 50,
	});
	await new Promise((r) => setTimeout(r, 400));
	const s = await state(page);

	// With reduced motion the answer never streams — it lands whole — so the
	// tail must be visible and usable from its very first frame.
	say("the answer lands complete, not revealing", s.busy === false);
	say("the tail is visible immediately", s.tail?.pending === false && s.tail?.opacity === 1, `opacity ${s.tail?.opacity}`);
	say("the tail is interactive immediately", s.tail?.inert === false);
	say("the chips are visible immediately", s.chips?.opacity === 1 && s.chips?.pending === false);
	await page.close();
}

console.log(`\n${fails === 0 ? "ALL PASS" : `${fails} FAIL`}`);
await browser.close();
process.exit(fails === 0 ? 0 : 1);
