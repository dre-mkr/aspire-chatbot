import puppeteer from "puppeteer";
const b = await puppeteer.launch({ headless: "new" });
for (const [label, setup] of [
  ["cold load (no history)", async () => {}],
  ["with an existing chat in history", async (p) => {
    await p.evaluate(() => localStorage.setItem("aspire.conversations.v1", JSON.stringify([{id:"real-1",title:"Real chat",updatedAt:Date.now(),titleSource:"generated",messages:[]}])));
  }],
]) {
  const p = await b.newPage();
  await p.setViewport({ width: 1280, height: 800 });
  await p.goto("http://localhost:4173/", { waitUntil: "networkidle2" });
  await setup(p);
  await p.goto("http://localhost:4173/chat/does-not-exist-123", { waitUntil: "networkidle2" });
  for (const wait of [300, 1500, 3000]) {
    await new Promise(r => setTimeout(r, wait === 300 ? 300 : 1200));
    const s = await p.evaluate(() => ({ url: location.pathname, phase: document.querySelector(".app")?.dataset.phase, turns: document.querySelectorAll(".transcript > *").length }));
    console.log(`  ${label} @${wait}ms:`, JSON.stringify(s));
  }
  await p.close();
}
await b.close();
