/**
 * The design review's regression suite. Run against the production preview.
 *
 *   node .impeccable/preview-server.mjs &
 *   node .impeccable/verify.mjs
 *
 * Three things a mechanical scan gets wrong on this app, all handled here:
 *
 *  1. CONTRAST. The detector compares text against gradient stops it never
 *     touches, and against text that is in the DOM but never painted. This
 *     blanks every glyph, screenshots, and reads the actual painted pixel under
 *     each glyph run via Range.getClientRects(), skipping any subtree under a
 *     zero-opacity / zero-size / inert ancestor. That is ground truth.
 *  2. TOUCH TARGETS. This codebase keeps controls visually small and carries the
 *     pointer target to 44px with an invisible ::after overlay, so
 *     getBoundingClientRect understates every one. Hit-test the extremes.
 *  3. OVERFLOW. The decorative .atmosphere blobs and the mobile starters
 *     carousel both extend past the viewport by design; only a document-level
 *     scrollWidth is a real defect.
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";
import { serveStream } from "./fake-stream.mjs";

const BASE = process.argv[2] ?? "http://localhost:4173/";
const CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS", "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Aspire-Device" };
const ANSWER = {
	reply: "An **index fund** holds a little of every company on a list.\n\n- You own a slice of hundreds at once\n- Fees are low",
	thread_id: "t",
	sources: [{ content: "An index fund tracks a market index, such as the S&P 500.", metadata: { question: "What is an index fund?" } }, { content: "Diversification reduces single-company risk.", metadata: { category: "Risk" } }],
	follow_ups: ["How much do I need to start?", "What is the difference between stocks and bonds?"],
};

const VIEWPORTS = [["desktop", 1280, 800], ["compact", 780, 900], ["mobile", 390, 844]];
let failures = 0;
const say = (label, ok, detail = "") => {
	if (!ok) failures += 1;
	console.log(`  ${ok ? "PASS" : "FAIL"}  ${label}${detail ? " — " + detail : ""}`);
};

const browser = await puppeteer.launch({ headless: "new" });

async function open(w, h, answered) {
	const page = await browser.newPage();
	await page.setViewport({ width: w, height: h });
	await page.setRequestInterception(true);
	page.on("request", (r) => {
		if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
		// The real transport. Without this the client falls back to `/chat`,
		// and this suite only passes while nothing is listening on :8000.
		if (serveStream(r, CORS, (sent) => { void sent; return { reply: ANSWER.reply, sources: ANSWER.sources, followUps: ANSWER.follow_ups }; })) return;
		if (r.url().endsWith("/chat")) return r.respond({ status: 200, contentType: "application/json", headers: CORS, body: JSON.stringify(ANSWER) });
		if (r.url().includes("/api/games/")) return r.respond({ status: 404, contentType: "application/json", headers: CORS, body: "{}" });
		r.continue();
	});
	await page.goto(BASE, { waitUntil: "networkidle2", timeout: 30000 });
	if (answered) {
		await page.type("#aspire-composer", "What is an index fund?");
		await page.keyboard.press("Enter");
		await page.waitForFunction(() => !document.querySelector(".composer__send--stop"), { timeout: 20000 });
		await new Promise((r) => setTimeout(r, 500));
	}
	return page;
}

async function contrast(page) {
	const targets = await page.evaluate(() => {
		const sel = (el) => `${el.tagName.toLowerCase()}${el.id ? "#" + el.id : ""}${[...el.classList].map((c) => "." + c).join("")}`.slice(0, 60);
		const out = [];
		let i = 0;
		for (const el of document.querySelectorAll("*")) {
			const own = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent.trim()).join(" ").trim();
			if (!own) continue;
			const s = getComputedStyle(el);
			if (s.display === "none" || s.visibility === "hidden" || +s.opacity === 0) continue;
			if (el.closest(".sr-only") || el.classList.contains("sr-only")) continue;
			// An ancestor can erase text without the element saying so.
			let hidden = false;
			for (let p = el; p && p !== document.documentElement; p = p.parentElement) {
				const pr = p.getBoundingClientRect();
				if (+getComputedStyle(p).opacity === 0 || p.hasAttribute("inert") || pr.width < 2 || pr.height < 2) { hidden = true; break; }
			}
			if (hidden) continue;
			const rects = [];
			for (const n of el.childNodes) {
				if (n.nodeType !== 3 || !n.textContent.trim()) continue;
				const r = document.createRange();
				r.selectNodeContents(n);
				// Anything crossing the title bar is deliberately obscured: the bar
				// is translucent and blurred precisely so passing content turns to
				// mush. Measuring those pixels reports the bar's own white as the
				// text's background and calls an intended effect a contrast defect.
				const bar = document.querySelector(".titlebar");
				const barBottom = bar ? bar.getBoundingClientRect().bottom : 0;

				for (const q of r.getClientRects()) {
					if (q.width <= 1 || q.height <= 1) continue;
					if (q.top >= innerHeight || q.bottom <= 0 || q.left >= innerWidth || q.right <= 0) continue;
					if (q.top < barBottom) continue;
					// Scrolled under the topbar or behind the composer still counts
					// as inside the viewport, but the pixel there belongs to
					// whatever is on top -- measuring it reports that layer's
					// colour as the text's background. Only sample runs this
					// element is actually the painted owner of.
					const mx = Math.min(Math.max(q.left + q.width / 2, 1), innerWidth - 1);
					const my = Math.min(Math.max(q.top + q.height / 2, 1), innerHeight - 1);
					const top = document.elementFromPoint(mx, my);
					if (!top || !(el === top || el.contains(top) || top.contains(el))) continue;
					rects.push({ x: q.left, y: q.top, w: q.width, h: q.height });
				}
			}
			if (!rects.length) continue;
			out.push({ i: i++, sel: sel(el), text: own.slice(0, 40), color: s.color, px: +parseFloat(s.fontSize).toFixed(1), weight: Number(s.fontWeight) || 400, rects });
		}
		return out;
	});

	await page.addStyleTag({ content: "*,*::before,*::after{color:transparent!important;text-shadow:none!important}" });
	await new Promise((r) => setTimeout(r, 250));
	const shot = await page.screenshot({ encoding: "base64" });

	return page.evaluate(async (b64, ts) => {
		const img = new Image();
		img.src = "data:image/png;base64," + b64;
		await img.decode();
		const c = document.createElement("canvas");
		c.width = img.width; c.height = img.height;
		const x = c.getContext("2d", { willReadFrequently: true });
		x.drawImage(img, 0, 0);
		const dpr = img.width / innerWidth;
		const lum = ([r, g, b]) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
		const ratio = (a, b) => { const [p, q] = [lum(a), lum(b)].sort((m, n) => n - m); return (p + 0.05) / (q + 0.05); };
		const bad = [];
		for (const t of ts) {
			const pts = [];
			for (const r of t.rects) for (let gx = 1; gx <= 6; gx++) for (let gy = 1; gy <= 3; gy++) {
				const px = Math.round((r.x + r.w * gx / 7) * dpr), py = Math.round((r.y + r.h * gy / 4) * dpr);
				if (px < 0 || py < 0 || px >= c.width || py >= c.height) continue;
				const d = x.getImageData(px, py, 1, 1).data;
				pts.push([d[0], d[1], d[2]]);
			}
			if (!pts.length) continue;
			const s = pts.slice().sort((m, n) => lum(m) - lum(n));
			const fg = t.color.match(/[\d.]+/g).map(Number);
			const a = fg[3] ?? 1;
			const over = (bg) => fg.slice(0, 3).map((v, k) => v * a + bg[k] * (1 - a));
			const worst = Math.min(ratio(over(s[0]), s[0]), ratio(over(s[s.length - 1]), s[s.length - 1]));
			const need = t.px >= 24 || (t.px >= 18.66 && t.weight >= 700) ? 3 : 4.5;
			if (worst < need) bad.push({ sel: t.sel, text: t.text, px: t.px, worst: +worst.toFixed(2), need });
		}
		return bad;
	}, shot, targets);
}

const hits = (page) => page.evaluate(() => {
	const out = [];
	for (const el of document.querySelectorAll("button, a, summary, [role=switch]")) {
		const s = getComputedStyle(el);
		if (s.display === "none" || s.visibility === "hidden" || +s.opacity === 0 || el.closest("[inert]")) continue;
		const r = el.getBoundingClientRect();
		if (r.width < 1 || r.height < 1) continue;
		const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
		if (cx < 0 || cy < 0 || cx > innerWidth || cy > innerHeight) continue; // off-screen carousel items
		const owns = (x, y) => { if (x < 0 || y < 0 || x > innerWidth - 1 || y > innerHeight - 1) return false; const t = document.elementFromPoint(x, y); return !!t && (el === t || el.contains(t) || t.contains(el)); };
		let up = 0, down = 0;
		for (let d = 1; d <= 30 && owns(cx, cy - d); d++) up = d;
		for (let d = 1; d <= 30 && owns(cx, cy + d); d++) down = d;
		if (up + down + 1 < 44) out.push(`${el.className || el.tagName} ${Math.round(r.width)}x${Math.round(r.height)} hit=${up + down + 1}`);
	}
	return out;
});

for (const [name, w, h] of VIEWPORTS) {
	for (const answered of [false, true]) {
		const state = answered ? "chat" : "landing";
		console.log(`\n=== ${name} ${w}x${h} · ${state} ===`);
		const page = await open(w, h, answered);

		const doc = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: innerWidth }));
		say("no document horizontal scroll", doc.sw <= doc.iw, `${doc.sw} vs ${doc.iw}`);

		const under = await hits(page);
		say("all hit areas >= 44px", under.length === 0, under.join("; "));

		if (answered) {
			const reach = await page.evaluate(() => {
				const t = document.querySelector(".thread");
				const tr = t.getBoundingClientRect();
				return [...document.querySelectorAll(".follow-up")].map((c) => {
					const r = c.getBoundingClientRect();
					const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
					return { inView: r.bottom <= tr.bottom + 1, reachable: !!hit && (c === hit || c.contains(hit)) };
				});
			});
			say("follow-ups in view and reachable", reach.length > 0 && reach.every((r) => r.inView && r.reachable));

			const src = await page.evaluate(async () => {
				const s = document.querySelector(".sources__toggle");
				if (!s) return null;
				s.click();
				await new Promise((r) => setTimeout(r, 800));
				const one = document.querySelector(".source");
				const lab = one?.querySelector(".source__label");
				return { display: getComputedStyle(one).display, before: getComputedStyle(one, "::before").content, labelLines: lab ? Math.round(lab.getBoundingClientRect().height / 18) : 0 };
			});
			if (src) {
				say("sources render as a block stack", src.display === "block" && src.before === "none", `display=${src.display} ::before=${src.before}`);
				say("source label on one line", src.labelLines <= 1, `${src.labelLines} lines`);
			}
		}

		const bad = await contrast(page);
		say("all painted text >= AA", bad.length === 0, bad.map((b) => `${b.sel} ${b.worst}:1<${b.need}`).join("; "));
		await page.close();
	}
}

await browser.close();
console.log(`\n${failures === 0 ? "ALL CHECKS PASSED" : failures + " CHECK(S) FAILED"}`);
process.exit(failures === 0 ? 0 : 1);
