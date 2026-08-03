/**
 * Sign-up and sign-in against the real service and the real database.
 *
 * Every other auth harness talks to a stub. That is right for asserting what
 * the pages do — a stub can be made to fail on command, and a real service
 * cannot — but it means nothing here had ever proved that an account can
 * actually be created. A stub agrees with whatever the client sends it; the
 * things that break in practice are the ones only a real server can disagree
 * about: the shape of the request body, the password rules, what a duplicate
 * address returns, whether the token the client stores is one the service will
 * accept back, and whether any of it survives a reload.
 *
 * Requires FastAPI on :8000 with a database configured, and the preview server
 * on :4173. `run-all.mjs` does not start the backend, so this suite skips
 * cleanly rather than failing when it is not there — a red suite for "you did
 * not start the API" teaches people to ignore red suites.
 *
 *   cd backend && uv run uvicorn app.main:app --port 8000 &
 *   node .impeccable/preview-server.mjs &
 *   node .impeccable/auth-e2e.mjs
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";

const BASE = process.argv[2] ?? "http://localhost:4173";
const API = process.argv[3] ?? "http://localhost:8000";

let fails = 0;
const say = (label, ok, detail = "") => {
	if (!ok) fails += 1;
	console.log(`  ${ok ? "PASS" : "FAIL"}  ${label}${detail ? ` — ${detail}` : ""}`);
};

// A fresh address every run: these accounts are real rows and the suite must be
// runnable twice in a row without the second run colliding with the first.
const stamp = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
const EMAIL = `aspire.e2e.${stamp}@example.com`;
const PASSWORD = "Nutmeg-Harbour-71";
const FIRST = "Marcia";
const LAST = "Liburd";

try {
	const health = await fetch(`${API}/health`, { signal: AbortSignal.timeout(3000) });
	if (!health.ok) throw new Error(String(health.status));
} catch {
	console.log(`\n  SKIP  no service on ${API} — start uvicorn to run these`);
	process.exit(0);
}

const browser = await puppeteer.launch({ headless: "new" });
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 900 });

const type = async (label, value) => {
	const ok = await page.evaluate(
		(l, v) => {
			const byLabel = [...document.querySelectorAll(".field")].find(
				(f) => f.querySelector(".field__label, legend")?.textContent?.trim() === l,
			);
			const input =
				document.querySelector(`[aria-label="${l}"]`) ?? byLabel?.querySelector("input, select");
			if (!input) return false;
			const setter = Object.getOwnPropertyDescriptor(
				input.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype,
				"value",
			).set;
			setter.call(input, v);
			input.dispatchEvent(new Event("input", { bubbles: true }));
			input.dispatchEvent(new Event("change", { bubbles: true }));
			return true;
		},
		label,
		value,
	);
	if (!ok) throw new Error(`no field labelled "${label}"`);
};

const click = (text) =>
	page.evaluate((t) => {
		const button = [...document.querySelectorAll("button")].find((b) =>
			b.textContent.trim().toLowerCase().includes(t.toLowerCase()),
		);
		if (!button) throw new Error(`no button "${t}"`);
		button.click();
	}, text);

const session = () =>
	page.evaluate(() => {
		try {
			return JSON.parse(localStorage.getItem("aspire.session.v1") ?? "null");
		} catch {
			return null;
		}
	});

const settle = (ms = 900) => new Promise((r) => setTimeout(r, ms));

// ─── an anonymous session comes from the real service ────────────────────────
console.log("\n── the service issues an anonymous session ───────────────────");
await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
await page.waitForFunction(() => !!localStorage.getItem("aspire.session.v1"), { timeout: 15000 });
const anonymous = await session();
say("a session is minted without anyone signing up", Boolean(anonymous?.token), anonymous?.accountType ?? "none");
say("it is anonymous", anonymous?.accountType === "anonymous", anonymous?.accountType ?? "");

// And the service accepts its own token back — the half a stub cannot test.
const echoed = await fetch(`${API}/api/auth/session`, {
	headers: { authorization: `Bearer ${anonymous.token}` },
});
say("the service accepts the token it just issued", echoed.status === 200, `HTTP ${echoed.status}`);

// ─── sign up ─────────────────────────────────────────────────────────────────
console.log("\n── signing up creates a real account ─────────────────────────");
await page.goto(`${BASE}/signup`, { waitUntil: "networkidle2" });

await type("First name", FIRST);
await type("Last name", LAST);
await type("Day", "14");
await type("Month", "3");
// An adult, so the guardian step is skipped and this is a four-step form.
await type("Year", String(new Date().getFullYear() - 27));
await click("Continue");
await settle(400);

await page.evaluate(() => {
	// Island is a row of buttons rather than a select.
	const island = [...document.querySelectorAll("fieldset button, .field button")].find((b) =>
		/kitts/i.test(b.textContent ?? ""),
	);
	island?.click();
});
await type("School", "Basseterre High");
await click("Continue");
await settle(400);

// Step 3 is the grown-up. It is shown to adults as well as children — it is
// only *required* under 13 — so it has to be stepped through either way rather
// than assumed skipped, which is what made this suite look for the email field
// one screen too early.
say(
	"step 3 asks who to tell",
	/someone we can tell/i.test(await page.evaluate(() => document.querySelector(".auth__title")?.textContent ?? "")),
);
await click("Continue");
await settle(400);

await type("Email", EMAIL);
await type("Password", PASSWORD);
await click("Create account");
await page.waitForFunction(
	() => {
		try {
			return JSON.parse(localStorage.getItem("aspire.session.v1") ?? "null")?.accountType === "registered";
		} catch {
			return false;
		}
	},
	{ timeout: 20000 },
).catch(() => {});
await settle();

const registered = await session();
say("the account exists and the browser holds its session", registered?.accountType === "registered", registered?.accountType ?? "still anonymous");
say("the session carries the address that was typed", registered?.email === EMAIL, registered?.email ?? "none");
say("the token changed from the anonymous one", registered?.token !== anonymous?.token);
say("sign-up returns to the product", new URL(page.url()).pathname === "/", page.url());

// The row is really in Postgres, not just in this tab.
const whoami = await fetch(`${API}/api/auth/session`, {
	headers: { authorization: `Bearer ${registered.token}` },
});
const whoamiBody = await whoami.json().catch(() => ({}));
say("the service recognises the new account", whoami.status === 200 && whoamiBody.email === EMAIL, `HTTP ${whoami.status} ${whoamiBody.email ?? ""}`);

// ─── the address is now taken ────────────────────────────────────────────────
console.log("\n── the same address cannot be taken twice ────────────────────");
const duplicate = await fetch(`${API}/api/auth/register`, {
	method: "POST",
	headers: { "content-type": "application/json" },
	body: JSON.stringify({
		email: EMAIL, password: PASSWORD, first_name: FIRST, last_name: LAST,
		date_of_birth: `${new Date().getFullYear() - 27}-03-14`,
	}),
});
say("a second registration is refused", duplicate.status >= 400, `HTTP ${duplicate.status}`);
const duplicateBody = await duplicate.json().catch(() => ({}));
say(
	"and says which field is the problem",
	/already|taken|exists/i.test(JSON.stringify(duplicateBody)),
	String(duplicateBody.detail ?? "").slice(0, 60),
);

// ─── sign out ────────────────────────────────────────────────────────────────
console.log("\n── signing out ──────────────────────────────────────────────");
await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
await settle();
const signedOut = await page.evaluate(async () => {
	const open = document.querySelector(".account__avatar-btn");
	if (!open) return "no avatar control";
	open.click();
	await new Promise((r) => setTimeout(r, 400));
	const out = [...document.querySelectorAll("button, a")].find((n) =>
		/^sign out$/i.test((n.textContent ?? "").trim()),
	);
	if (!out) return "no sign-out item";
	out.click();
	await new Promise((r) => setTimeout(r, 400));

	// Signing out is confirmed rather than immediate — from the menu it is not
	// obvious what happens to the conversations in the rail, and the product
	// answers that in one sentence before doing anything. A harness that clicks
	// "Sign out" and stops has opened the question, not answered it, and will
	// report a working sign-out as broken.
	const confirm = [...document.querySelectorAll("button")].find((n) =>
		/yes, sign out/i.test(n.textContent ?? ""),
	);
	if (!confirm) return "no confirmation step";
	confirm.click();
	return "clicked";
});
say("the account menu offers a way out", signedOut === "clicked", signedOut);
await settle(1500);
const after = await session();
say("the account session is gone", after?.accountType !== "registered", after?.accountType ?? "none");
say("and the previous account's address is not left behind", after?.email !== EMAIL, after?.email ?? "none");

// ─── sign back in ────────────────────────────────────────────────────────────
console.log("\n── signing back in with those credentials ────────────────────");
await page.goto(`${BASE}/signin`, { waitUntil: "networkidle2" });
await type("Email", EMAIL);
await type("Password", PASSWORD);
await click("Sign in");
await page.waitForFunction(
	(email) => {
		try {
			return JSON.parse(localStorage.getItem("aspire.session.v1") ?? "null")?.email === email;
		} catch {
			return false;
		}
	},
	{ timeout: 20000 },
	EMAIL,
).catch(() => {});
await settle();

const back = await session();
say("the same credentials sign back in", back?.email === EMAIL, back?.email ?? "not signed in");
say("as a registered account", back?.accountType === "registered", back?.accountType ?? "");

// ─── a wrong password is refused ─────────────────────────────────────────────
console.log("\n── a wrong password is refused, without saying which half ────");
const wrong = await fetch(`${API}/api/auth/login`, {
	method: "POST",
	headers: { "content-type": "application/json" },
	body: JSON.stringify({ email: EMAIL, password: "not-the-password" }),
});
const wrongBody = await wrong.json().catch(() => ({}));
say("the wrong password does not sign in", wrong.status >= 400, `HTTP ${wrong.status}`);
const unknown = await fetch(`${API}/api/auth/login`, {
	method: "POST",
	headers: { "content-type": "application/json" },
	body: JSON.stringify({ email: `nobody.${stamp}@example.com`, password: PASSWORD }),
});
const unknownBody = await unknown.json().catch(() => ({}));
say(
	"an unknown address is refused identically, so the API is not an oracle for who has an account",
	wrong.status === unknown.status && JSON.stringify(wrongBody) === JSON.stringify(unknownBody),
	`${wrong.status} vs ${unknown.status}`,
);

// ─── the session survives a reload ───────────────────────────────────────────
console.log("\n── it is still signed in after a reload ──────────────────────");
await page.reload({ waitUntil: "networkidle2" });
await settle(1200);
const reloaded = await session();
say("the session survives a reload", reloaded?.email === EMAIL, reloaded?.email ?? "gone");
const avatar = await page.evaluate(() => !!document.querySelector(".account-slot .avatar"));
say("and the interface shows the account, not the sign-in invitation", avatar);

console.log(`\n${fails === 0 ? "ALL PASS" : `${fails} FAIL`}`);
await browser.close();
process.exit(fails === 0 ? 0 : 1);
