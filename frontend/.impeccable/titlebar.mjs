/**
 * The title bar, and the sidebar reading the same stored title.
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";
import { serveStream } from "./fake-stream.mjs";
import { createConversationStore } from "./fake-conversations.mjs";

const BASE = "http://localhost:4173/";
const CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS", "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Aspire-Device" };

let fails = 0;
const say = (l, ok, d = "") => { if (!ok) fails += 1; console.log(`  ${ok ? "PASS" : "FAIL"}  ${l}${d ? " — " + d : ""}`); };

const browser = await puppeteer.launch({ headless: "new" });

async function open(w = 1280, h = 800, titleReply = "Completion certificate details", delay = 300) {
	const page = await browser.newPage();
	await page.setViewport({ width: w, height: h });
	const calls = [];
	// A real backend echoes a thread id it was given and mints a fresh one when
	// there is none. Returning a constant would collapse every "New chat" into
	// the same stored record.
	let minted = 0;
	// History is server state now. The stub has to BE that service, or the
	// rail is empty and every assertion about titles is an assertion about
	// nothing. See fake-conversations.mjs.
	const store = createConversationStore();
	await page.setRequestInterception(true);
	page.on("request", async (r) => {
		if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
		if (await store.handle(r, (status, body) => r.respond({ status, contentType: "application/json", headers: CORS, body: body === null ? "" : JSON.stringify(body) }))) return;
		// The real transport. Without this the client falls back to `/chat`,
		// and this suite only passes while nothing is listening on :8000.
		if (serveStream(r, CORS, (sent) => {
			const id = sent.thread_id || "t-fixed";
			store.openConversation(id, store.ownerOf(r), sent.message);
			store.recordTurn(id, null, sent.message, { role: "assistant", text: "A certificate is issued on completion.", sources: [], follow_ups: [] });
			return { reply: "A certificate is issued on completion." };
		})) return;
		if (r.url().endsWith("/chat")) {
			const sent = JSON.parse(r.postData() || "{}");
			return r.respond({ status: 200, contentType: "application/json", headers: CORS, body: JSON.stringify({ reply: "A certificate is issued on completion.", thread_id: sent.thread_id || `t-${++minted}`, sources: [], follow_ups: [] }) });
		}
		if (r.url().endsWith("/api/title")) {
			calls.push(JSON.parse(r.postData() || "{}"));
			await new Promise((x) => setTimeout(x, delay));
			return r.respond({ status: 200, contentType: "application/json", headers: CORS, body: JSON.stringify({ title: titleReply }) });
		}
		if (r.url().includes("/api/games/")) return r.respond({ status: 404, contentType: "application/json", headers: CORS, body: "{}" });
		r.continue();
	});
	await page.goto(BASE, { waitUntil: "networkidle2" });
	await page.evaluate(() => localStorage.clear());
	await page.reload({ waitUntil: "networkidle2" });
	return { page, calls, store };
}
const ask = async (page, q) => {
	await page.type("#aspire-composer", q);
	await page.keyboard.press("Enter");
	await page.waitForFunction(() => !document.querySelector(".composer__send--stop"), { timeout: 20000 });
	await new Promise((r) => setTimeout(r, 400));
};
/**
 * What the service holds, which is where conversations live now.
 *
 * This read `localStorage.getItem("aspire.conversations.v1")` — a key that
 * stopped existing when history moved off the device. It returned `[]` every
 * time, so every assertion under it was comparing against nothing and the
 * suite reported the product broken while the product was fine.
 */
const stored = (store) =>
	[...store.rows.entries()]
		.sort((a, b) => b[1].updatedAt - a[1].updatedAt)
		.map(([threadId, row]) => ({ threadId, title: row.title, titleSource: row.titleSource ?? undefined }));

console.log("\n=== no bar on the empty state ===");
{
	const { page, store } = await open();
	say("no bar before the first message", !(await page.$(".titlebar")));
	await ask(page, "Do I get a certificate?");
	say("bar appears in the chat phase", !!(await page.$(".titlebar")));
	await page.close();
}

console.log("\n=== crossfade, no layout shift ===");
{
	const { page, store } = await open(1280, 800, "Completion certificate details", 1200);
	await ask(page, "Do I get a certificate when I finish?");
	const before = await page.evaluate(() => {
		const b = document.querySelector(".titlebar");
		const t = document.querySelector(".thread");
		return { title: b.textContent.trim(), barH: Math.round(b.getBoundingClientRect().height), threadTop: Math.round(t.getBoundingClientRect().top), padTop: getComputedStyle(t).paddingTop };
	});
	say("shows the first message while generating", before.title.includes("Do I get a certificate"), JSON.stringify(before.title));
	await new Promise((r) => setTimeout(r, 1600));
	const after = await page.evaluate(() => {
		const b = document.querySelector(".titlebar");
		const t = document.querySelector(".thread");
		return { title: b.textContent.trim(), barH: Math.round(b.getBoundingClientRect().height), threadTop: Math.round(t.getBoundingClientRect().top), padTop: getComputedStyle(t).paddingTop, docTitle: document.title };
	});
	say("swapped to the generated title", after.title === "Completion certificate details", JSON.stringify(after.title));
	say("no layout shift (bar height)", before.barH === after.barH, `${before.barH} -> ${after.barH}`);
	say("no layout shift (thread)", before.threadTop === after.threadTop && before.padTop === after.padTop, `${before.padTop} -> ${after.padTop}`);
	say("document.title synced", after.docTitle.startsWith("Completion certificate details"), JSON.stringify(after.docTitle));
	await page.close();
}

console.log("\n=== bar and sidebar read the same title ===");
{
	const { page, store } = await open();
	await ask(page, "Do I get a certificate?");
	await new Promise((r) => setTimeout(r, 900));
	const both = await page.evaluate(() => ({
		bar: document.querySelector(".titlebar__text")?.textContent.trim(),
		row: document.querySelector(".history-item")?.textContent.trim(),
		rowTitleAttr: document.querySelector(".history-item")?.getAttribute("title"),
	}));
	say("sidebar shows the generated title", both.row === "Completion certificate details", JSON.stringify(both.row));
	say("bar and sidebar agree", both.bar === both.row, `${both.bar} | ${both.row}`);
	say("row has a tooltip", both.rowTitleAttr === both.row, JSON.stringify(both.rowTitleAttr));
	await page.close();
}

console.log("\n=== inline rename from the bar ===");
{
	const { page, store } = await open();
	await ask(page, "Do I get a certificate?");
	await new Promise((r) => setTimeout(r, 900));
	await page.click(".titlebar__title");
	await new Promise((r) => setTimeout(r, 250));
	await page.evaluate(() => { const i = document.querySelector(".titlebar__input"); i.value = ""; });
	await page.type(".titlebar__input", "My certificate question");
	await page.keyboard.press("Enter");
	await new Promise((r) => setTimeout(r, 500));
	const s = stored(store);
	say("rename commits on Enter", s[0]?.title === "My certificate question", JSON.stringify(s[0]?.title));
	say("marked manual", s[0]?.titleSource === "manual", String(s[0]?.titleSource));
	const row = await page.evaluate(() => document.querySelector(".history-item")?.textContent.trim());
	say("sidebar follows the rename", row === "My certificate question", JSON.stringify(row));

	// ESC cancels
	await page.click(".titlebar__title");
	await new Promise((r) => setTimeout(r, 250));
	await page.evaluate(() => { const i = document.querySelector(".titlebar__input"); i.value = "throwaway"; });
	await page.keyboard.press("Escape");
	await new Promise((r) => setTimeout(r, 400));
	const s2 = stored(store);
	say("ESC cancels", s2[0]?.title === "My certificate question", JSON.stringify(s2[0]?.title));
	await page.close();
}

console.log("\n=== a rename survives a regenerate on a DIFFERENT chat ===");
{
	const { page, store } = await open(1280, 800, "Second chat title");
	await ask(page, "First question about certificates");
	await new Promise((r) => setTimeout(r, 800));
	// rename chat one
	await page.click(".titlebar__title");
	await new Promise((r) => setTimeout(r, 250));
	await page.evaluate(() => { document.querySelector(".titlebar__input").value = ""; });
	await page.type(".titlebar__input", "Hand typed name");
	await page.keyboard.press("Enter");
	await new Promise((r) => setTimeout(r, 500));

	// start a second chat
	await page.evaluate(() => document.querySelector(".btn-new")?.click());
	await new Promise((r) => setTimeout(r, 400));
	await ask(page, "Second question about applying");
	await new Promise((r) => setTimeout(r, 900));

	// regenerate the SECOND chat from its row menu
	await page.evaluate(() => {
		const rows = [...document.querySelectorAll(".history-row")];
		const target = rows.find((r) => !r.textContent.includes("Hand typed name"));
		if (!target) throw new Error("expected two rows, saw: " + rows.map((r) => r.textContent.trim()).join(" | "));
		target.querySelector(".history-more").click();
	});
	await new Promise((r) => setTimeout(r, 400));
	await page.evaluate(() => [...document.querySelectorAll(".row-menu__item")].find((b) => b.textContent.includes("Regenerate"))?.click());
	await new Promise((r) => setTimeout(r, 1200));

	const s = stored(store);
	const renamed = s.find((c) => c.title === "Hand typed name");
	say("the renamed chat is untouched", !!renamed, JSON.stringify(s.map((c) => c.title)));
	say("it is still marked manual", renamed?.titleSource === "manual", String(renamed?.titleSource));
	await page.close();
}

console.log("\n=== mobile: hamburger in the bar, not duplicated ===");
{
	const { page, store } = await open(390, 844);
	await ask(page, "Do I get a certificate?");
	await new Promise((r) => setTimeout(r, 900));
	const m = await page.evaluate(() => ({
		inBar: !!document.querySelector(".titlebar__menu"),
		floating: !!document.querySelector(".rail-open"),
		docScrollW: document.documentElement.scrollWidth,
		vw: innerWidth,
	}));
	say("hamburger is in the bar", m.inBar);
	say("not duplicated as a floating control", !m.floating, `floating=${m.floating}`);
	say("no horizontal overflow", m.docScrollW <= m.vw, `${m.docScrollW} vs ${m.vw}`);
	await page.close();
}

console.log("\n=== 320px ===");
{
	const { page, store } = await open(320, 568, "A reasonably long generated chat title");
	await ask(page, "A fairly long opening question about certificates and eligibility");
	await new Promise((r) => setTimeout(r, 900));
	const m = await page.evaluate(() => {
		const t = document.querySelector(".titlebar__text");
		const b = document.querySelector(".titlebar");
		return {
			docScrollW: document.documentElement.scrollWidth, vw: innerWidth,
			ellipsis: getComputedStyle(t).textOverflow,
			singleLine: Math.round(t.getBoundingClientRect().height) <= 26,
			barRight: Math.round(b.getBoundingClientRect().right),
		};
	});
	say("no horizontal overflow at 320", m.docScrollW <= m.vw, `${m.docScrollW} vs ${m.vw}`);
	say("title ellipsises on one line", m.ellipsis === "ellipsis" && m.singleLine, JSON.stringify(m));
	await page.close();
}

console.log("\n=== scroll reconciliation ===");
{
	const { page, store } = await open();
	await ask(page, "Do I get a certificate?");
	const m = await page.evaluate(() => {
		const b = document.querySelector(".titlebar");
		const t = document.querySelector(".thread");
		const bs = getComputedStyle(b);
		return {
			barTranslucent: bs.backgroundColor.includes("0.7") || bs.backdropFilter !== "none",
			backdrop: bs.backdropFilter,
			mask: getComputedStyle(t).maskImage !== "none",
			padTop: getComputedStyle(t).paddingTop,
			barH: Math.round(b.getBoundingClientRect().height),
			scrollers: [...document.querySelectorAll("*")].filter((el) => {
				const s = getComputedStyle(el);
				return ["auto", "scroll"].includes(s.overflowY) && el.scrollHeight > el.clientHeight + 1;
			}).map((el) => el.className || el.tagName),
		};
	});
	say("bar is translucent + blurred", m.barTranslucent, m.backdrop);
	say("fade retained under it", m.mask, `mask=${m.mask}`);
	say("thread clears the bar", parseInt(m.padTop, 10) >= m.barH, `${m.padTop} vs bar ${m.barH}px`);
	say("thread is still the only scroller", m.scrollers.every((c) => /thread|rail__body|TEXTAREA/.test(c)), JSON.stringify(m.scrollers));
	await page.close();
}

await browser.close();
console.log(`\n${fails === 0 ? "ALL CHECKS PASSED" : fails + " CHECK(S) FAILED"}`);
process.exit(fails === 0 ? 0 : 1);
