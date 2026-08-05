/**
 * Does a question typed into the UI actually get an answer rendered?
 *
 * The E2E harness saw the question echoed and then the EMPTY-STATE copy ("What
 * do you want to learn about money today?"), which means the transcript never
 * gained an assistant message. This logs every request and response touching
 * the stream endpoint, so the answer to "is this the frontend or the backend"
 * is in the transcript rather than inferred.
 */
import puppeteer from "puppeteer";

const browser = await puppeteer.launch({
	headless: "new",
	args: ["--no-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 900 });

page.on("request", (r) => {
	if (/\/v2\/|\/api\//.test(r.url())) console.log(`  -> ${r.method()} ${r.url()}`);
});
page.on("response", async (r) => {
	if (!/\/v2\/|\/api\//.test(r.url())) return;
	let body = "";
	try {
		body = (await r.text()).slice(0, 260).replace(/\n/g, "\\n");
	} catch (e) {
		body = `<unreadable: ${e.message.slice(0, 60)}>`;
	}
	console.log(`  <- ${r.status()} ${r.url()}`);
	if (body) console.log(`     ${body}`);
});
page.on("requestfailed", (r) => {
	if (/\/v2\/|\/api\//.test(r.url()))
		console.log(`  !! FAILED ${r.method()} ${r.url()} ${r.failure()?.errorText}`);
});
page.on("pageerror", (e) => console.log(`  !! pageerror ${String(e).slice(0, 160)}`));

await page.goto("http://localhost:3000/", { waitUntil: "networkidle2", timeout: 60_000 });

const composer = await page.waitForSelector("textarea", { timeout: 30_000 });
console.log("\n== typing and submitting ==");
await composer.click();
await composer.type("What is the ASPIRE Programme?", { delay: 10 });
await page.keyboard.press("Enter");

// Give the stream a generous window to complete.
await new Promise((r) => setTimeout(r, 45_000));

console.log("\n== what the transcript holds now ==");
const text = await page.evaluate(() => document.body.innerText);
console.log(JSON.stringify(text.slice(0, 700)));

console.log("\n== assistant message nodes ==");
const nodes = await page.evaluate(() => {
	const out = [];
	for (const el of document.querySelectorAll(
		"[data-role], [data-message-role], [class*='assistant'], [class*='message']",
	)) {
		const t = (el.textContent || "").trim();
		if (t) out.push(`${el.tagName}.${el.className}`.slice(0, 70) + " :: " + t.slice(0, 90));
	}
	return out.slice(0, 12);
});
for (const n of nodes) console.log("  " + n);

await browser.close();
