/**
 * Part 9: the edge cases, driven rather than reasoned about.
 *
 * Each of these is a way the session layer could quietly fail in a manner
 * nobody notices until a child is stuck. They are cheap to check and expensive
 * to discover in the field.
 *
 *   node .impeccable/preview-server.mjs &
 *   node .impeccable/auth-edges.mjs
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";

const BASE = process.argv[2] ?? "http://localhost:4173";
const CORS = {
	"Access-Control-Allow-Origin": "*",
	"Access-Control-Allow-Methods": "GET,POST,PATCH,OPTIONS",
	"Access-Control-Allow-Headers": "Content-Type, Authorization, X-Aspire-Device",
};

let fails = 0;
const say = (label, ok, detail = "") => {
	if (!ok) fails += 1;
	console.log(`  ${ok ? "PASS" : "FAIL"}  ${label}${detail ? ` — ${detail}` : ""}`);
};

const browser = await puppeteer.launch({ headless: "new" });

async function wire(page, calls, { expiresIn = 9999 } = {}) {
	await page.setRequestInterception(true);
	page.on("request", async (r) => {
		const u = r.url();
		if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
		const json = (s, b) =>
			r.respond({ status: s, contentType: "application/json", headers: CORS, body: JSON.stringify(b) });

		if (u.endsWith("/api/auth/anonymous")) {
			calls.anonymous += 1;
			calls.devices.push(JSON.parse(r.postData() || "{}").device_id ?? null);
			return json(200, {
				token: `anon-${calls.anonymous}`, user_id: `anon-${calls.anonymous}`,
				account_type: "anonymous", email: null, display_name: null, avatar_url: null,
				expires_in: expiresIn,
			});
		}
		if (u.endsWith("/api/auth/refresh")) {
			calls.refresh += 1;
			return json(200, {
				token: `renewed-${calls.refresh}`, user_id: "anon-1", account_type: "anonymous",
				email: null, display_name: null, avatar_url: null, expires_in: 9999,
			});
		}
		if (u.endsWith("/chat") || u.endsWith("/chat/stream")) {
			calls.chat += 1;
			calls.chatTokens.push(r.headers().authorization ?? "");
			if (u.endsWith("/chat/stream")) {
				const frame = (e) => `data: ${JSON.stringify(e)}\n\n`;
				return r.respond({
					status: 200, contentType: "text/event-stream", headers: CORS,
					body:
						frame({ type: "RUN_STARTED", threadId: "t", runId: "r" }) +
						frame({ type: "TEXT_MESSAGE_START", messageId: "m", role: "assistant" }) +
						frame({ type: "TEXT_MESSAGE_CONTENT", messageId: "m", delta: "An index fund holds a little of every company.\n" }) +
						frame({ type: "TEXT_MESSAGE_END", messageId: "m" }) +
						frame({ type: "CUSTOM", name: "aspire.turn", value: { reply: "An index fund holds a little of every company.", thread_id: "t", sources: [], follow_ups: [], game_started: null, eligibility_started: null } }) +
						frame({ type: "RUN_FINISHED", threadId: "t", runId: "r" }),
				});
			}
			return json(200, { reply: "An index fund holds a little of every company.", thread_id: "t", sources: [], follow_ups: [] });
		}
		if (u.endsWith("/api/title")) return json(200, { title: "Index funds" });
		if (u.includes("/api/")) return json(200, { conversations: [] });
		r.continue();
	});
}

const fresh = () => ({ anonymous: 0, refresh: 0, chat: 0, devices: [], chatTokens: [] });

/**
 * A page with nothing left over from the last one.
 *
 * Every page in a browser shares an origin's storage, so without this the
 * session written by one case is still there for the next — which made the
 * renewal case inherit a signed-in token from the cross-tab case and skip
 * renewal entirely, correctly, for the wrong reason.
 */
async function clean(calls, options) {
	const page = await browser.newPage();
	await page.setViewport({ width: 1280, height: 900 });
	await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
	await page.evaluate(() => {
		try {
			localStorage.clear();
		} catch {}
	});
	await wire(page, calls, options);
	return page;
}

const ask = async (page, text = "What is an index fund?") => {
	await page.click("#aspire-composer");
	await page.type("#aspire-composer", text);
	await page.keyboard.press("Enter");
};

// ─── storage unavailable ─────────────────────────────────────────────────────
console.log("\n── storage denied entirely ───────────────────────────────────");
{
	const page = await browser.newPage();
	await page.setViewport({ width: 1280, height: 900 });
	// Private browsing, blocked cookies, a locked-down profile: every call to
	// localStorage throws. A child in that state must still be able to ask.
	await page.evaluateOnNewDocument(() => {
		const boom = () => {
			throw new DOMException("denied", "SecurityError");
		};
		Object.defineProperty(window, "localStorage", {
			configurable: true,
			get: () => ({ getItem: boom, setItem: boom, removeItem: boom, clear: boom, key: boom, length: 0 }),
		});
	});
	const calls = fresh();
	await wire(page, calls);

	let crashed = null;
	page.on("pageerror", (e) => {
		crashed = String(e);
	});

	await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await ask(page);
	await page.waitForFunction(() => !document.querySelector(".composer__send--stop"), { timeout: 25000 });
	await new Promise((r) => setTimeout(r, 600));

	const answered = await page.evaluate(() => !!document.querySelector(".transcript .turn--assistant .answer p"));
	say("the page does not crash", crashed === null, crashed ?? "");
	say("a question can still be asked and answered", answered);
	say("a session was still established in memory", calls.anonymous >= 1, `${calls.anonymous}`);
	await page.close();
}

// ─── storage cleared mid-session ─────────────────────────────────────────────
console.log("\n── storage cleared while the tab is open ─────────────────────");
{
	const calls = fresh();
	const page = await clean(calls);
	await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await page.waitForFunction(() => !!localStorage.getItem("aspire.session.v1"), { timeout: 10000 });

	await page.evaluate(() => localStorage.clear());
	await page.reload({ waitUntil: "networkidle2" });
	await page.waitForFunction(() => !!localStorage.getItem("aspire.session.v1"), { timeout: 10000 });

	say("a new anonymous session is issued rather than an error", calls.anonymous >= 2, `${calls.anonymous} sessions`);
	const usable = await page.evaluate(() => !!document.querySelector("#aspire-composer"));
	say("and the app is usable immediately", usable);
	await page.close();
}

// ─── many tabs, one session ──────────────────────────────────────────────────
console.log("\n── several things needing identity at once ───────────────────");
{
	const calls = fresh();
	const page = await clean(calls);
	await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await new Promise((r) => setTimeout(r, 900));
	// The rail, the auth control and the conversation hook all want identity on
	// the same first paint. One request, not three, or a race mints several
	// identities and strands the conversations of the losers.
	say("exactly one anonymous session is created", calls.anonymous === 1, `${calls.anonymous}`);
	await page.close();
}

// ─── a sign-in in another tab reaches this one ───────────────────────────────
console.log("\n── another tab signs in ──────────────────────────────────────");
{
	const calls = fresh();
	const page = await clean(calls);
	await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await page.waitForSelector(".account__signin", { timeout: 10000 });

	// Exactly what a second tab writing the session looks like from here.
	await page.evaluate(() => {
		const value = JSON.stringify({
			token: "acct-token", userId: "u-1", accountType: "registered",
			email: "marcia.liburd@gmail.com", displayName: "Marcia Liburd", avatarUrl: null,
		});
		localStorage.setItem("aspire.session.v1", value);
		window.dispatchEvent(new StorageEvent("storage", { key: "aspire.session.v1", newValue: value }));
	});
	await page.waitForFunction(() => !!document.querySelector(".account-slot .avatar"), { timeout: 8000 })
		.then(() => say("this tab notices and shows the avatar", true))
		.catch(() => say("this tab notices and shows the avatar", false, "still showing signed-out"));
	await page.close();
}

// ─── renewal never interrupts a stream ───────────────────────────────────────
console.log("\n── a token near expiry renews without disturbing a reply ─────");
{
	const calls = fresh();
	// Two days left: inside the renewal window, nowhere near actually expired.
	const page = await clean(calls, { expiresIn: 2 * 24 * 60 * 60 });
	await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await page.waitForFunction(() => !!localStorage.getItem("aspire.session.v1"), { timeout: 10000 });
	await page.reload({ waitUntil: "networkidle2" });
	await new Promise((r) => setTimeout(r, 800));

	say("a session close to expiry is renewed", calls.refresh >= 1, `${calls.refresh} renewals`);

	await ask(page);
	await page.waitForFunction(() => !document.querySelector(".composer__send--stop"), { timeout: 25000 });
	await new Promise((r) => setTimeout(r, 500));
	const answered = await page.evaluate(() => !!document.querySelector(".transcript .turn--assistant .answer p"));
	say("the reply still arrives intact", answered);
	const stored = await page.evaluate(() => JSON.parse(localStorage.getItem("aspire.session.v1")).token);
	say("the renewed token is the one now in use", stored.startsWith("renewed-"), stored);
	await page.close();
}

// ─── the collapsed sidebar still reaches auth ────────────────────────────────
console.log("\n── sidebar collapsed in a conversation ───────────────────────");
{
	const calls = fresh();
	const page = await clean(calls);
	await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await ask(page);
	await page.waitForFunction(() => !document.querySelector(".composer__send--stop"), { timeout: 25000 });
	await page.evaluate(() => document.querySelector(".rail__collapse")?.click());
	await new Promise((r) => setTimeout(r, 800));

	const reachable = await page.evaluate(() => {
		const slot = document.querySelector(".account-slot");
		const control = slot?.querySelector(".account__signin, .account__avatar-btn");
		if (!slot || !control) return { ok: false, why: "no control" };
		const r = control.getBoundingClientRect();
		return {
			ok: Number(getComputedStyle(slot).opacity) > 0.9 && r.width > 0 && getComputedStyle(slot).pointerEvents !== "none",
			why: `opacity ${getComputedStyle(slot).opacity}`,
		};
	});
	say("the corner control takes over when the rail is collapsed", reachable.ok, reachable.why);
	await page.close();
}

console.log(`\n${fails === 0 ? "ALL PASS" : `${fails} FAIL`}`);
await browser.close();
process.exit(fails === 0 ? 0 : 1);
