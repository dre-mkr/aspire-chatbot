/** Screenshots each widget card as it actually ships. */
import puppeteer from "puppeteer";
const BASE = "http://localhost:4173";
const API = "http://localhost:8000";
const CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,OPTIONS", "Access-Control-Allow-Headers": "Content-Type" };
const [, , WIDTH = "1280"] = process.argv;

const browser = await puppeteer.launch({ headless: "new" });
const settle = (ms = 800) => new Promise((r) => setTimeout(r, ms));

async function shot(kind, gameType, out) {
	const p = await browser.newPage();
	await p.setViewport({ width: Number(WIDTH), height: 1400 });
	await p.setRequestInterception(true);
	p.on("request", (r) => {
		if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
		if (r.url().endsWith("/chat")) {
			const threadId = JSON.parse(r.postData() ?? "{}").thread_id;
			const url = kind === "elig" ? `${API}/api/eligibility/start` : `${API}/api/games/start`;
			const body = kind === "elig"
				? { thread_id: threadId, language: "en" }
				: { thread_id: threadId, persona: "orion", language: "en", game_type: gameType };
			const announce = kind === "elig"
				? { eligibility_started: { check: "aspire_eligibility", language: "en" } }
				: { game_started: { game_type: gameType } };
			return void fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
				.catch(() => {})
				.then(() => r.respond({ status: 200, contentType: "application/json", headers: CORS,
					body: JSON.stringify({ reply: "", thread_id: threadId, sources: [], follow_ups: [], ...announce }) }));
		}
		r.continue();
	});
	await p.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await p.type("#aspire-composer", "go");
	await p.keyboard.press("Enter");
	await p.waitForSelector(kind === "elig" ? ".elig" : ".game", { timeout: 20000 });
	await settle();
	const card = await p.$(kind === "elig" ? ".elig" : ".game");
	await card.screenshot({ path: `.impeccable/${out}` });
	console.log("wrote", out);
	await p.close();
}

await shot("game", "word_scramble", `card-scramble-${WIDTH}.png`);
await shot("game", "true_false", `card-tf-${WIDTH}.png`);
await shot("elig", null, `card-elig-${WIDTH}.png`);
await browser.close();
