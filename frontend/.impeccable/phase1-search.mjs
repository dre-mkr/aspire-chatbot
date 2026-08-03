/**
 * Phase 1: the plain-words toggle lives in the URL.
 *
 * The refactor moved `simpleMode` out of component state and into a validated
 * search param. That is only an improvement if it is invisible: the control
 * must look and behave exactly as it did, existing links must resolve exactly
 * as they did, and the setting must survive the navigations that previously
 * could not disturb it because it was React state.
 *
 * The two hazards this exists to catch:
 *
 *   - A default that writes itself down. `?simple=false` on every URL would
 *     change every link the product produces.
 *   - Search dropped on navigation. TanStack Router resets search unless the
 *     navigation carries it, so the first send of a chat would silently turn
 *     the setting off at the moment the answer was being composed.
 *
 *   node .impeccable/preview-server.mjs &
 *   node .impeccable/phase1-search.mjs
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";

const BASE = process.argv[2] ?? "http://localhost:4173";
const CORS = {
	"Access-Control-Allow-Origin": "*",
	"Access-Control-Allow-Methods": "GET,POST,OPTIONS",
	"Access-Control-Allow-Headers": "Content-Type, Authorization, X-Aspire-Device",
};

let fails = 0;
const say = (label, ok, detail = "") => {
	if (!ok) fails += 1;
	console.log(`  ${ok ? "PASS" : "FAIL"}  ${label}${detail ? " — " + detail : ""}`);
};

const browser = await puppeteer.launch({ headless: "new" });

async function open(path = "/") {
	const page = await browser.newPage();
	await page.setViewport({ width: 1280, height: 900 });
	const seen = { chat: [] };
	await page.setRequestInterception(true);
	page.on("request", async (r) => {
		if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
		if (r.url().endsWith("/chat")) {
			const sent = JSON.parse(r.postData() || "{}");
			seen.chat.push(sent);
			return r.respond({
				status: 200,
				contentType: "application/json",
				headers: CORS,
				body: JSON.stringify({
					reply: "An index fund holds a little of every company on a list.",
					thread_id: sent.thread_id || "t-server",
					sources: [],
					follow_ups: [],
				}),
			});
		}
		if (r.url().endsWith("/api/title")) {
			return r.respond({ status: 200, contentType: "application/json", headers: CORS, body: '{"title":"Index funds"}' });
		}
		if (r.url().includes("/api/")) {
			return r.respond({ status: 404, contentType: "application/json", headers: CORS, body: "{}" });
		}
		r.continue();
	});
	await page.goto(`${BASE}${path}`, { waitUntil: "networkidle2" });
	await page.evaluate(() => localStorage.clear());
	await page.goto(`${BASE}${path}`, { waitUntil: "networkidle2" });
	return { page, seen };
}

const url = (page) => page.evaluate(() => location.pathname + location.search);
const pressed = (page) =>
	page.evaluate(() => document.querySelector('[aria-pressed]')?.getAttribute("aria-pressed"));
const historyLength = (page) => page.evaluate(() => history.length);

const ask = async (page, text) => {
	await page.click("#aspire-composer");
	await page.type("#aspire-composer", text);
	await page.keyboard.press("Enter");
	await page.waitForFunction(() => !document.querySelector(".composer__send--stop"), { timeout: 20000 });
};

const toggle = async (page) => {
	await page.evaluate(() => document.querySelector('[aria-pressed]')?.click());
	await new Promise((r) => setTimeout(r, 150));
};

console.log("\n── the default state is not written down ─────────────");
{
	const { page } = await open("/");
	say("landing URL is clean", (await url(page)) === "/", await url(page));
	say("toggle starts off", (await pressed(page)) === "false", await pressed(page));

	await toggle(page);
	say("turning it on writes exactly ?simple=true", (await url(page)) === "/?simple=true", await url(page));
	say("the control reflects it", (await pressed(page)) === "true");

	await toggle(page);
	say("turning it off removes the param entirely", (await url(page)) === "/", await url(page));
	say("the control reflects that too", (await pressed(page)) === "false");
	await page.close();
}

console.log("\n── toggling does not add history entries ─────────────");
{
	const { page } = await open("/");
	const before = await historyLength(page);
	await toggle(page);
	await toggle(page);
	await toggle(page);
	const after = await historyLength(page);
	// It was React state before this change, so it could not push history.
	// `replace: true` is what keeps that true now.
	say("three toggles push nothing onto the stack", after === before, `${before} → ${after}`);
	await page.close();
}

console.log("\n── the setting survives navigation ──────────────────");
{
	const { page, seen } = await open("/");
	await toggle(page);
	say("armed before sending", (await url(page)) === "/?simple=true", await url(page));

	await ask(page, "What is an index fund?");
	const afterSend = await url(page);
	say("first send keeps the param through `/` → `/chat/:id`", /^\/chat\/[^?]+\?simple=true$/.test(afterSend), afterSend);
	say("the control is still on", (await pressed(page)) === "true");
	// The whole point of the setting: it must reach the service.
	say("the request carried simple_mode", seen.chat.at(-1)?.simple_mode === true, JSON.stringify(seen.chat.at(-1)?.simple_mode));

	// New chat, then back into the stored one via the rail.
	await page.evaluate(() => {
		const btn = [...document.querySelectorAll("button")].find((b) => /new chat/i.test(b.textContent || b.getAttribute("aria-label") || ""));
		btn?.click();
	});
	await new Promise((r) => setTimeout(r, 400));
	const afterNew = await url(page);
	say("New chat keeps it", afterNew === "/?simple=true", afterNew);

	await page.evaluate(() => document.querySelector(".history-item")?.click());
	await new Promise((r) => setTimeout(r, 500));
	const afterReopen = await url(page);
	say("reopening from the rail keeps it", /^\/chat\/[^?]+\?simple=true$/.test(afterReopen), afterReopen);
	await page.close();
}

console.log("\n── deep links still resolve ─────────────────────────");
{
	// A link produced before this change existed: no search at all.
	const { page } = await open("/");
	await ask(page, "What is an index fund?");
	const id = await page.evaluate(() => location.pathname);
	await page.close();

	const { page: p2 } = await browser.newPage().then(async (p) => ({ page: p }));
	await p2.setViewport({ width: 1280, height: 900 });
	await p2.goto(`${BASE}${id}`, { waitUntil: "networkidle2" });
	say("a bare /chat/:id link loads", (await p2.evaluate(() => location.pathname)) === id, await url(p2));
	say("and defaults the toggle to off", (await pressed(p2)) === "false", await pressed(p2));

	await p2.goto(`${BASE}${id}?simple=true`, { waitUntil: "networkidle2" });
	say("a shared ?simple=true link arrives armed", (await pressed(p2)) === "true", await url(p2));

	// Garbage must degrade, not throw.
	await p2.goto(`${BASE}${id}?simple=banana&nonsense=1`, { waitUntil: "networkidle2" });
	const survived = await p2.evaluate(() => !!document.querySelector("#aspire-composer"));
	say("an unrecognised value degrades to the default", survived && (await pressed(p2)) === "false", await url(p2));
	await p2.close();
}

console.log(`\n${fails === 0 ? "ALL PASS" : `${fails} FAIL`}`);
await browser.close();
process.exit(fails === 0 ? 0 : 1);
