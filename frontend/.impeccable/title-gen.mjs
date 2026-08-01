/**
 * Title generation: fired once, never blocking, never overwriting a rename.
 *
 * The title endpoint is stubbed so the assertions are about *when and whether*
 * the client calls it, not about model output.
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";

const BASE = "http://localhost:4173/";
const CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,OPTIONS", "Access-Control-Allow-Headers": "Content-Type" };

let fails = 0;
const say = (l, ok, d = "") => { if (!ok) fails += 1; console.log(`  ${ok ? "PASS" : "FAIL"}  ${l}${d ? " — " + d : ""}`); };

const browser = await puppeteer.launch({ headless: "new" });

/** @param titleReply what /api/title returns; null means "declined". */
async function open({ titleReply = "Completion certificate details", titleDelayMs = 400 } = {}) {
	const page = await browser.newPage();
	await page.setViewport({ width: 1280, height: 800 });
	const calls = [];
	await page.setRequestInterception(true);
	page.on("request", async (r) => {
		if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
		if (r.url().endsWith("/chat")) {
			const sent = JSON.parse(r.postData() || "{}");
			return r.respond({ status: 200, contentType: "application/json", headers: CORS, body: JSON.stringify({ reply: "A certificate is issued on completion.", thread_id: sent.thread_id || "t-fixed", sources: [], follow_ups: [] }) });
		}
		if (r.url().endsWith("/api/title")) {
			calls.push(JSON.parse(r.postData() || "{}"));
			await new Promise((x) => setTimeout(x, titleDelayMs));
			return r.respond({ status: 200, contentType: "application/json", headers: CORS, body: JSON.stringify({ title: titleReply }) });
		}
		if (r.url().includes("/api/games/")) return r.respond({ status: 404, contentType: "application/json", headers: CORS, body: "{}" });
		r.continue();
	});
	await page.goto(BASE, { waitUntil: "networkidle2" });
	await page.evaluate(() => localStorage.clear());
	await page.reload({ waitUntil: "networkidle2" });
	return { page, calls };
}

const ask = async (page, q) => {
	await page.type("#aspire-composer", q);
	await page.keyboard.press("Enter");
	await page.waitForFunction(() => !document.querySelector(".composer__send--stop"), { timeout: 20000 });
	await new Promise((r) => setTimeout(r, 500));
};

const stored = (page) => page.evaluate(() => JSON.parse(localStorage.getItem("aspire.conversations.v1") || "[]"));

console.log("\n=== fires once, after the first answer, and does not block ===");
{
	const { page, calls } = await open({ titleDelayMs: 1500 });
	await ask(page, "Do I get a certificate when I finish?");

	// The answer is fully readable while the title call is still in flight.
	const beforeTitle = await stored(page);
	const answerUp = await page.evaluate(() =>
		(document.querySelector(".turn--assistant .answer")?.textContent || "").includes("certificate is issued"),
	);
	say("answer readable while the title is still in flight", answerUp, `answerVisible=${answerUp}`);
	say("title call fired once", calls.length === 1, JSON.stringify(calls.length));
	say("sent first message and answer", !!calls[0]?.message && !!calls[0]?.answer, JSON.stringify(Object.keys(calls[0] ?? {})));
	say("fallback title stored meanwhile", beforeTitle[0]?.title?.startsWith("Do I get a certificate"), JSON.stringify(beforeTitle[0]?.title));

	await new Promise((r) => setTimeout(r, 1800));
	const after = await stored(page);
	say("generated title replaces the fallback", after[0]?.title === "Completion certificate details", JSON.stringify(after[0]?.title));
	say("marked as generated", after[0]?.titleSource === "generated", String(after[0]?.titleSource));

	// A second turn must not fire it again.
	await ask(page, "And how long does it take?");
	say("not re-fired on a later message", calls.length === 1, `calls=${calls.length}`);
	const afterSecond = await stored(page);
	say("title survives a later turn", afterSecond[0]?.title === "Completion certificate details", JSON.stringify(afterSecond[0]?.title));
	await page.close();
}

console.log("\n=== NO_TITLE keeps the fallback ===");
{
	const { page, calls } = await open({ titleReply: null, titleDelayMs: 200 });
	await ask(page, "dfghjkl;");
	await new Promise((r) => setTimeout(r, 900));
	const s = await stored(page);
	say("call was made", calls.length === 1);
	say("fallback kept, nothing invented", s[0]?.title === "dfghjkl;", JSON.stringify(s[0]?.title));
	say("not marked generated", s[0]?.titleSource === undefined, String(s[0]?.titleSource));
	await page.close();
}

console.log("\n=== a failing endpoint is invisible ===");
{
	const page = await browser.newPage();
	await page.setViewport({ width: 1280, height: 800 });
	await page.setRequestInterception(true);
	page.on("request", (r) => {
		if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
		if (r.url().endsWith("/chat")) return r.respond({ status: 200, contentType: "application/json", headers: CORS, body: JSON.stringify({ reply: "An answer.", thread_id: "t1", sources: [], follow_ups: [] }) });
		if (r.url().endsWith("/api/title")) return r.respond({ status: 500, contentType: "application/json", headers: CORS, body: '{"detail":"boom"}' });
		if (r.url().includes("/api/games/")) return r.respond({ status: 404, contentType: "application/json", headers: CORS, body: "{}" });
		r.continue();
	});
	const errors = [];
	page.on("pageerror", (e) => errors.push(String(e)));
	await page.goto(BASE, { waitUntil: "networkidle2" });
	await page.evaluate(() => localStorage.clear());
	await page.reload({ waitUntil: "networkidle2" });
	await ask(page, "What is compound interest?");
	await new Promise((r) => setTimeout(r, 900));
	const s = await stored(page);
	say("no page error surfaced", errors.length === 0, JSON.stringify(errors));
	say("fallback kept on a 500", s[0]?.title === "What is compound interest?", JSON.stringify(s[0]?.title));
	await page.close();
}

console.log("\n=== language comes from the voice setting ===");
{
	const { page, calls } = await open({ titleReply: "Requisitos de elegibilidad" });
	await page.click(".tool-btn--icon");
	await new Promise((r) => setTimeout(r, 400));
	await page.evaluate(() => [...document.querySelectorAll(".voice-choice--lang")].find((b) => b.textContent.includes("ES"))?.click());
	await page.keyboard.press("Escape");
	await new Promise((r) => setTimeout(r, 300));
	await ask(page, "¿Quién puede unirse a ASPIRE?");
	await new Promise((r) => setTimeout(r, 900));
	say("language sent as es", calls[0]?.language === "es", JSON.stringify(calls[0]?.language));
	const s = await stored(page);
	say("Spanish title stored", s[0]?.title === "Requisitos de elegibilidad", JSON.stringify(s[0]?.title));
	await page.close();
}

console.log("\n=== reopening a titled chat never re-titles it ===");
{
	const { page, calls } = await open();
	await ask(page, "Do I get a certificate when I finish?");
	await new Promise((r) => setTimeout(r, 900));
	await page.reload({ waitUntil: "networkidle2" });
	await new Promise((r) => setTimeout(r, 700));
	// Reopen from the rail.
	await page.evaluate(() => document.querySelector(".chip-btn--square")?.click());
	await new Promise((r) => setTimeout(r, 500));
	await page.evaluate(() => document.querySelector(".history-item")?.click());
	await new Promise((r) => setTimeout(r, 1200));
	say("no second title call after reopen", calls.length === 1, `calls=${calls.length}`);
	const s = await stored(page);
	say("title survives refresh + reopen", s[0]?.title === "Completion certificate details", JSON.stringify(s[0]?.title));
	await page.close();
}

await browser.close();
console.log(`\n${fails === 0 ? "ALL CHECKS PASSED" : fails + " CHECK(S) FAILED"}`);
process.exit(fails === 0 ? 0 : 1);
