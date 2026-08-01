/**
 * Phase 1 acceptance: the shell is edge-to-edge and there is exactly one
 * scrolling message list plus one independently scrolling sidebar.
 *
 * Checks, per viewport, in both phases:
 *   - no frame: shell fills the viewport, no outer radius, no outer shadow
 *   - no document scroll in either axis (the shell owns its own height)
 *   - exactly the intended scroll containers, and no others
 *   - the sidebar scrolls independently and runs the full viewport height
 *   - 100dvh not 100vh, so mobile Safari's shrinking toolbar leaves no gap
 *   - the brand gradient survives on the mark, the New chat button and the orb
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";

const BASE = "http://localhost:4173/";
const CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,OPTIONS", "Access-Control-Allow-Headers": "Content-Type" };
const A = { reply: "An index fund holds a little of every company.\n\n- One\n- Two", thread_id: "t", sources: [], follow_ups: ["More?"] };
const VIEWPORTS = [[320, 568], [375, 667], [768, 1024], [1024, 768], [1440, 900]];

let fails = 0;
const say = (l, ok, d = "") => { if (!ok) fails += 1; console.log(`    ${ok ? "PASS" : "FAIL"}  ${l}${d ? " — " + d : ""}`); };

const browser = await puppeteer.launch({ headless: "new" });

for (const [w, h] of VIEWPORTS) {
	for (const answered of [false, true]) {
		const page = await browser.newPage();
		await page.setViewport({ width: w, height: h });
		await page.setRequestInterception(true);
		page.on("request", (r) => {
			if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
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

		console.log(`\n  ${w}x${h} · ${answered ? "chat" : "landing"}`);

		const m = await page.evaluate(() => {
			const app = document.querySelector(".app");
			const frame = document.querySelector(".frame");
			const rail = document.getElementById("aspire-rail");
			const as = getComputedStyle(app);
			const fs = getComputedStyle(frame);
			const fr = frame.getBoundingClientRect();
			const rr = rail.getBoundingClientRect();

			// Anything that can actually scroll, anywhere in the tree.
			const scrollers = [];
			for (const el of document.querySelectorAll("*")) {
				const s = getComputedStyle(el);
				const oy = s.overflowY, ox = s.overflowX;
				const canY = (oy === "auto" || oy === "scroll") && el.scrollHeight > el.clientHeight + 1;
				const canX = (ox === "auto" || ox === "scroll") && el.scrollWidth > el.clientWidth + 1;
				if (canY || canX) scrollers.push(`${el.className || el.tagName}${canY ? "[y]" : ""}${canX ? "[x]" : ""}`);
			}

			const grad = (sel) => {
				const el = document.querySelector(sel);
				if (!el) return "missing";
				const s = getComputedStyle(el);
				const own = s.backgroundImage;
				if (own && own.includes("gradient")) return "gradient";
				const after = getComputedStyle(el, "::after").backgroundImage;
				return after && after.includes("gradient") ? "gradient(::after)" : own;
			};

			return {
				appHeight: as.height,
				usesDvh: (document.styleSheets, true),
				docScrollW: document.documentElement.scrollWidth,
				docScrollH: document.documentElement.scrollHeight,
				innerW: innerWidth, innerH: innerHeight,
				bodyOverflow: getComputedStyle(document.body).overflow,
				frameMargin: fs.margin,
				frameRadius: fs.borderRadius,
				frameShadow: fs.boxShadow,
				frameBox: { x: Math.round(fr.left), y: Math.round(fr.top), w: Math.round(fr.width), h: Math.round(fr.height) },
				railBox: { x: Math.round(rr.left), y: Math.round(rr.top), w: Math.round(rr.width), h: Math.round(rr.height) },
				railBodyScrolls: (() => { const b = document.querySelector(".rail__body"); return b ? getComputedStyle(b).overflowY : null; })(),
				threadScrolls: (() => { const t = document.querySelector(".thread"); return t ? getComputedStyle(t).overflowY : null; })(),
				scrollers,
				brandMark: grad(".rail__mark"),
				brandNew: grad(".btn-new"),
				brandOrb: grad(".orb"),
			};
		});

		say("shell fills the viewport height", Math.abs(parseFloat(m.appHeight) - m.innerH) <= 1, `${m.appHeight} vs ${m.innerH}px`);
		say("no outer frame margin", m.frameMargin === "0px", m.frameMargin);
		say("no outer radius", m.frameRadius === "0px", m.frameRadius);
		say("no outer shadow", m.frameShadow === "none", m.frameShadow);
		say("frame is edge-to-edge", m.frameBox.x === 0 && m.frameBox.w === m.innerW, JSON.stringify(m.frameBox));
		say("no document vertical scroll", m.docScrollH <= m.innerH, `${m.docScrollH} vs ${m.innerH}`);
		say("no horizontal overflow", m.docScrollW <= m.innerW, `${m.docScrollW} vs ${m.innerW}`);
		// `.thread` is the message list, `.rail__body` the sidebar, and
		// `.starters__row` the deliberate mobile chip carousel. TEXTAREA is the
		// composer: a multi-line input that cannot scroll its own overflow is
		// broken, so it is an input affordance rather than a page scroll region.
		say("only intended scrollers", m.scrollers.every((s) => /thread|rail__body|starters__row|TEXTAREA/.test(s)), JSON.stringify(m.scrollers));
		say("sidebar scrolls independently", m.railBodyScrolls === "auto", String(m.railBodyScrolls));
		if (answered && w > 860) {
			say("sidebar runs full viewport height", m.railBox.y === 0 && m.railBox.h === m.innerH, JSON.stringify(m.railBox));
		}
		say("brand gradient kept (mark/new/orb)", [m.brandMark, m.brandNew, m.brandOrb].every((v) => String(v).includes("gradient")), `${m.brandMark} | ${m.brandNew} | ${m.brandOrb}`);

		await page.close();
	}
}

// 100dvh, not 100vh: the value that stops mobile Safari leaving a gap when the
// toolbar collapses. Read from the stylesheet text, since computed style
// resolves it to pixels.
const page = await browser.newPage();
await page.goto(BASE, { waitUntil: "networkidle2" });
const css = await page.evaluate(async () => {
	const link = [...document.querySelectorAll('link[rel=stylesheet]')].map((l) => l.href).find((h) => h.includes("styles"));
	return link ? (await fetch(link)).text() : "";
});
await page.close();
const appRule = css.match(/\.app\{[^}]*\}/)?.[0] ?? "";
console.log("\n  viewport unit");
say("shell uses 100dvh, not 100vh", appRule.includes("100dvh") && !/height:100vh/.test(appRule), appRule.match(/height:[^;]+/)?.[0] ?? "not found");

await browser.close();
console.log(`\n${fails === 0 ? "PHASE 1: ALL CHECKS PASSED" : fails + " CHECK(S) FAILED"}`);
process.exit(fails === 0 ? 0 : 1);
