/** Direct check: does --stmt resolve, and can data-scale ever be stella? */
import puppeteer from "puppeteer";
const BASE = "http://localhost:4173";
const API = "http://localhost:8000";
const CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS", "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Aspire-Device" };

const b = await puppeteer.launch({ headless: "new" });
const p = await b.newPage();
await p.setViewport({ width: 1280, height: 1200 });
await p.setRequestInterception(true);
p.on("request", (r) => {
	if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
	if (r.url().endsWith("/chat")) {
		const threadId = JSON.parse(r.postData() ?? "{}").thread_id;
		return void fetch(`${API}/api/games/start`, {
			method: "POST", headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ thread_id: threadId, persona: "stella", language: "en", game_type: "true_false" }),
		}).catch(() => {}).then(() => r.respond({
			status: 200, contentType: "application/json", headers: CORS,
			body: JSON.stringify({ reply: "", thread_id: threadId, sources: [], follow_ups: [], game_started: { game_type: "true_false" } }),
		}));
	}
	r.continue();
});
await p.goto(`${BASE}/`, { waitUntil: "networkidle2" });
await p.type("#aspire-composer", "play");
await p.keyboard.press("Enter");
await p.waitForSelector(".tf", { timeout: 20000 });
await new Promise((r) => setTimeout(r, 800));

console.log(JSON.stringify(await p.evaluate(() => {
	const card = document.querySelector(".tf");
	const st = document.querySelector(".tf__statement");
	const lb = document.querySelector(".game__eyebrow");
	const cs = getComputedStyle(card);
	return {
		cardClass: card.className,
		dataScale: card.dataset.scale,
		serverPersonaWasStella: true,
		rootFontSize: getComputedStyle(document.documentElement).fontSize,
		stmtVar: cs.getPropertyValue("--stmt").trim(),
		choiceHVar: cs.getPropertyValue("--choice-h").trim(),
		statementTag: st?.tagName,
		statementClass: st?.className,
		statementFontSize: st ? getComputedStyle(st).fontSize : null,
		statementText: st?.textContent?.slice(0, 50),
		labelClass: lb?.className,
		labelFontSize: lb ? getComputedStyle(lb).fontSize : null,
		labelText: lb?.textContent?.slice(0, 40),
		choiceH: document.querySelector(".tf__choice")?.getBoundingClientRect().height,
	};
}), null, 2));
await b.close();
