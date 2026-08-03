/** Screenshots the card in one state. Usage: node elig-shot.mjs <lang> <state> <WxH> */
import puppeteer from "puppeteer";

const [, , LANG = "en", STATE = "question", VP = "760x1000"] = process.argv;
const [w, h] = VP.split("x").map(Number);
const API = "http://localhost:8000";
const CORS = {
	"Access-Control-Allow-Origin": "*",
	"Access-Control-Allow-Methods": "GET,POST,OPTIONS",
	"Access-Control-Allow-Headers": "Content-Type, Authorization, X-Aspire-Device",
};

const b = await puppeteer.launch({ headless: "new" });
const p = await b.newPage();
await p.setViewport({ width: w, height: h });
await p.setRequestInterception(true);
p.on("request", async (r) => {
	if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
	if (r.url().endsWith("/chat")) {
		const threadId = JSON.parse(r.postData() ?? "{}").thread_id;
		await fetch(`${API}/api/eligibility/start`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ thread_id: threadId, language: LANG }),
		});
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
	if (r.url().includes("/api/games/"))
		return r.respond({ status: 404, contentType: "application/json", headers: CORS, body: "{}" });
	r.continue();
});
await p.evaluateOnNewDocument((lang) => {
	window.localStorage.setItem(
		"aspire.voice.prefs.v1",
		JSON.stringify({ autoSpeak: false, speed: 1, language: lang }),
	);
}, LANG);

await p.goto("http://localhost:4173/", { waitUntil: "networkidle2" });
await p.type("#aspire-composer", "can I join ASPIRE?");
await p.keyboard.press("Enter");
await p.waitForSelector(".elig", { timeout: 15000 });
await new Promise((r) => setTimeout(r, 500));

const tap = async (i) => {
	await p.evaluate((n) => {
		const els = [...document.querySelectorAll(".elig__option")];
		(n < 0 ? els.at(n) : els[n])?.click();
	}, i);
	await p.waitForNetworkIdle({ idleTime: 250, timeout: 8000 }).catch(() => {});
	await new Promise((r) => setTimeout(r, 250));
};

if (STATE === "eligible") {
	for (const i of [1, 0, 0, 0, 0]) await tap(i);
} else if (STATE === "notyet") {
	// Under 5, aged 2: the "not yet" that has to read as a date in the diary.
	for (const i of [0, 2, 0, 0, 0, 0]) await tap(i);
} else if (STATE === "unsure") {
	for (let i = 0; i < 6; i += 1) {
		if (await p.$(".elig__result")) break;
		await tap(-1);
	}
}

await new Promise((r) => setTimeout(r, 400));
const card = await p.$(".elig");
await card.screenshot({ path: `.impeccable/elig-${LANG}-${STATE}.png` });
await b.close();
console.log(`wrote .impeccable/elig-${LANG}-${STATE}.png`);
