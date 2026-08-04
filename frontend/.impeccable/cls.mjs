/**
 * Cumulative Layout Shift, attributed to the elements that caused it.
 *
 * P5-002 measured the landing→chat transition at CLS 0.35 against a 0.05
 * budget, with the shifts landing ~1s after a question is sent and attributed
 * to `form.composer` and `div.starters`. The number was taken by hand; this is
 * the same measurement made repeatable, and it prints the offending elements
 * rather than only the total, because a total tells you nothing about what to
 * change.
 *
 * Only shifts WITHOUT `hadRecentInput` are counted, which is what CLS means:
 * a shift within 500ms of a user action is expected and excluded. The ones this
 * catches are the ones that happen while nobody has touched anything.
 *
 *   node .impeccable/preview-server.mjs &
 *   node .impeccable/cls.mjs
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";
import { handleChatStream } from "./fake-stream.mjs";

const BASE = process.argv[2] ?? "http://localhost:4173";
const BUDGET = 0.05;
const CORS = {
	"Access-Control-Allow-Origin": "*",
	"Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
	"Access-Control-Allow-Headers": "Content-Type, Authorization, X-Aspire-Device",
};
const ANSWER = {
	reply:
		"An **index fund** holds a little of every company on a list.\n\n- You own a slice of hundreds at once\n- Fees are low\n\nThat spread is what makes it steadier than one share.",
	thread_id: "t-cls",
	sources: [],
	follow_ups: ["How much do I need to start?"],
};

/** Installed before any page script, so nothing is missed. */
const OBSERVE = () => {
	window.__cls = { total: 0, entries: [] };
	new PerformanceObserver((list) => {
		for (const entry of list.getEntries()) {
			// The definition of CLS: shifts near a user action are expected.
			if (entry.hadRecentInput) continue;
			window.__cls.total += entry.value;
			for (const source of entry.sources ?? []) {
				const node = source.node;
				window.__cls.entries.push({
					value: +entry.value.toFixed(4),
					at: Math.round(entry.startTime),
					node: node
						? `${node.tagName?.toLowerCase() ?? "?"}${node.className && typeof node.className === "string" ? `.${node.className.split(" ").filter(Boolean).join(".")}` : ""}`
						: "(detached)",
				});
			}
		}
	}).observe({ type: "layout-shift", buffered: true });
};

const browser = await puppeteer.launch({ headless: "new" });

async function run(label, drive) {
	const page = await browser.newPage();
	await page.setViewport({ width: 1280, height: 800 });
	await page.setRequestInterception(true);
	page.on("request", (r) => {
		if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
		// The real SSE transport, not a JSON stub. The reveal is what the
		// composer and the follow-up chips are laid out around, so measuring
		// against a whole-response fallback measures a path nobody takes.
		if (r.url().endsWith("/chat/stream")) {
			handleChatStream(
				r,
				(body) =>
					r.respond({ status: 200, contentType: "text/event-stream", headers: CORS, body }),
				() => ({ reply: ANSWER.reply, follow_ups: ANSWER.follow_ups }),
			);
			return;
		}
		if (r.url().endsWith("/chat")) {
			return r.respond({
				status: 200,
				contentType: "application/json",
				headers: CORS,
				body: JSON.stringify(ANSWER),
			});
		}
		if (r.url().includes("/api/")) {
			return r.respond({ status: 404, contentType: "application/json", headers: CORS, body: "{}" });
		}
		r.continue();
	});
	await page.evaluateOnNewDocument(OBSERVE);
	await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await drive(page);
	await new Promise((done) => setTimeout(done, 1500));

	const cls = await page.evaluate(() => window.__cls);
	const worst = cls.entries
		.sort((a, b) => b.value - a.value)
		.slice(0, 5)
		.map((e) => `      ${e.value} @${e.at}ms  ${e.node}`);
	const ok = cls.total <= BUDGET;
	console.log(
		`  ${ok ? "PASS" : "FAIL"}  ${label} — CLS ${cls.total.toFixed(4)} (budget ${BUDGET})`,
	);
	if (worst.length) console.log(worst.join("\n"));
	await page.close();
	return ok;
}

console.log("");
const landing = await run("landing, at rest", async () => {
	await new Promise((done) => setTimeout(done, 800));
});
const transition = await run("landing → chat, a question sent", async (page) => {
	await page.click("#aspire-composer");
	await page.type("#aspire-composer", "What is an index fund?");
	await page.keyboard.press("Enter");
	await page
		.waitForFunction(() => !document.querySelector(".composer__send--stop"), { timeout: 30000 })
		.catch(() => {});
});

await browser.close();
process.exit(landing && transition ? 0 : 1);
