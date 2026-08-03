/**
 * Two claims the last review disproved, re-tested.
 *
 *   A. Stopping MID-REVEAL keeps only the words already revealed. It used to
 *      call finishStream(), which appends `state.answer` -- the whole reply --
 *      so for the entire length of the typewriter the "Stop generating" button
 *      was a reveal-everything button, and no stopped notice was created.
 *   B. Stopping leaves focus somewhere real. Distinct keys make React unmount
 *      the pressed button, so activeElement fell to <body> and a keyboard user
 *      was dropped out of the tab ring at the moment they asked for an exit.
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";

const BASE = "http://localhost:4173/";
const CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS", "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Aspire-Device" };
const LONG = Array.from({ length: 120 }, (_, i) => `word${i + 1}`).join(" ");

const browser = await puppeteer.launch({ headless: "new" });

async function trial(label, press) {
	const page = await browser.newPage();
	await page.setViewport({ width: 1280, height: 900 });
	await page.setRequestInterception(true);
	page.on("request", (r) => {
		if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
		if (r.url().endsWith("/chat")) return r.respond({ status: 200, contentType: "application/json", headers: CORS, body: JSON.stringify({ reply: LONG, thread_id: "t", sources: [], follow_ups: ["follow up one"] }) });
		if (r.url().includes("/api/games/")) return r.respond({ status: 404, contentType: "application/json", headers: CORS, body: "{}" });
		r.continue();
	});
	await page.goto(BASE, { waitUntil: "networkidle2" });

	await page.type("#aspire-composer", "Tell me a long answer");
	await page.keyboard.press("Enter");

	// Let the typewriter get partway, then stop.
	await page.waitForFunction(() => (document.querySelector(".turn--assistant .answer")?.textContent.match(/word\d+/g) || []).length > 20, { timeout: 15000 });
	const atPress = await page.evaluate(() => (document.querySelector(".turn--assistant .answer")?.textContent.match(/word\d+/g) || []).length);

	await press(page);
	await new Promise((r) => setTimeout(r, 1500));

	const after = await page.evaluate(() => ({
		words: (document.querySelector(".turn--assistant .answer")?.textContent.match(/word\d+/g) || []).length,
		stopNotice: !!document.querySelector('.failure[data-tone="stopped"]'),
		followUps: document.querySelectorAll(".follow-up").length,
		focus: document.activeElement?.id || document.activeElement?.className || document.activeElement?.tagName,
		heading: !!document.querySelector('.failure[data-tone="stopped"]')?.closest(".answer")?.querySelector("h2.sr-only"),
	}));

	console.log(`\n--- ${label} ---`);
	console.log(`  words at press : ${atPress}   after: ${after.words}   (full reply = 120)`);
	console.log(`  kept only revealed            : ${after.words < 120 ? "PASS" : "FAIL — settled the whole reply"}`);
	console.log(`  stopped notice present        : ${after.stopNotice ? "PASS" : "FAIL"}`);
	console.log(`  no follow-ups on a stopped turn: ${after.followUps === 0 ? "PASS" : "FAIL"}`);
	console.log(`  heading on the stopped turn   : ${after.heading ? "PASS" : "FAIL"}`);
	console.log(`  focus after stop              : ${after.focus} → ${after.focus === "aspire-composer" ? "PASS" : "FAIL"}`);
	await page.close();
}

await trial("MOUSE", async (page) => { await page.click(".composer__send--stop"); });
await trial("KEYBOARD", async (page) => {
	await page.evaluate(() => document.querySelector(".composer__send--stop").focus());
	await page.keyboard.press("Enter");
});

await browser.close();
