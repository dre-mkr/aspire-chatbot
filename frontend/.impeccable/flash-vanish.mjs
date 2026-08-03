/**
 * What else leaves the screen at completion, and does title generation matter?
 *
 * Two questions the flash audit deliberately leaves open:
 *
 *   - A dark element in the top-right of the recording disappears at the same
 *     instant and never comes back. This walks the whole document, not just the
 *     transcript, and reports every element removed or hidden at completion
 *     with its position, so the thing can be named rather than guessed at.
 *
 *   - Whether the title round trip is implicated. Titles are requested exactly
 *     at first-answer completion, which matches the timing, so the run is
 *     repeated with `/api/title` failing and the lifecycle compared.
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
const REPLY =
	"An **index fund** holds a little of every company on a list.\n\nThat matters because nobody can reliably pick the winners in advance.\n\n- You own a slice of hundreds at once\n- Fees are low";

const browser = await puppeteer.launch({ headless: "new" });

async function run({ titleOff = false } = {}) {
	const page = await browser.newPage();
	await page.setViewport({ width: 1280, height: 900, deviceScaleFactor: 1 });
	const seen = { title: 0 };

	await page.setRequestInterception(true);
	page.on("request", async (r) => {
		if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
		// `/chat/stream` is the transport now; `/chat` stays as the fallback.
		// Both are served from the same fixture so they cannot drift apart.
		if (
			handleChatStream(r, (body) =>
				r.respond({ status: 200, contentType: "text/event-stream", headers: CORS, body }),
				{ reply: REPLY },
			)
		)
			return;

		if (r.url().endsWith("/chat")) {
			const sent = JSON.parse(r.postData() || "{}");
			return r.respond({
				status: 200,
				contentType: "application/json",
				headers: CORS,
				body: JSON.stringify({ reply: REPLY, thread_id: sent.thread_id || "t", sources: [], follow_ups: [] }),
			});
		}
		if (r.url().endsWith("/api/title")) {
			seen.title += 1;
			if (titleOff) return r.respond({ status: 500, contentType: "application/json", headers: CORS, body: "{}" });
			return r.respond({
				status: 200,
				contentType: "application/json",
				headers: CORS,
				body: JSON.stringify({ title: "Index fund basics" }),
			});
		}
		if (r.url().includes("/api/games/") || r.url().includes("/api/eligibility")) {
			return r.respond({ status: 404, contentType: "application/json", headers: CORS, body: "{}" });
		}
		r.continue();
	});

	await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await page.evaluate(() => localStorage.clear());
	await page.reload({ waitUntil: "networkidle2" });

	// Watch the WHOLE document, and take a census of every visible box before
	// and after the answer settles.
	await page.evaluate(() => {
		window.__out = [];
		const label = (el) =>
			`${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ""}${
				typeof el.className === "string" && el.className ? `.${el.className.trim().split(/\s+/).join(".")}` : ""
			}`;
		new MutationObserver((records) => {
			for (const rec of records) {
				for (const el of rec.removedNodes) {
					if (el.nodeType !== 1) continue;
					window.__out.push({ t: performance.now(), what: label(el) });
				}
			}
		}).observe(document.body, { childList: true, subtree: true });

		window.__census = () => {
			const out = [];
			for (const el of document.body.querySelectorAll("*")) {
				const r = el.getBoundingClientRect();
				if (r.width < 6 || r.height < 6) continue;
				const cs = getComputedStyle(el);
				if (cs.visibility === "hidden" || cs.opacity === "0") continue;
				out.push({
					what: label(el),
					x: Math.round(r.x),
					y: Math.round(r.y),
					w: Math.round(r.width),
					h: Math.round(r.height),
					bg: cs.backgroundColor,
					bgi: cs.backgroundImage === "none" ? "" : "gradient",
				});
			}
			return out;
		};
	});

	await page.click("#aspire-composer");
	await page.type("#aspire-composer", "What is an index fund?");
	await page.keyboard.press("Enter");
	await page.waitForFunction(() => !!document.querySelector('.transcript [aria-busy="true"]'), { timeout: 15000 });
	await new Promise((r) => setTimeout(r, 250));

	const before = await page.evaluate(() => window.__census());
	await page.waitForFunction(() => document.querySelectorAll(".transcript .answer-actions").length > 0, { timeout: 20000 });
	await new Promise((r) => setTimeout(r, 1500));
	const after = await page.evaluate(() => window.__census());
	const removals = await page.evaluate(() => window.__out);

	const key = (e) => `${e.what}@${e.x},${e.y}`;
	const afterKeys = new Set(after.map((e) => e.what));
	const gone = before.filter((e) => !afterKeys.has(e.what));

	await page.close();
	return { gone, removals, before, after, seen };
}

console.log("── what disappears at completion ─────────────────────");
const a = await run();
for (const g of a.gone) {
	const rightHalf = g.x > 640;
	const topHalf = g.y < 450;
	console.log(
		`  ${g.what}\n      at ${g.x},${g.y} ${g.w}x${g.h}  bg=${g.bg}${g.bgi ? " +gradient" : ""}  ${
			rightHalf && topHalf ? "<<< TOP-RIGHT QUADRANT" : rightHalf ? "(right, lower)" : ""
		}`,
	);
}
console.log(`\n  never returns: ${a.gone.map((g) => g.what).join(", ") || "(nothing)"}`);
console.log(`  title requests: ${a.seen.title}`);

console.log("\n── cause D: title generation disabled ────────────────");
const b = await run({ titleOff: true });
const swaps = (r) => r.removals.filter((x) => /turn--assistant/.test(x.what)).length;
console.log(`  with title    : ${swaps(a)} assistant-turn removal(s), ${a.seen.title} title call(s)`);
console.log(`  without title : ${swaps(b)} assistant-turn removal(s), ${b.seen.title} title call(s)`);
console.log(
	`  → the swap is ${swaps(a) === swaps(b) ? "IDENTICAL with and without title generation: cause D is ruled out" : "AFFECTED by title generation"}`,
);

await browser.close();
