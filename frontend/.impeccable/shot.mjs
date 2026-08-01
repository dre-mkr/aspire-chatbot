/**
 * Screenshots one state at one viewport. Backend stubbed so the chat phase is
 * reachable without a running service.
 * Usage: node .impeccable/shot.mjs <out.png> <WxH> [--answered]
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";
const [, , out, vp = "1280x800", ...flags] = process.argv;
const [w, h] = vp.split("x").map(Number);
const CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,OPTIONS", "Access-Control-Allow-Headers": "Content-Type" };
const A = { reply: "An **index fund** holds a little of every company on a list.\n\n- You own a slice of hundreds at once\n- Fees are low", thread_id: "t", sources: [{ content: "An index fund tracks a market index.", metadata: { question: "What is an index fund?" } }], follow_ups: ["How much do I need to start?"] };
const b = await puppeteer.launch({ headless: "new" });
const p = await b.newPage();
await p.setViewport({ width: w, height: h });
await p.setRequestInterception(true);
p.on("request", (r) => {
  if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
  if (r.url().endsWith("/chat")) return r.respond({ status: 200, contentType: "application/json", headers: CORS, body: JSON.stringify(A) });
  if (r.url().includes("/api/games/")) return r.respond({ status: 404, contentType: "application/json", headers: CORS, body: "{}" });
  r.continue();
});
await p.goto("http://localhost:4173/", { waitUntil: "networkidle2" });
if (flags.includes("--answered")) {
  await p.type("#aspire-composer", "What is an index fund?");
  await p.keyboard.press("Enter");
  await p.waitForFunction(() => !document.querySelector(".composer__send--stop"), { timeout: 20000 });
  await new Promise((r) => setTimeout(r, 900));
}
await new Promise((r) => setTimeout(r, 500));
await p.screenshot({ path: out });
await b.close();
console.log("wrote", out);
