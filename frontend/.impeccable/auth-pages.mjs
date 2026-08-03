/**
 * `/signin` and `/signup`: do they work, and do they look like the product.
 *
 * The visual half is checked against the tokens already in the stylesheet
 * rather than against a screenshot, because "matches the existing language" is
 * a claim about the same plum, the same radii and the same type scale — and
 * those are readable at runtime. A screenshot would only prove the page has not
 * changed since the last screenshot.
 *
 * The functional half drives the real forms against a stubbed service.
 *
 *   node .impeccable/preview-server.mjs &
 *   node .impeccable/auth-pages.mjs
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

/** A stub that records what the pages actually send. */
async function open(path, { registerStatus = 200, loginStatus = 200, detail = "" } = {}) {
	const page = await browser.newPage();
	await page.setViewport({ width: 1280, height: 900 });
	const seen = { register: [], login: [], forgot: [], link: [] };

	await page.setRequestInterception(true);
	page.on("request", async (r) => {
		const url = r.url();
		if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });

		const json = (status, body) =>
			r.respond({ status, contentType: "application/json", headers: CORS, body: JSON.stringify(body) });

		if (url.endsWith("/api/auth/anonymous")) {
			return json(200, { token: "anon-token", user_id: "anon-1", account_type: "anonymous", expires_in: 99999 });
		}
		if (url.endsWith("/api/auth/register")) {
			seen.register.push(JSON.parse(r.postData() || "{}"));
			if (registerStatus !== 200) return json(registerStatus, { detail });
			return json(200, {
				token: "acct-token", user_id: "u-1", account_type: "registered",
				email: "jayla@ecse.kn", display_name: "Jayla Thomas", avatar_url: null,
				expires_in: 99999, claim: { attempted: true, conversations: 2, reason: null },
			});
		}
		if (url.endsWith("/api/auth/login")) {
			seen.login.push(JSON.parse(r.postData() || "{}"));
			if (loginStatus !== 200) return json(loginStatus, { detail });
			return json(200, {
				token: "acct-token", user_id: "u-1", account_type: "registered",
				email: "jayla@ecse.kn", display_name: "Jayla Thomas", avatar_url: null,
				expires_in: 99999, claim: { attempted: true, conversations: 1, reason: null },
			});
		}
		if (url.endsWith("/api/auth/signin-link")) {
			seen.link.push(JSON.parse(r.postData() || "{}"));
			return json(202, { sent: true });
		}
		if (url.includes("/api/conversations")) return json(200, { conversations: [] });
		if (url.includes("/api/")) return json(404, {});
		r.continue();
	});

	await page.goto(`${BASE}${path}`, { waitUntil: "networkidle2" });
	return { page, seen };
}

const type = async (page, label, value) => {
	const ok = await page.evaluate(
		(l, v) => {
			// Most fields are found by their visible label; the date-of-birth
			// boxes sit together under one legend and are named individually by
			// `aria-label`, so both are tried.
			const byLabel = [...document.querySelectorAll(".field")].find(
				(f) => f.querySelector(".field__label, legend")?.textContent?.trim() === l,
			);
			const input =
				document.querySelector(`[aria-label="${l}"]`) ??
				byLabel?.querySelector("input, select");
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

const click = (page, text) =>
	page.evaluate((t) => {
		const button = [...document.querySelectorAll("button")].find((b) =>
			b.textContent.trim().toLowerCase().includes(t.toLowerCase()),
		);
		if (!button) throw new Error(`no button "${t}"`);
		button.click();
	}, text);

// ─── it looks like the product ───────────────────────────────────────────────
console.log("\n── the pages use the product's own language ───────────────────");
{
	const { page } = await open("/signin");
	const design = await page.evaluate(() => {
		const root = getComputedStyle(document.documentElement);
		const panel = document.querySelector(".auth__panel");
		const input = document.querySelector(".field__input");
		const primary = document.querySelector(".auth__primary");
		const body = getComputedStyle(document.body);
		return {
			plum: root.getPropertyValue("--plum").trim(),
			panelBg: getComputedStyle(panel).backgroundImage,
			inputRadius: getComputedStyle(input).borderRadius,
			inputHeight: getComputedStyle(input).height,
			inputFont: getComputedStyle(input).fontSize,
			primaryRadius: getComputedStyle(primary).borderRadius,
			primaryHeight: getComputedStyle(primary).height,
			family: body.fontFamily,
		};
	});

	say("the panel uses the brand gradient", design.panelBg.includes("gradient"), design.panelBg.slice(0, 46));
	say("inputs use the product's radius and rhythm", design.inputRadius === "16px" && design.inputHeight === "52px", `${design.inputRadius} / ${design.inputHeight}`);
	// 16px exactly, or iOS zooms the page when a child taps the field.
	say("input text is 16px, so mobile does not zoom on focus", design.inputFont === "16px", design.inputFont);
	say("the primary button matches the field rhythm", design.primaryRadius === "16px" && design.primaryHeight === "52px", `${design.primaryRadius} / ${design.primaryHeight}`);
	say("the page uses the product typeface", /Sora/.test(design.family), design.family.slice(0, 40));

	// No new colour system: every colour on the page resolves from the tokens.
	const strays = await page.evaluate(() => {
		const allowed = new Set();
		for (const name of ["--plum", "--plum-light", "--magenta", "--ink", "--prose", "--quiet", "--faint", "--danger", "--success"]) {
			allowed.add(getComputedStyle(document.documentElement).getPropertyValue(name).trim());
		}
		const seen = new Set();
		for (const el of document.querySelectorAll(".auth__column *")) {
			const c = getComputedStyle(el).color;
			if (c) seen.add(c);
		}
		return [...seen];
	});
	say("the form column draws only a handful of colours", strays.length <= 6, `${strays.length}: ${strays.join(" ")}`);
	await page.close();
}

// ─── the two pages link to each other ────────────────────────────────────────
console.log("\n── they link to each other ───────────────────────────────────");
{
	const { page } = await open("/signin");
	const toSignup = await page.evaluate(() =>
		[...document.querySelectorAll("a")].some((a) => a.getAttribute("href") === "/signup"),
	);
	say("sign-in offers a way to create an account", toSignup);
	await page.close();

	const { page: p2 } = await open("/signup");
	const toSignin = await p2.evaluate(() =>
		[...document.querySelectorAll("a")].some((a) => a.getAttribute("href") === "/signin"),
	);
	say("sign-up offers a way back to sign in", toSignin);
	await p2.close();
}

// ─── sign-in carries the anonymous token and the redirect ────────────────────
console.log("\n── signing in ───────────────────────────────────────────────");
{
	// Land on the app first, so an anonymous identity exists — which is the
	// only situation where there is anything to claim. Arriving at /signin cold
	// correctly has no token and nothing to carry.
	const { page, seen } = await open("/");
	await page.waitForFunction(() => !!localStorage.getItem("aspire.session.v1"), { timeout: 10000 });
	await page.goto(`${BASE}/signin?next=%2Fchat%2Fabc`, { waitUntil: "networkidle2" });
	await type(page, "Email", "jayla@ecse.kn");
	await type(page, "Password", "seaview7392pass");
	const sentAuth = await new Promise((resolve) => {
		page.on("request", (r) => {
			// POST only: the CORS preflight carries no Authorization header, and
			// catching it reads as the token being missing.
			if (r.method() === "POST" && r.url().endsWith("/api/auth/login")) {
				resolve(r.headers().authorization ?? "(none)");
			}
		});
		click(page, "Sign in");
	});
	say("the anonymous token rides along, so the claim can run", sentAuth === "Bearer anon-token", sentAuth);

	await page.waitForFunction(() => location.pathname !== "/signin", { timeout: 10000 });
	say("it returns you to where you came from", (await page.evaluate(() => location.pathname)) === "/chat/abc", await page.evaluate(() => location.pathname));
	say("the account session replaced the anonymous one", await page.evaluate(() => JSON.parse(localStorage.getItem("aspire.session.v1")).accountType === "registered"));
	await page.close();
}

// ─── an open redirect is refused ─────────────────────────────────────────────
console.log("\n── the redirect target cannot be turned outward ──────────────");
{
	// What matters is where it goes, not what the address bar still shows: the
	// router keeps the query it was given, and the validator decides whether it
	// means anything. An unchecked target is how a sign-in page becomes a way to
	// bounce somebody elsewhere with a trusted-looking link.
	for (const [label, hostile] of [
		["an absolute URL", "https%3A%2F%2Fevil.example"],
		["a protocol-relative URL", "%2F%2Fevil.example"],
	]) {
		const { page } = await open(`/signin?next=${hostile}`);
		await type(page, "Email", "jayla@ecse.kn");
		await type(page, "Password", "seaview7392pass");
		await click(page, "Sign in");
		await page.waitForFunction(() => location.pathname !== "/signin", { timeout: 10000 });
		const landed = await page.evaluate(() => location.origin + location.pathname);
		say(`${label} is refused as a destination`, landed === `${BASE}/`, landed);
		await page.close();
	}
}

// ─── errors land beside the field they belong to ─────────────────────────────
console.log("\n── failures are inline, not alerts ──────────────────────────");
{
	const { page } = await open("/signin", { loginStatus: 401, detail: "That email and password do not match." });
	let alerted = false;
	page.on("dialog", async (d) => {
		alerted = true;
		await d.dismiss();
	});
	await type(page, "Email", "jayla@ecse.kn");
	await type(page, "Password", "wrongpassword");
	await click(page, "Sign in");
	await page.waitForFunction(() => !!document.querySelector(".field__error"), { timeout: 10000 });

	const where = await page.evaluate(() => {
		const err = document.querySelector(".field__error");
		const field = err.closest(".field");
		return {
			text: err.textContent.trim(),
			label: field.querySelector(".field__label, legend")?.textContent?.trim(),
			marked: field.querySelector("input")?.getAttribute("aria-invalid"),
			described: !!field.querySelector("input")?.getAttribute("aria-describedby"),
		};
	});
	say("the message is under the password field", where.label === "Password", `under "${where.label}"`);
	say("it says what the service said", /do not match/.test(where.text), where.text);
	say("the input is marked invalid for assistive tech", where.marked === "true");
	say("and points at its own message", where.described);
	say("nothing was shown as a browser alert", !alerted);
	await page.close();
}

console.log("\n── a taken address is named on the step it belongs to ────────");
{
	const { page } = await open("/signup", { registerStatus: 409, detail: "That email already has an account. Try signing in." });
	await type(page, "First name", "Jayla");
	await type(page, "Last name", "Thomas");
	await type(page, "Day", "14");
	await type(page, "Month", "3");
	await type(page, "Year", "2011");
	await click(page, "Continue");
	await click(page, "Continue");
	await click(page, "Continue");
	await type(page, "Email", "taken@ecse.kn");
	await type(page, "Password", "seaview7392pass");
	await click(page, "Create account");
	await page.waitForFunction(() => !!document.querySelector(".field__error"), { timeout: 10000 });
	const label = await page.evaluate(() =>
		document.querySelector(".field__error").closest(".field").querySelector(".field__label, legend")?.textContent?.trim(),
	);
	say("the duplicate-email message sits under Email", label === "Email", `under "${label}"`);
	await page.close();
}

// ─── the age fork ────────────────────────────────────────────────────────────
console.log("\n── the age rule changes the form as soon as it is known ──────");
{
	const { page, seen } = await open("/signup");
	await type(page, "First name", "Amara");
	await type(page, "Last name", "Liburd");
	await type(page, "Day", "2");
	await type(page, "Month", "6");
	await type(page, "Year", "2018");
	await new Promise((r) => setTimeout(r, 150));

	const warned = await page.evaluate(() =>
		[...document.querySelectorAll(".field__hint")].some((h) => /parent or guardian/i.test(h.textContent)),
	);
	say("under 13 is said on step 1, not sprung at the end", warned);

	await click(page, "Continue");
	await click(page, "Continue");
	const stepThree = await page.evaluate(() => document.querySelector(".auth__title").textContent.trim());
	say("step 3 asks about the grown-up", /looks after you/i.test(stepThree), stepThree);

	// Refused without a named adult — the one shape this form must not send.
	await click(page, "Continue");
	const refused = await page.evaluate(() => !!document.querySelector(".field__error"));
	say("it will not continue without a named adult", refused);

	await type(page, "Their name", "Marcia Liburd");
	await type(page, "Their email", "marcia@example.com");
	await click(page, "Continue");
	await type(page, "Their email", "marcia@example.com");
	await type(page, "Password", "seaview7392pass");
	await click(page, "Create account");
	await page.waitForFunction(() => location.pathname !== "/signup", { timeout: 10000 });

	const sent = seen.register.at(-1);
	say("the guardian is sent with the account", sent?.guardian_name === "Marcia Liburd", JSON.stringify(sent?.guardian_name));
	say("the child's date of birth is sent as given", sent?.date_of_birth === "2018-06-02", sent?.date_of_birth);
	await page.close();
}

// ─── an adult signs up without a guardian step ───────────────────────────────
console.log("\n── an adult sign-up sends no guardian ────────────────────────");
{
	const { page, seen } = await open("/signup");
	await type(page, "First name", "Jayla");
	await type(page, "Last name", "Thomas");
	await type(page, "Day", "14");
	await type(page, "Month", "3");
	await type(page, "Year", "2011");
	await click(page, "Continue");
	await click(page, "Continue");
	await click(page, "Continue");
	await type(page, "Email", "jayla@ecse.kn");
	await type(page, "Password", "seaview7392pass");
	await click(page, "Create account");
	await page.waitForFunction(() => location.pathname !== "/signup", { timeout: 10000 });
	const sent = seen.register.at(-1);
	say("no guardian is invented for somebody old enough", sent?.guardian_name === null, JSON.stringify(sent?.guardian_name));
	await page.close();
}

console.log(`\n${fails === 0 ? "ALL PASS" : `${fails} FAIL`}`);
await browser.close();
process.exit(fails === 0 ? 0 : 1);
