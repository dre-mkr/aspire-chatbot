/**
 * Pixel-exact before/after for a refactor that is not allowed to change the UI.
 *
 * Captures the same set of surfaces every time, into a named directory, then
 * diffs two captures pixel by pixel. The point is that "looks the same" is not
 * a claim anyone can make honestly by eye across six phases — a 2px shift in a
 * chip row is invisible in review and obvious to a user.
 *
 *   node .impeccable/phase-shots.mjs capture before
 *   ...make changes, rebuild...
 *   node .impeccable/phase-shots.mjs capture after
 *   node .impeccable/phase-shots.mjs diff before after
 *
 * Animation is the enemy of a stable screenshot, so every capture pins the
 * clock: entrance animations are forced to their finished frame and the
 * ambient gradient is stopped. That is done through an injected stylesheet
 * rather than by editing the app, so what is measured is the shipped CSS.
 *
 * Review-only. Never built or shipped.
 */
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer";
import { handleChatStream } from "./fake-stream.mjs";


const [mode, a, b] = process.argv.slice(2);
const BASE = "http://localhost:4173";
const OUT = fileURLToPath(new URL("./flash-out/shots", import.meta.url));
const CORS = {
	"Access-Control-Allow-Origin": "*",
	"Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
	"Access-Control-Allow-Headers": "Content-Type, Authorization, X-Aspire-Device",
};

const REPLY =
	"An **index fund** holds a little of every company on a list.\n\nThat matters because nobody can reliably pick the winners in advance.\n\n- You own a slice of hundreds at once\n- Fees are low";
const SOURCES = [
	{ content: "An index fund tracks a market index.", metadata: { question: "What is an index fund?" } },
	{ content: "Low fees compound over decades.", metadata: { category: "Investing basics" } },
];

/** Everything that moves, stopped. Injected, so the real stylesheet is what renders. */
const FREEZE = `
*, *::before, *::after {
  animation-duration: 1ms !important;
  animation-delay: 0ms !important;
  transition-duration: 1ms !important;
  transition-delay: 0ms !important;
  caret-color: transparent !important;
}
.atmosphere span, .orb--hero, .orb--hero::before, .orb--thinking { animation: none !important; }
`;

async function surfaces(label) {
	mkdirSync(`${OUT}/${label}`, { recursive: true });
	const browser = await puppeteer.launch({ headless: "new", args: ["--force-device-scale-factor=1"] });

	const shot = async (name, { path = "/", width = 1280, height = 900, after } = {}) => {
		const page = await browser.newPage();
		await page.setViewport({ width, height, deviceScaleFactor: 1 });
		await page.setRequestInterception(true);
		page.on("request", async (r) => {
			if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
			// `/chat/stream` is the transport now; `/chat` stays as the fallback.
		// Both are served from the same fixture so they cannot drift apart.
		if (
			handleChatStream(r, (body) =>
				r.respond({ status: 200, contentType: "text/event-stream", headers: CORS, body }),
				{ reply: REPLY, sources: SOURCES, followUps: ["How much do I need to start?", "What is compound interest?"] },
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
						follow_ups: ["How much do I need to start?", "What is compound interest?"],
					}),
				});
			}
			if (r.url().endsWith("/api/title")) {
				return r.respond({ status: 200, contentType: "application/json", headers: CORS, body: '{"title":"Index fund basics"}' });
			}
			if (r.url().includes("/api/")) return r.respond({ status: 404, contentType: "application/json", headers: CORS, body: "{}" });
			r.continue();
		});
		await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
		await page.evaluate(() => localStorage.clear());
		await page.goto(`${BASE}${path}`, { waitUntil: "networkidle2" });
		await page.addStyleTag({ content: FREEZE });
		if (after) await after(page);
		await page.addStyleTag({ content: FREEZE });
		await new Promise((r) => setTimeout(r, 500));
		await page.screenshot({ path: `${OUT}/${label}/${name}.png` });
		await page.close();
	};

	const ask = async (page, text = "What is an index fund?") => {
		await page.click("#aspire-composer");
		await page.type("#aspire-composer", text);
		await page.keyboard.press("Enter");
		await page.waitForFunction(() => !document.querySelector(".composer__send--stop"), { timeout: 25000 });
		await new Promise((r) => setTimeout(r, 900));
	};

	await shot("landing-1280");
	await shot("landing-320", { width: 320, height: 780 });
	await shot("landing-simple-on", { path: "/?simple=true" });
	await shot("chat-1280", { after: ask });
	await shot("chat-320", { width: 320, height: 780, after: ask });
	await shot("chat-sources-open", {
		after: async (page) => {
			await ask(page);
			await page.evaluate(() => document.querySelector(".sources__toggle")?.click());
			await new Promise((r) => setTimeout(r, 700));
		},
	});
	await shot("chat-rail-open", {
		after: async (page) => {
			await ask(page);
			await page.evaluate(() => document.querySelector(".rail-open, .titlebar button")?.click());
			await new Promise((r) => setTimeout(r, 500));
		},
	});

	await browser.close();
	console.log(`captured → ${OUT}/${label}`);
}

/** Pixel diff, in the browser's own decoder. */
async function diff(one, two) {
	const browser = await puppeteer.launch({ headless: "new" });
	const page = await browser.newPage();
	const names = readdirSync(`${OUT}/${one}`).filter((f) => f.endsWith(".png"));
	let worst = 0;
	let failed = 0;

	for (const name of names) {
		const A = readFileSync(`${OUT}/${one}/${name}`).toString("base64");
		const B = readFileSync(`${OUT}/${two}/${name}`).toString("base64");
		const result = await page.evaluate(
			async (x, y) => {
				const load = (d) =>
					new Promise((res, rej) => {
						const i = new Image();
						i.onload = () => res(i);
						i.onerror = rej;
						i.src = `data:image/png;base64,${d}`;
					});
				const [ia, ib] = await Promise.all([load(x), load(y)]);
				if (ia.width !== ib.width || ia.height !== ib.height) {
					return { sizeMismatch: `${ia.width}x${ia.height} vs ${ib.width}x${ib.height}` };
				}
				const c = document.createElement("canvas");
				c.width = ia.width;
				c.height = ia.height;
				const ctx = c.getContext("2d", { willReadFrequently: true });
				ctx.drawImage(ia, 0, 0);
				const da = ctx.getImageData(0, 0, c.width, c.height).data;
				ctx.clearRect(0, 0, c.width, c.height);
				ctx.drawImage(ib, 0, 0);
				const db = ctx.getImageData(0, 0, c.width, c.height).data;
				let differing = 0;
				let maxDelta = 0;
				let firstRow = -1;
				for (let i = 0; i < da.length; i += 4) {
					const d = Math.max(Math.abs(da[i] - db[i]), Math.abs(da[i + 1] - db[i + 1]), Math.abs(da[i + 2] - db[i + 2]));
					// 2/255 absorbs jpeg-free PNG noise from subpixel AA only.
					if (d > 2) {
						differing += 1;
						if (d > maxDelta) maxDelta = d;
						if (firstRow === -1) firstRow = Math.floor(i / 4 / c.width);
					}
				}
				return { differing, maxDelta, firstRow, total: c.width * c.height };
			},
			A,
			B,
		);

		if (result.sizeMismatch) {
			failed += 1;
			console.log(`  FAIL  ${name} — size changed: ${result.sizeMismatch}`);
			continue;
		}
		const pct = (result.differing / result.total) * 100;
		worst = Math.max(worst, pct);
		const ok = result.differing === 0;
		if (!ok) failed += 1;
		console.log(
			`  ${ok ? "PASS" : "FAIL"}  ${name} — ${result.differing} px differ (${pct.toFixed(4)}%)${
				result.differing ? `, max Δ${result.maxDelta}, first at row ${result.firstRow}` : ""
			}`,
		);
	}

	await browser.close();
	writeFileSync(`${OUT}/diff-${one}-${two}.json`, JSON.stringify({ worst, failed }, null, 2));
	console.log(`\n${failed === 0 ? "IDENTICAL" : `${failed} SURFACE(S) CHANGED`}`);
	process.exit(failed === 0 ? 0 : 1);
}

if (mode === "capture") await surfaces(a);
else if (mode === "diff") await diff(a, b);
else console.log("usage: phase-shots.mjs capture <label> | diff <a> <b>");
