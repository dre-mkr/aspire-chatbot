/**
 * The persona picker, end to end.
 *
 * P3-005 was not a bug, it was an unbuilt path: the backend had per-persona
 * prompts, twelve voices and `persona_bands` on every game item, and the client
 * sent `null` on every request because nothing ever set the prop. So the test
 * that matters is the last one in the first group -- that a choice actually
 * reaches the service -- and the rest exist to keep the control that makes it
 * reachable working.
 *
 *   node .impeccable/preview-server.mjs &
 *   node .impeccable/persona-picker.mjs
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";
import { createConversationStore } from "./fake-conversations.mjs";
import { handleChatStream } from "./fake-stream.mjs";

const CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS", "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Aspire-Device" };
let fails = 0;
const say = (l, ok, d = "") => { if (!ok) fails++; console.log(`  ${ok ? "PASS" : "FAIL"}  ${l}${d ? ` — ${d}` : ""}`); };
const b = await puppeteer.launch({ headless: "new" });
const p = await b.newPage();
await p.setViewport({ width: 1280, height: 800 });
const store = createConversationStore();
let sentPersona = "UNSENT";
await p.setRequestInterception(true);
p.on("request", async (r) => {
  if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
  const respond = (s, bd) => r.respond({ status: s, contentType: "application/json", headers: CORS, body: bd === null ? "" : JSON.stringify(bd) });
  if (await store.handle(r, respond)) return;
  if (r.url().endsWith("/chat/stream")) {
    handleChatStream(r, (body) => r.respond({ status: 200, contentType: "text/event-stream", headers: CORS, body }), (sent) => {
      sentPersona = sent.persona === undefined ? "ABSENT" : String(sent.persona);
      const id = sent.thread_id || "t-p";
      store.openConversation(id, store.ownerOf(r), sent.message);
      store.recordTurn(id, null, sent.message, { role: "assistant", text: "A bond is a loan.", sources: [], follow_ups: [] });
      return { reply: "A bond is a loan." };
    });
    return;
  }
  if (r.url().includes("/api/")) return respond(404, {});
  r.continue();
});
await p.goto("http://localhost:4173/", { waitUntil: "networkidle2" });
await new Promise((r) => setTimeout(r, 700));

say("the trigger says nobody is chosen yet", (await p.$eval(".persona__name", (n) => n.textContent)) === "Everyone");
await p.evaluate(() => document.querySelector(".persona__trigger").click());
await new Promise((r) => setTimeout(r, 400));
const labels = await p.$$eval(".persona__option .persona__label", (ns) => ns.map((n) => n.textContent.replace(/([a-z])([A-Z])/g, "$1 $2")));
say("all four personas plus the default are offered", labels.length === 5, labels.join(" / "));

await p.evaluate(() => { const o = [...document.querySelectorAll(".persona__option")].find((n) => n.textContent.includes("Orion")); o.click(); });
await new Promise((r) => setTimeout(r, 500));
say("choosing puts it in the URL", p.url().includes("persona=orion"), p.url());
say("and the trigger now names it", (await p.$eval(".persona__name", (n) => n.textContent)) === "Orion");
say("the menu closed", (await p.$(".persona__menu")) === null);

await p.click("#aspire-composer");
await p.type("#aspire-composer", "What is a bond?");
await p.keyboard.press("Enter");
await p.waitForFunction(() => !document.querySelector(".composer__send--stop"), { timeout: 30000 });
await new Promise((r) => setTimeout(r, 900));
say("and it reaches the service on the request", sentPersona === "orion", `persona=${sentPersona}`);

// Chat phase: composer is docked low, so the menu must open upward.
await p.evaluate(() => document.querySelector(".persona__trigger").click());
await new Promise((r) => setTimeout(r, 400));
const geo = await p.evaluate(() => { const m = document.querySelector(".persona__menu").getBoundingClientRect(); const t = document.querySelector(".persona__trigger").getBoundingClientRect(); return { mTop: Math.round(m.top), mBot: Math.round(m.bottom), tTop: Math.round(t.top), vh: window.innerHeight }; });
say("in the chat phase it opens above the composer", geo.mBot <= geo.tTop + 1, JSON.stringify(geo));
say("and stays on screen", geo.mTop >= 0 && geo.mBot <= geo.vh, JSON.stringify(geo));
await p.screenshot({ path: ".impeccable/shots/persona-chat-open.png" });

// A junk persona in the URL must not be forwarded.
await p.goto("http://localhost:4173/?persona=wizard", { waitUntil: "networkidle2" });
await new Promise((r) => setTimeout(r, 700));
say("a junk persona in the URL falls back to the default", (await p.$eval(".persona__name", (n) => n.textContent)) === "Everyone");

console.log(fails ? `\n${fails} FAIL` : "\nALL PASS");
await b.close();
process.exit(fails ? 1 : 0);
