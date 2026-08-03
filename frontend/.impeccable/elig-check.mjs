/**
 * Acceptance for the eligibility card, in a real browser.
 *
 * Covers the criteria that only exist on screen: back navigation preserving
 * answers, "I am not sure" never blocking, a refresh mid-flow and after the
 * verdict, checklist ticks persisting, and 320px in French with no overflow.
 *
 * The backend is the REAL engine, proxied: this script talks to a running
 * FastAPI on :8000 (override API in the file) and only stubs `/chat` (so no model call is needed to get
 * the card on screen). That matters — stubbing the eligibility endpoints would
 * test the stub rather than the audited rules.
 *
 * Usage: node .impeccable/elig-check.mjs [lang]
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";
import { createConversationStore, serveAnonymousAuth } from "./fake-conversations.mjs";

const LANG = process.argv[2] ?? "en";
const API = "http://localhost:8000";
const CORS = {
	"Access-Control-Allow-Origin": "*",
	"Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
	"Access-Control-Allow-Headers": "Content-Type, Authorization, X-Aspire-Device",
};

const results = [];
const check = (name, ok, detail = "") => {
	results.push({ name, ok, detail });
	console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${detail ? ` — ${detail}` : ""}`);
};

/** A fresh thread id per run, so the server-side flow never collides. */
const thread = `browser-${Date.now()}`;

const browser = await puppeteer.launch({ headless: "new" });
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 900 });

/**
 * Stubs `/chat` and nothing else.
 *
 * The stub stands in for the model call only. It does what the real agent's
 * tool does — POSTs to the REAL `/api/eligibility/start` — so from the card's
 * point of view everything downstream is the actual engine, actual rules and
 * actual copy. Stubbing the eligibility endpoints would have tested the stub.
 */
// The conversation has to exist somewhere the app can read it back.
// This suite reloads the page and expects the card to still be there, which
// means the thread has to be reopened — and reopening it goes through the
// conversations service now, not localStorage. Without a service holding the
// thread, the reload landed on the empty state and the card never mounted.
// Eligibility itself is still the REAL endpoint: `store.handle` only answers
// auth and /api/conversations and passes everything else through.
const store = createConversationStore();
const installStub = async () => {
	await page.setRequestInterception(true);
	page.removeAllListeners("request");
	page.on("request", async (r) => {
		if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
		if (serveAnonymousAuth(r, CORS)) return;
		if (await store.handle(r, (status, body) => r.respond({ status, contentType: "application/json", headers: CORS, body: body === null ? "" : JSON.stringify(body) }))) return;
		if (r.url().endsWith("/chat")) {
			// The client mints the conversation id before sending, and the real
			// service echoes it back — that id is the URL, the storage key and
			// the eligibility session key all at once. The stub has to echo it
			// too, and start the real flow under it, or the card would fetch one
			// thread's question and post its answers to another.
			const sent = JSON.parse(r.postData() ?? "{}");
			const threadId = sent.thread_id ?? `fallback-${Date.now()}`;
			try {
				await fetch(`${API}/api/eligibility/start`, {
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({ thread_id: threadId, language: LANG }),
				});
			} catch {
				// Reported by the checks below as a missing card.
			}
			store.openConversation(threadId, store.ownerOf(r), sent.message);
			store.recordTurn(threadId, null, sent.message, { role: "assistant", text: "", sources: [], follow_ups: [] });
			return r.respond({
				status: 200,
				contentType: "application/json",
				headers: CORS,
				body: JSON.stringify({
					reply: "",
					thread_id: threadId,
					sources: [],
					follow_ups: [],
					eligibility_started: { check: "aspire_eligibility", language: LANG },
				}),
			});
		}
		if (r.url().includes("/api/games/")) {
			return r.respond({ status: 404, contentType: "application/json", headers: CORS, body: "{}" });
		}
		r.continue();
	});
};

await installStub();

// The card opens in the language the conversation is held in, which the client
// reads from the voice preference. Set before first paint.
await page.evaluateOnNewDocument((lang) => {
	window.localStorage.setItem(
		"aspire.voice.prefs.v1",
		JSON.stringify({ autoSpeak: false, speed: 1, language: lang }),
	);
}, LANG);

await page.goto("http://localhost:4173/", { waitUntil: "networkidle2" });

const ask = async (text) => {
	await page.type("#aspire-composer", text);
	await page.keyboard.press("Enter");
	await page.waitForSelector(".elig", { timeout: 15000 });
	await new Promise((r) => setTimeout(r, 400));
};

const options = () =>
	page.$$eval(".elig__option", (els) =>
		els.map((e) => ({ label: e.textContent.trim(), chosen: e.hasAttribute("data-chosen") })),
	);
const questionText = () => page.$eval(".elig__question", (e) => e.textContent.trim());
const progress = () => page.$eval(".game__eyebrow span", (e) => e.textContent.trim());
/**
 * Taps an option by index, from inside the page.
 *
 * Not via an ElementHandle: React re-renders the option list on every answer,
 * so a handle grabbed a moment earlier is detached by the time puppeteer tries
 * to scroll it into view. Dispatching the click in-page reads the live DOM.
 * `-1` means the last option, which is always "I am not sure".
 */
const tapOption = async (index) => {
	await page.evaluate((i) => {
		const els = [...document.querySelectorAll(".elig__option")];
		const el = i < 0 ? els.at(i) : els[i];
		el?.click();
	}, index);
	await page.waitForNetworkIdle({ idleTime: 250, timeout: 8000 }).catch(() => {});
	await new Promise((r) => setTimeout(r, 250));
};

// ── 1. The card appears, as the whole turn ────────────────────────────────
await ask("can I join ASPIRE?");

check("card renders", (await page.$(".elig")) !== null);
check(
	"the turn is the card and nothing else — no answer actions",
	(await page.$(".elig")) !== null &&
		(await page.$$(".turn--assistant .answer-actions")).length === 0,
);
check(
	"no follow-up chips while the flow is active",
	(await page.$$(".follow-up")).length === 0,
);
check(
	"the pre-check banner is visible chrome, not fine print",
	await page.$eval(".elig__banner", (e) => {
		const r = e.getBoundingClientRect();
		const s = getComputedStyle(e);
		return r.height > 20 && s.visibility === "visible" && s.display !== "none";
	}),
);
check("progress shows on the first question", (await progress()).length > 0, await progress());

// ── 2. Back preserves answers ─────────────────────────────────────────────
const q1 = await questionText();
await tapOption(1); // "5 to 18" / equivalent
const q2 = await questionText();
await tapOption(0); // born in the Federation
const q3 = await questionText();

await page.click(".game__btn--quiet"); // Back
await new Promise((r) => setTimeout(r, 350));
const backQ = await questionText();
const backOpts = await options();
check(
	"back returns to the previous question",
	backQ === q2,
	`${backQ.slice(0, 40)}…`,
);
check(
	"back preserves the answer that was given",
	backOpts.some((o) => o.chosen),
	backOpts.find((o) => o.chosen)?.label ?? "none marked",
);

// Forward again and confirm it did not re-ask from blank.
await tapOption(0);
check("going forward again lands where it did before", (await questionText()) === q3);

// ── 3. "I am not sure" never blocks ───────────────────────────────────────
// Answer the rest with the last option (always "I am not sure").
for (let i = 0; i < 6; i += 1) {
	if (await page.$(".elig__result")) break;
	if (!(await page.$(".elig__option"))) break;
	await tapOption(-1);
}
check("an unsure path reaches a result rather than blocking", (await page.$(".elig__result")) !== null);
const verdict = await page.$eval(".elig__verdict", (e) => e.dataset.verdict);
check("that result is the conditional one", verdict === "needs_confirmation", verdict);
check("it pre-frames a question for a mentor", (await page.$(".elig__mentor-question")) !== null);
check("the disclaimer is repeated under the verdict", (await page.$(".elig__disclaimer")) !== null);
check("the checklist is shown", (await page.$$(".elig__doc")).length > 0);
check("the walkthrough is shown", (await page.$$(".elig__step-row")).length === 6);

// ── 4. Checklist ticks persist across a reload ────────────────────────────
await page.evaluate(() => document.querySelector(".elig__checkbox")?.click());
await new Promise((r) => setTimeout(r, 300));
check("ticking a document marks it", await page.$eval(".elig__doc", (e) => e.hasAttribute("data-checked")));

await page.reload({ waitUntil: "networkidle2" });
await page.waitForSelector(".elig", { timeout: 15000 });
await new Promise((r) => setTimeout(r, 600));
check(
	"the verdict survives a refresh after finishing",
	(await page.$(".elig__result")) !== null,
);
check(
	"the ticked document survives a refresh",
	await page.$eval(".elig__doc", (e) => e.hasAttribute("data-checked")),
);
check(
	"nothing renders half-way — either a question or a result, never both",
	!((await page.$(".elig__question")) && (await page.$(".elig__result"))),
);

// ── 5. Refresh MID-flow restores the question ─────────────────────────────
const midThread = `${thread}-mid`;
await page.evaluate(() => window.localStorage.clear());
await page.evaluateOnNewDocument((lang) => {
	window.localStorage.setItem(
		"aspire.voice.prefs.v1",
		JSON.stringify({ autoSpeak: false, speed: 1, language: lang }),
	);
}, LANG);
await installStub();

await page.goto("http://localhost:4173/", { waitUntil: "networkidle2" });
await ask("am I too old?");
await tapOption(1);
await tapOption(0);
const midQ = await questionText();

await page.reload({ waitUntil: "networkidle2" });
await page.waitForSelector(".elig", { timeout: 15000 });
await new Promise((r) => setTimeout(r, 600));
check(
	"a refresh mid-flow restores the same question",
	(await page.$(".elig__question")) !== null && (await questionText()) === midQ,
	(await page.$(".elig__question")) ? await questionText() : "no question",
);
check(
	"a mid-flow refresh shows no result",
	(await page.$(".elig__result")) === null,
);

// ── 6. 320px, no horizontal overflow ──────────────────────────────────────
await page.setViewport({ width: 320, height: 720 });
await new Promise((r) => setTimeout(r, 500));

const overflow = await page.evaluate(() => {
	const doc = document.documentElement;
	const offenders = [];
	for (const el of document.querySelectorAll(".elig, .elig *")) {
		const r = el.getBoundingClientRect();
		if (r.right > doc.clientWidth + 1 || r.left < -1) {
			offenders.push({
				cls: el.className?.toString?.().slice(0, 60),
				right: Math.round(r.right),
				left: Math.round(r.left),
			});
		}
	}
	return {
		pageScrolls: doc.scrollWidth > doc.clientWidth,
		width: doc.clientWidth,
		scrollWidth: doc.scrollWidth,
		offenders: offenders.slice(0, 6),
	};
});
check(
	`320px ${LANG}: the page does not scroll horizontally`,
	!overflow.pageScrolls,
	`client=${overflow.width} scroll=${overflow.scrollWidth}`,
);
check(
	`320px ${LANG}: no element escapes the viewport`,
	overflow.offenders.length === 0,
	JSON.stringify(overflow.offenders),
);

// And on the result, which is the longest content the card has.
await page.setViewport({ width: 1280, height: 900 });
for (let i = 0; i < 6; i += 1) {
	if (await page.$(".elig__result")) break;
	if (!(await page.$(".elig__option"))) break;
	await tapOption(0);
}
await page.setViewport({ width: 320, height: 720 });
await new Promise((r) => setTimeout(r, 500));

const resultOverflow = await page.evaluate(() => {
	const doc = document.documentElement;
	const offenders = [];
	for (const el of document.querySelectorAll(".elig, .elig *")) {
		const r = el.getBoundingClientRect();
		if (r.right > doc.clientWidth + 1) {
			offenders.push({ cls: el.className?.toString?.().slice(0, 60), right: Math.round(r.right) });
		}
	}
	return {
		pageScrolls: doc.scrollWidth > doc.clientWidth,
		scrollWidth: doc.scrollWidth,
		offenders: offenders.slice(0, 6),
	};
});
check(
	`320px ${LANG}: the RESULT does not overflow`,
	!resultOverflow.pageScrolls && resultOverflow.offenders.length === 0,
	`scroll=${resultOverflow.scrollWidth} ${JSON.stringify(resultOverflow.offenders)}`,
);

await page.screenshot({ path: `.impeccable/elig-${LANG}-320.png`, fullPage: true });

await browser.close();

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length ? 1 : 0);
