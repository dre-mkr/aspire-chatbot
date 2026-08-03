/**
 * Phase 7: the deliberate i18n sample.
 *
 * French at 320px (longest strings, tightest width) and Spanish at 768px catch
 * nearly everything. Reports overflow, clipping, and text colliding with the
 * controls beside it, per surface.
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";

const BASE = "http://localhost:4173";
const API = "http://localhost:8000";
const CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS", "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Aspire-Device" };

const browser = await puppeteer.launch({ headless: "new" });
const settle = (ms = 700) => new Promise((r) => setTimeout(r, ms));

/** Every way a layout can fail at a width, measured rather than eyeballed. */
const AUDIT = `() => {
  const problems = [];
  const doc = document.documentElement;
  if (doc.scrollWidth > doc.clientWidth + 1)
    problems.push({ kind: "page-overflow", detail: doc.scrollWidth + "px in " + doc.clientWidth + "px" });

  // Same rule the contrast triage needed: this product keeps whole subtrees in
  // the DOM while folded away (the collapsed rail, the starters row at 0fr, the
  // hero in the chat phase). Judging them reports the layer behind them as a
  // defect. Anything under a folded, inert, zero-size or clipped-to-nothing
  // ancestor is not on screen and is not a layout failure.
  const folded = (el) => {
    for (let n = el; n && n !== document.documentElement; n = n.parentElement) {
      const s = getComputedStyle(n);
      if (s.display === "none" || s.visibility === "hidden") return true;
      if (Number.parseFloat(s.opacity) === 0) return true;
      if (n.inert || n.hasAttribute?.("inert")) return true;
      const r = n.getBoundingClientRect();
      if (r.width <= 1 || r.height <= 1) return true;
    }
    return false;
  };

  // A label hidden by design at this width: sr-only, and the composer tool label
  // that is deliberately dropped under 620px while keeping its accessible name.
  const hiddenByDesign = (el) =>
    el.classList.contains("sr-only") ||
    el.closest(".sr-only") !== null ||
    el.classList.contains("tool-btn__label");

  for (const el of document.querySelectorAll("*")) {
    if (hiddenByDesign(el) || folded(el)) continue;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    const label = (el.className || el.tagName || "").toString().trim().slice(0, 40);
    const text = (el.textContent || "").trim().slice(0, 30);
    if (!text) continue;

    // Only judge an element that paints text ITSELF. A container whose
    // scrollWidth is inflated by an absolutely-positioned decorative child --
    // the hero's vignette is inset -8%/-6% behind an overflow:hidden on
    // purpose -- is not clipping anything anyone was meant to read.
    const ownsText = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());

    // Content inside a horizontally scrollable ancestor is reachable. Below
    // 620px the starters row is a deliberate scroll-snap carousel, so its chips
    // extending past the viewport is the design, not an overflow.
    let scrollable = false;
    for (let n = el.parentElement; n && n !== document.documentElement; n = n.parentElement) {
      const ov = getComputedStyle(n).overflowX;
      if (ov === "auto" || ov === "scroll") { scrollable = true; break; }
    }

    // Text cut off by its own box, with no ellipsis to announce it.
    const scrolls = (a) => a === "auto" || a === "scroll" || a === "visible";
    const clipsX = el.scrollWidth > el.clientWidth + 1 && !scrolls(s.overflowX);
    const clipsY = el.scrollHeight > el.clientHeight + 1 && !scrolls(s.overflowY);
    if ((clipsX || clipsY) && s.textOverflow !== "ellipsis" && ownsText)
      problems.push({ kind: "clipped", el: label, detail: (clipsX ? "x " + el.scrollWidth + ">" + el.clientWidth : "") + (clipsY ? " y " + el.scrollHeight + ">" + el.clientHeight : ""), text });

    // Ellipsis engaging is only a defect where the string has to be read whole.
    // A conversation title in a 187px rail row and a chat title in the top bar
    // are both meant to truncate; they are the label of something you can open.
    const mayTruncate = el.closest(".rail, .titlebar, .history-row") !== null;
    if (s.textOverflow === "ellipsis" && el.scrollWidth > el.clientWidth + 1 && !mayTruncate)
      problems.push({ kind: "ellipsised", el: label, text });

    if (r.right > window.innerWidth + 1 && !scrollable)
      problems.push({ kind: "off-right", el: label, detail: Math.round(r.right) + " > " + window.innerWidth, text });
  }
  return problems;
}`;

async function open({ lang, width, height, kind = "chat", gameType = null }) {
	const p = await browser.newPage();
	await p.setViewport({ width, height });
	await p.setRequestInterception(true);
	p.on("request", (r) => {
		if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
		if (r.url().endsWith("/chat")) {
			const t = JSON.parse(r.postData() ?? "{}").thread_id;
			if (kind === "answer")
				return r.respond({ status: 200, contentType: "application/json", headers: CORS, body: JSON.stringify({
					reply: "Un fonds indiciel détient une petite partie de chaque entreprise d'une liste.\n\n- Vous possédez une fraction de centaines d'entreprises\n- Les frais sont peu élevés",
					thread_id: t, sources: [{ content: "Un fonds indiciel suit un indice de marché.", metadata: { question: "Qu'est-ce qu'un fonds indiciel ?" } }],
					follow_ups: ["De combien ai-je besoin pour commencer ?"] }) });
			const url = kind === "elig" ? `${API}/api/eligibility/start` : `${API}/api/games/start`;
			const body = kind === "elig" ? { thread_id: t, language: lang } : { thread_id: t, persona: "orion", language: lang, game_type: gameType };
			const ann = kind === "elig" ? { eligibility_started: { check: "aspire_eligibility", language: lang } } : { game_started: { game_type: gameType } };
			return void fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
				.catch(() => {})
				.then(() => r.respond({ status: 200, contentType: "application/json", headers: CORS, body: JSON.stringify({ reply: "", thread_id: t, sources: [], follow_ups: [], ...ann }) }));
		}
		r.continue();
	});
	await p.evaluateOnNewDocument((l) => {
		window.localStorage.setItem("aspire.voice.prefs.v1", JSON.stringify({ autoSpeak: false, speed: 1, language: l }));
	}, lang);
	await p.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await settle(400);
	return p;
}

const CASES = [
	{ name: "landing", lang: "fr", width: 320, height: 720, kind: "landing" },
	{ name: "landing", lang: "es", width: 768, height: 900, kind: "landing" },
	{ name: "answer", lang: "fr", width: 320, height: 720, kind: "answer" },
	{ name: "answer", lang: "es", width: 768, height: 900, kind: "answer" },
	{ name: "scramble", lang: "fr", width: 320, height: 900, kind: "game", gameType: "word_scramble" },
	{ name: "scramble", lang: "es", width: 768, height: 900, kind: "game", gameType: "word_scramble" },
	{ name: "truefalse", lang: "fr", width: 320, height: 900, kind: "game", gameType: "true_false" },
	{ name: "truefalse", lang: "es", width: 768, height: 900, kind: "game", gameType: "true_false" },
	{ name: "eligibility", lang: "fr", width: 320, height: 1100, kind: "elig" },
	{ name: "eligibility", lang: "es", width: 768, height: 1100, kind: "elig" },
];

let total = 0;
for (const c of CASES) {
	const p = await open(c);
	if (c.kind === "answer") {
		await p.type("#aspire-composer", "fonds indiciel ?");
		await p.keyboard.press("Enter");
		await p.waitForFunction(() => !document.querySelector(".composer__send--stop"), { timeout: 20000 }).catch(() => {});
		await settle(900);
	} else if (c.kind !== "landing") {
		await p.type("#aspire-composer", "go");
		await p.keyboard.press("Enter");
		await p.waitForSelector(c.kind === "elig" ? ".elig" : ".game", { timeout: 20000 }).catch(() => {});
		await settle(700);
	}
	const found = await p.evaluate(eval(AUDIT));
	const tag = `${c.name} · ${c.lang.toUpperCase()} @ ${c.width}`;
	if (!found.length) console.log(`  PASS  ${tag}`);
	else {
		console.log(`  FAIL  ${tag}`);
		const seen = new Set();
		for (const f of found) {
			const k = `${f.kind}|${f.el}|${f.text ?? ""}`;
			if (seen.has(k)) continue;
			seen.add(k);
			total += 1;
			console.log(`          ${f.kind}  ${f.el ?? ""}  ${f.detail ?? ""}  ${f.text ? `"${f.text}"` : ""}`);
		}
	}
	await p.screenshot({ path: `.impeccable/i18n-${c.name}-${c.lang}-${c.width}.png`, fullPage: false });
	await p.close();
}
console.log(`\n${total} distinct layout problems across the sample.`);
await browser.close();
