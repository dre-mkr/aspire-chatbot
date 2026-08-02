import puppeteer from "puppeteer";
const b = await puppeteer.launch({ headless: "new" });
const p = await b.newPage();
await p.setViewport({ width: 1280, height: 800 });
const errs = [];
p.on("pageerror", (e) => errs.push(String(e).slice(0, 120)));
await p.goto("http://localhost:4173/chat/does-not-exist-123", { waitUntil: "networkidle2" });
await new Promise((r) => setTimeout(r, 1200));
console.log(JSON.stringify(await p.evaluate(() => ({
  phase: document.querySelector(".app")?.dataset.phase,
  titlebar: document.querySelector(".titlebar__text")?.textContent ?? null,
  turns: document.querySelectorAll(".transcript > *").length,
  heroVisible: getComputedStyle(document.querySelector(".hero")).opacity,
  bodyText: document.body.innerText.replace(/\s+/g, " ").slice(0, 160),
})), null, 2));
console.log("pageerrors:", errs.length ? errs : "none");
await p.screenshot({ path: ".impeccable/notfound.png" });
await b.close();
