/**
 * Blast radius of `.answer p`.
 *
 * `.answer p` is specificity (0,1,1). Every widget's own paragraph rules are
 * single-class, (0,1,0). Every widget renders inside `.answer`. So each <p> in
 * a card takes the answer-prose font-size, line-height, colour and margin no
 * matter what the widget declared. This lists every <p> that is actually
 * losing, with declared vs computed.
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";
import { readFile } from "node:fs/promises";

const BASE = "http://localhost:4173";
const API = "http://localhost:8000";
const CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS", "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Aspire-Device" };

/* Declared font-size per class, straight out of the stylesheet. */
const css = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");
const declared = {};
for (const m of css.matchAll(/^\.([a-z0-9_-]+)\s*\{([^}]*)\}/gim)) {
	const fs = /font-size:\s*([^;]+);/.exec(m[2]);
	if (fs) declared[m[1]] = fs[1].trim();
}

const browser = await puppeteer.launch({ headless: "new" });
const settle = (ms = 700) => new Promise((r) => setTimeout(r, ms));

async function surface(kind, gameType) {
	const p = await browser.newPage();
	await p.setViewport({ width: 1280, height: 1400 });
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
				.then(() => r.respond({
					status: 200, contentType: "application/json", headers: CORS,
					body: JSON.stringify({ reply: "", thread_id: threadId, sources: [], follow_ups: [], ...announce }),
				}));
		}
		r.continue();
	});
	await p.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await p.type("#aspire-composer", "go");
	await p.keyboard.press("Enter");
	await p.waitForSelector(kind === "elig" ? ".elig" : ".game", { timeout: 20000 });
	await settle();
	return p;
}

const collect = (p) =>
	p.evaluate(() =>
		[...document.querySelectorAll(".game p, .elig p")].map((el) => {
			const s = getComputedStyle(el);
			return {
				cls: el.className,
				fs: s.fontSize,
				lh: s.lineHeight,
				color: s.color,
				margin: s.margin,
				text: (el.textContent ?? "").trim().slice(0, 34),
			};
		}),
	);

const rem = (v) => (v.endsWith("rem") ? `${Number.parseFloat(v) * 16}px` : v);
const rows = [];
const seen = new Set();

for (const [kind, gameType] of [["game", "word_scramble"], ["game", "true_false"], ["elig", null]]) {
	const p = await surface(kind, gameType);
	for (const el of await collect(p)) {
		const key = el.cls;
		if (seen.has(key)) continue;
		seen.add(key);
		const own = el.cls.split(/\s+/).find((c) => declared[c]);
		const want = own ? rem(declared[own]) : null;
		rows.push({
			cls: el.cls,
			declared: want ?? "(none)",
			computed: el.fs,
			lost: want !== null && want !== el.fs,
			text: el.text,
		});
	}
	await p.close();
}

await browser.close();

const lost = rows.filter((r) => r.lost);
console.log(`\nParagraphs inside widget cards: ${rows.length}`);
console.log(`Overridden by \`.answer p\`:      ${lost.length}\n`);
console.log("CLASS".padEnd(30), "DECLARED".padEnd(11), "COMPUTED".padEnd(10), "TEXT");
for (const r of rows) {
	console.log(
		(r.lost ? "✗ " : "  ") + r.cls.padEnd(28),
		r.declared.padEnd(11),
		r.computed.padEnd(10),
		r.text,
	);
}
