/**
 * Acceptance for removing the top bar and relocating its contents.
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";
import { serveStream } from "./fake-stream.mjs";
import { serveAnonymousAuth } from "./fake-conversations.mjs";

const BASE = "http://localhost:4173/";
const CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS", "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Aspire-Device" };
const A = { reply: "An index fund holds a little of every company.\n\n- One\n- Two", thread_id: "t", sources: [], follow_ups: ["More?"] };

let fails = 0;
const say = (l, ok, d = "") => { if (!ok) fails += 1; console.log(`    ${ok ? "PASS" : "FAIL"}  ${l}${d ? " — " + d : ""}`); };

const browser = await puppeteer.launch({ headless: "new" });

async function open(w, h, answered) {
	const page = await browser.newPage();
	await page.setViewport({ width: w, height: h });
	await page.setRequestInterception(true);
	page.on("request", (r) => {
		if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
		if (serveAnonymousAuth(r, CORS)) return;
		// The real transport. Without this the client falls back to `/chat`,
		// and this suite only passes while nothing is listening on :8000.
		if (serveStream(r, CORS, (sent) => { void sent; return { reply: A.reply, followUps: A.follow_ups }; })) return;
		if (r.url().endsWith("/chat")) return r.respond({ status: 200, contentType: "application/json", headers: CORS, body: JSON.stringify(A) });
		if (r.url().includes("/api/games/")) return r.respond({ status: 404, contentType: "application/json", headers: CORS, body: "{}" });
		r.continue();
	});
	await page.goto(BASE, { waitUntil: "networkidle2" });
	if (answered) {
		await page.type("#aspire-composer", "What is an index fund?");
		await page.keyboard.press("Enter");
		await page.waitForFunction(() => !document.querySelector(".composer__send--stop"), { timeout: 20000 });
		await new Promise((r) => setTimeout(r, 700));
	}
	return page;
}

for (const [name, w, h] of [["desktop", 1280, 800], ["mobile", 390, 844], ["narrow", 320, 568]]) {
	console.log(`\n=== ${name} ${w}x${h} ===`);
	const page = await open(w, h, true);

	// --- the bar is gone ---
	const gone = await page.evaluate(() => ({
		bar: !!document.querySelector(".topbar"),
		pill: !!document.querySelector(".chip-btn--model"),
		caption: !!document.querySelector(".topbar__caption"),
		barSave: [...document.querySelectorAll(".topbar .chip-btn")].length,
	}));
	say("top bar removed", !gone.bar && !gone.pill && !gone.caption && gone.barSave === 0, JSON.stringify(gone));

	// --- composer row order and sizes ---
	const row = await page.evaluate(() => {
		const items = [...document.querySelectorAll(".composer__tools button, .composer__tools .voice-settings button")]
			.filter((b) => b.offsetParent !== null)
			.map((b) => ({ cls: b.className.split(" ")[0], x: Math.round(b.getBoundingClientRect().left), w: Math.round(b.getBoundingClientRect().width), h: Math.round(b.getBoundingClientRect().height) }))
			.sort((a, b) => a.x - b.x);
		return items;
	});
	const order = row.map((r) => r.cls);
	say("order [settings][simply]…[mic][send]",
		order[0] === "tool-btn" && order[1] === "tool-btn" && order.includes("composer__mic") && order.includes("composer__send"),
		JSON.stringify(order));
	say("no horizontal overflow", await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "");
	say("'Explain it simply' not pushed out", await page.evaluate(() => {
		const b = [...document.querySelectorAll(".tool-btn")].find((x) => x.textContent.includes("Explain"));
		if (!b) return false;
		const r = b.getBoundingClientRect();
		return r.width > 0 && r.right <= innerWidth + 1;
	}), "");

	// --- open the popover ---
	await page.click(".tool-btn--icon");
	await new Promise((r) => setTimeout(r, 500));
	const pop = await page.evaluate(() => {
		const p = document.querySelector(".voice-menu");
		const t = document.querySelector(".tool-btn--icon");
		if (!p) return null;
		const pr = p.getBoundingClientRect();
		const tr = t.getBoundingClientRect();
		return {
			present: true,
			opensUpward: pr.bottom <= tr.top + 2,
			isSheet: p.hasAttribute("data-sheet"),
			onScreen: pr.top >= -1 && pr.left >= -1 && pr.right <= innerWidth + 1 && pr.bottom <= innerHeight + 1,
			expanded: t.getAttribute("aria-expanded"),
			focusInside: p.contains(document.activeElement),
			switchRole: p.querySelector('[role="switch"]')?.getAttribute("aria-checked"),
			// Contents must be the originals, unchanged.
			sections: [...p.querySelectorAll(".voice-menu__label")].map((l) => l.textContent.trim()),
			sub: p.querySelector(".voice-menu__sub")?.textContent.trim(),
			speeds: [...p.querySelectorAll(".voice-choice:not(.voice-choice--lang)")].map((b) => b.textContent.trim()),
			langs: [...p.querySelectorAll(".voice-choice--lang")].map((b) => b.textContent.trim()),
			privacy: p.querySelector(".voice-menu__link")?.textContent.trim(),
		};
	});
	say("popover present", !!pop);
	if (pop) {
		say(pop.isSheet ? "bottom sheet below breakpoint" : "opens upward from composer", pop.isSheet || pop.opensUpward, `sheet=${pop.isSheet} upward=${pop.opensUpward}`);
		say("stays on screen", pop.onScreen);
		say("aria-expanded true", pop.expanded === "true", String(pop.expanded));
		say("focus moved inside", pop.focusInside);
		say("real switch role", pop.switchRole === "true" || pop.switchRole === "false", String(pop.switchRole));
		say("sections unchanged", JSON.stringify(pop.sections) === '["Voice","Speed","Language"]', JSON.stringify(pop.sections));
		say("sublabel unchanged", pop.sub === "Starts as each answer arrives.", String(pop.sub));
		say("speeds unchanged", JSON.stringify(pop.speeds) === '["0.75×","1×","1.25×","1.5×"]', JSON.stringify(pop.speeds));
		say("languages unchanged", JSON.stringify(pop.langs) === '["ENEnglish","ESEspañol","FRFrançais"]', JSON.stringify(pop.langs));
		say("privacy link kept", pop.privacy === "What we do with your voice", String(pop.privacy));
	}

	// --- Space inside the popover must not start recording ---
	const spaceSafe = await page.evaluate(async () => {
		const before = document.querySelector(".voice-live") !== null;
		const btn = document.querySelector(".voice-choice");
		btn?.focus();
		btn?.dispatchEvent(new KeyboardEvent("keydown", { key: " ", code: "Space", bubbles: true }));
		await new Promise((r) => setTimeout(r, 400));
		return { before, recordingAfter: document.querySelector(".voice-live") !== null, stillOpen: !!document.querySelector(".voice-menu") };
	});
	say("Space in popover does not record", !spaceSafe.recordingAfter, JSON.stringify(spaceSafe));

	// --- ESC closes and returns focus ---
	await page.keyboard.press("Escape");
	await new Promise((r) => setTimeout(r, 400));
	const closed = await page.evaluate(() => ({
		gone: !document.querySelector(".voice-menu"),
		focusOnTrigger: document.activeElement?.classList.contains("tool-btn--icon"),
		expanded: document.querySelector(".tool-btn--icon")?.getAttribute("aria-expanded"),
	}));
	say("ESC closes", closed.gone);
	say("focus returns to trigger", closed.focusOnTrigger, JSON.stringify(closed));
	say("aria-expanded false", closed.expanded === "false", String(closed.expanded));

	await page.close();
}

// --- rail row menu: Save chat, keyboard reachable ---
console.log("\n=== rail overflow menu (1280x800) ===");
{
	const page = await open(1280, 800, true);
	const menu = await page.evaluate(() => {
		const more = document.querySelector(".history-more");
		if (!more) return null;
		const focusable = more.tabIndex >= 0 || more.tagName === "BUTTON";
		more.click();
		return { focusable, label: more.getAttribute("aria-label") };
	});
	await new Promise((r) => setTimeout(r, 400));
	const item = await page.evaluate(() => {
		const m = document.querySelector(".row-menu");
		return m ? { items: [...m.querySelectorAll(".row-menu__item")].map((b) => b.textContent.trim()), hasIcon: !!m.querySelector("svg") } : null;
	});
	say("overflow trigger exists and is a button", !!menu?.focusable, JSON.stringify(menu));
	say("menu contains Save chat", item?.items.includes("Save chat"), JSON.stringify(item));
	say("download icon kept", !!item?.hasIcon);

	// keyboard reachable, not hover-only
	const kb = await page.evaluate(() => {
		document.querySelector(".row-menu__item")?.blur();
		const more = document.querySelector(".history-more");
		more.focus();
		return { focused: document.activeElement === more, opacity: getComputedStyle(more).opacity };
	});
	say("reachable by keyboard focus", kb.focused && Number(kb.opacity) > 0.9, JSON.stringify(kb));
	await page.close();
}

// --- identity line moved to the empty state ---
console.log("\n=== identity line ===");
{
	const page = await open(1280, 800, false);
	const landing = await page.evaluate(() => {
		const el = document.querySelector(".hero__identity");
		return { text: el?.textContent.trim(), visible: !!el && el.getBoundingClientRect().height > 0 };
	});
	say("shown in the empty state", landing.visible && landing.text === "Financial literacy assistant · St. Kitts and Nevis", JSON.stringify(landing));
	await page.type("#aspire-composer", "hi");
	await page.keyboard.press("Enter");
	await page.waitForFunction(() => !document.querySelector(".composer__send--stop"), { timeout: 20000 });
	await new Promise((r) => setTimeout(r, 900));
	const inChat = await page.evaluate(() => {
		const hero = document.querySelector(".hero");
		return { heroOpacity: getComputedStyle(hero).opacity, heroInert: hero.hasAttribute("inert") };
	});
	say("gone once a conversation starts", inChat.heroOpacity === "0" && inChat.heroInert, JSON.stringify(inChat));
	await page.close();
}

await browser.close();
console.log(`\n${fails === 0 ? "ALL CHECKS PASSED" : fails + " CHECK(S) FAILED"}`);
process.exit(fails === 0 ? 0 : 1);
