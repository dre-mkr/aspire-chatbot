/**
 * Interactive elements below the WCAG 2.2 AA minimum, at a phone width.
 *
 * The programme's bar is 2.5.8 (AA) at 24x24, not 2.5.5 (AAA) at 44x44 --
 * owner's decision, 2026-08-04. P10 measured 18px-tall auth links as the only
 * controls actually under the AA line; everything else was between the two
 * standards and is a judgement call rather than a failure.
 *
 * Measures the HIT area, not the painted one: several controls carry an
 * invisible `::after` overlay that grows the target without growing the ink, so
 * reading `getBoundingClientRect` alone reports failures that do not exist.
 *
 *   node .impeccable/preview-server.mjs &
 *   node .impeccable/hit-targets.mjs
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";

const BASE = process.argv[2] ?? "http://localhost:4173";
const MIN = 24;
const CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS", "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Aspire-Device" };

const MEASURE = (min) => {
  const named = (el) => `${el.tagName.toLowerCase()}${typeof el.className === "string" && el.className ? `.${el.className.split(" ").filter(Boolean)[0]}` : ""}`;
  const out = [];
  for (const el of document.querySelectorAll('a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])')) {
    if (el.closest("[inert]") || el.hasAttribute("inert")) continue;
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") continue;
    const box = el.getBoundingClientRect();
    if (box.width === 0 && box.height === 0) continue;
    // The overlay, when there is one, is what a finger actually hits.
    const after = getComputedStyle(el, "::after");
    let w = box.width, h = box.height;
    if (after.content && after.content !== "none") {
      const ah = parseFloat(after.height), aw = parseFloat(after.width);
      if (!Number.isNaN(ah)) h = Math.max(h, ah);
      if (!Number.isNaN(aw)) w = Math.max(w, aw);
    }
    if (w < min || h < min) out.push({ el: named(el), w: Math.round(w), h: Math.round(h), text: (el.innerText || el.getAttribute("aria-label") || "").trim().slice(0, 28) });
  }
  return out;
};

const browser = await puppeteer.launch({ headless: "new" });
let fails = 0;
for (const [label, path] of [["landing", "/"], ["sign in", "/signin"], ["sign up", "/signup"]]) {
  const page = await browser.newPage();
  await page.setViewport({ width: 390, height: 780 });
  await page.setRequestInterception(true);
  page.on("request", (r) => {
    if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
    if (r.url().includes("/api/")) return r.respond({ status: 404, contentType: "application/json", headers: CORS, body: "{}" });
    r.continue();
  });
  await page.goto(`${BASE}${path}`, { waitUntil: "networkidle2" });
  await new Promise((d) => setTimeout(d, 700));
  const under = await page.evaluate(MEASURE, MIN);
  if (under.length) fails += under.length;
  console.log(`  ${under.length ? "FAIL" : "PASS"}  ${label} — ${under.length} under ${MIN}x${MIN}`);
  for (const u of under) console.log(`      ${u.w}x${u.h}  ${u.el}  "${u.text}"`);
  await page.close();
}
await browser.close();
console.log(fails ? `\n${fails} under the AA minimum` : "\nALL PASS");
process.exit(fails ? 1 : 0);
