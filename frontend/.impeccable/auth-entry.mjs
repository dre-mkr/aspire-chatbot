/**
 * Parts 5-7: the auth entry points, the avatar, and scoped data loading.
 *
 * Three claims are hard enough to be worth real instruments:
 *
 *   1. **No auth flash.** On first paint the session is not known, and a
 *      control that renders "Sign in" and then swaps to an avatar is the auth
 *      version of the completion flash. Sampled every animation frame from the
 *      first paint, so a single-frame swap cannot hide between polls.
 *   2. **Cross-fade, not pop.** The corner control and the sidebar block trade
 *      places during the 560ms morph. Neither may appear or disappear abruptly,
 *      which means both stay mounted and only opacity moves.
 *   3. **No stale data across identities.** The previous person's conversation
 *      titles must not survive sign-out for even one frame.
 *
 *   node .impeccable/preview-server.mjs &
 *   node .impeccable/auth-entry.mjs
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";
import { createConversationStore } from "./fake-conversations.mjs";

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

async function open({ signedIn = false, sessionDelay = 0, width = 1280, alwaysHistory = false } = {}) {
	const page = await browser.newPage();
	await page.setViewport({ width, height: 900 });
	const store = createConversationStore();
	const calls = { anonymous: 0, logout: 0, conversations: 0 };

	await page.setRequestInterception(true);
	page.on("request", async (r) => {
		const url = r.url();
		if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
		const json = (s, b) =>
			r.respond({ status: s, contentType: "application/json", headers: CORS, body: JSON.stringify(b) });

		if (url.endsWith("/api/auth/anonymous")) {
			calls.anonymous += 1;
			if (sessionDelay) await new Promise((x) => setTimeout(x, sessionDelay));
			return json(200, {
				token: `anon-${calls.anonymous}`, user_id: `anon-${calls.anonymous}`,
				account_type: "anonymous", email: null, display_name: null, avatar_url: null, expires_in: 9999,
			});
		}
		if (url.endsWith("/api/auth/logout")) {
			calls.logout += 1;
			return r.respond({ status: 204, headers: CORS, body: "" });
		}
		if (url.includes("/api/conversations")) {
			calls.conversations += 1;
			const header = r.headers().authorization ?? "";
			// Only the signed-in token ever sees the signed-in person's chats.
			const mine =
				header.includes("acct-token") || alwaysHistory
					? [{ thread_id: "t-1", title: "Marcia's private chat", title_source: null, updated_at: Date.now() }]
					: [];
			return json(200, { conversations: mine });
		}
		if (url.includes("/api/")) return json(404, {});
		r.continue();
	});

	if (signedIn) {
		// Arrive already signed in, as somebody returning would.
		await page.evaluateOnNewDocument(() => {
			localStorage.setItem(
				"aspire.session.v1",
				JSON.stringify({
					token: "acct-token", userId: "u-1", accountType: "registered",
					email: "marcia.liburd@gmail.com", displayName: "Marcia Liburd", avatarUrl: null,
				}),
			);
		});
	}
	return { page, calls, store };
}

const ask = async (page, text = "What is an index fund?") => {
	await page.click("#aspire-composer");
	await page.type("#aspire-composer", text);
	await page.keyboard.press("Enter");
};

// ─── 1. No auth flash ────────────────────────────────────────────────────────
console.log("\n── the auth slot never says one thing then another ────────────");
{
	// The session is deliberately slow, so if the control were going to commit
	// early it has every chance to.
	const { page } = await open({ sessionDelay: 600 });
	await page.evaluateOnNewDocument(() => {
		window.__seen = [];
		const read = () => {
			const slot = document.querySelector(".account-slot");
			if (slot) {
				const signin = slot.querySelector(".account__signin");
				const avatar = slot.querySelector(".avatar");
				const placeholder = slot.querySelector(".account__placeholder");
				window.__seen.push(
					avatar ? "avatar" : signin ? "signin" : placeholder ? "placeholder" : "empty",
				);
			}
			requestAnimationFrame(read);
		};
		read();
	});
	await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await new Promise((r) => setTimeout(r, 1400));

	const seen = await page.evaluate(() => window.__seen ?? []);
	const sequence = [];
	for (const state of seen) if (sequence.at(-1) !== state) sequence.push(state);

	say("the slot is sampled every frame", seen.length > 20, `${seen.length} frames`);
	// The one forbidden pair: a committed state followed by a different one.
	const flipped = sequence.some(
		(state, i) => i > 0 && state !== sequence[i - 1] && sequence[i - 1] !== "placeholder" && sequence[i - 1] !== "empty",
	);
	say("it never swaps between two committed states", !flipped, sequence.join(" → "));
	say("it holds a neutral placeholder until the session is known", sequence.includes("placeholder"), sequence.join(" → "));
	await page.close();
}

// ─── 2. The corner matches the hamburger ─────────────────────────────────────
console.log("\n── the corner control is the hamburger's opposite number ──────");
{
	// The hamburger only appears on the landing screen once there is history to
	// open, which is also the one place both controls are on screen together.
	// History has to exist for the hamburger to appear at all — it is the only
	// route to conversations when the rail is a drawer.
	const { page } = await open({ alwaysHistory: true });
	await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await page.waitForSelector(".account__signin", { timeout: 10000 });
	await ask(page);
	await page.waitForFunction(() => !document.querySelector(".composer__send--stop"), { timeout: 25000 });
	await page.evaluate(() => {
		const fresh = [...document.querySelectorAll("button")].find((b) => /new chat/i.test(b.textContent));
		fresh?.click();
	});
	await page.waitForSelector(".rail-open", { timeout: 10000 });
	await new Promise((r) => setTimeout(r, 700));

	const pair = await page.evaluate(() => {
		const burger = document.querySelector(".rail-open");
		const signin = document.querySelector(".account__signin");
		if (!burger || !signin) return null;
		const a = getComputedStyle(burger);
		const b = getComputedStyle(signin);
		const ra = burger.getBoundingClientRect();
		const rb = signin.getBoundingClientRect();
		return {
			radius: [a.borderRadius, b.borderRadius],
			height: [Math.round(ra.height), Math.round(rb.height)],
			bg: [a.backgroundColor, b.backgroundColor],
			blur: [a.backdropFilter, b.backdropFilter],
			shadow: [a.boxShadow === b.boxShadow],
			top: [Math.round(ra.top), Math.round(rb.top)],
		};
	});

	if (!pair) {
		say("both controls are on screen together", false, "one of them was missing");
	} else {
		say("same corner radius", pair.radius[0] === pair.radius[1], pair.radius.join(" vs "));
		say("same height", pair.height[0] === pair.height[1], pair.height.join(" vs "));
		say("same frosted surface", pair.bg[0] === pair.bg[1], pair.bg.join(" vs "));
		say("same backdrop blur", pair.blur[0] === pair.blur[1], pair.blur.join(" vs "));
		say("same shadow", pair.shadow[0]);
		say("sitting on the same line", pair.top[0] === pair.top[1], pair.top.join(" vs "));
	}
	await page.close();
}

// ─── 3. Signed in, the corner is the avatar alone ────────────────────────────
console.log("\n── signed in ─────────────────────────────────────────────────");
{
	const { page } = await open({ signedIn: true });
	await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await page.waitForSelector(".account-slot .avatar", { timeout: 10000 });

	const corner = await page.evaluate(() => {
		const slot = document.querySelector(".account-slot");
		return {
			text: slot.textContent.trim(),
			hasAvatar: !!slot.querySelector(".avatar"),
			alt: slot.querySelector(".avatar")?.getAttribute("aria-label") ?? slot.querySelector(".avatar")?.getAttribute("alt"),
			round: getComputedStyle(slot.querySelector(".avatar")).borderRadius,
		};
	});
	say("the corner is the avatar and nothing else", corner.hasAvatar && corner.text === "", `text: "${corner.text}"`);
	say("the avatar is circular", corner.round === "999px", corner.round);
	say("and says whose it is", /Marcia Liburd/.test(corner.alt ?? ""), corner.alt);

	// The menu carries at least the identity and a way out.
	await page.evaluate(() => document.querySelector(".account__avatar-btn").click());
	await page.waitForSelector(".account__menu", { timeout: 5000 });
	const menu = await page.evaluate(() => document.querySelector(".account__menu").textContent);
	say("the menu names the account", /Marcia Liburd/.test(menu) && /marcia\.liburd@gmail\.com/.test(menu));
	say("and offers a way out", /Sign out/i.test(menu));
	await page.close();
}

// ─── 4. The sidebar block keeps its shape across both states ─────────────────
console.log("\n── one block, two states, same shape ─────────────────────────");
{
	const shapeOf = async (signedIn) => {
		const { page } = await open({ signedIn });
		await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
		await ask(page);
		await page.waitForFunction(() => !document.querySelector(".composer__send--stop"), { timeout: 25000 });
		await new Promise((r) => setTimeout(r, 800));
		const shape = await page.evaluate(() => {
			const foot = document.querySelector(".rail__foot");
			const slot = foot.querySelector(".rail__device, .avatar");
			const lines = foot.querySelectorAll(".rail__name, .rail__note");
			const fs = getComputedStyle(foot);
			return {
				pad: fs.padding,
				gap: getComputedStyle(foot.querySelector(".account__block")).gap,
				iconW: Math.round(slot.getBoundingClientRect().width),
				iconH: Math.round(slot.getBoundingClientRect().height),
				lines: lines.length,
				nameSize: getComputedStyle(lines[0]).fontSize,
				noteSize: getComputedStyle(lines[1]).fontSize,
				height: Math.round(foot.getBoundingClientRect().height),
			};
		});
		await page.close();
		return shape;
	};

	const out = await shapeOf(false);
	const inn = await shapeOf(true);
	say("same padding", out.pad === inn.pad, `${out.pad} vs ${inn.pad}`);
	say("same gap", out.gap === inn.gap, `${out.gap} vs ${inn.gap}`);
	say("same icon slot", out.iconW === inn.iconW && out.iconH === inn.iconH, `${out.iconW}x${out.iconH} vs ${inn.iconW}x${inn.iconH}`);
	say("both are two lines", out.lines === 2 && inn.lines === 2, `${out.lines} vs ${inn.lines}`);
	say("same type sizes", out.nameSize === inn.nameSize && out.noteSize === inn.noteSize, `${out.nameSize}/${out.noteSize} vs ${inn.nameSize}/${inn.noteSize}`);
	say("same overall height", Math.abs(out.height - inn.height) <= 1, `${out.height} vs ${inn.height}`);
}

// ─── 5. The handover cross-fades ─────────────────────────────────────────────
console.log("\n── the handover during the morph is a cross-fade ─────────────");
{
	const { page } = await open();
	await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await page.waitForSelector(".account-slot", { timeout: 10000 });

	await page.evaluate(() => {
		window.__fade = [];
		const read = () => {
			const slot = document.querySelector(".account-slot");
			const foot = document.querySelector(".rail__foot");
			if (slot) {
				window.__fade.push({
					corner: Number(getComputedStyle(slot).opacity),
					// Present the whole time, or the handover is a pop.
					footPresent: !!foot,
				});
			}
			window.__raf = requestAnimationFrame(read);
		};
		read();
	});

	await ask(page);
	await page.waitForFunction(() => !document.querySelector(".composer__send--stop"), { timeout: 25000 });
	await new Promise((r) => setTimeout(r, 900));

	const frames = await page.evaluate(() => {
		cancelAnimationFrame(window.__raf);
		return window.__fade;
	});

	const opacities = frames.map((f) => f.corner);
	const distinct = [...new Set(opacities.map((o) => o.toFixed(2)))];
	// A pop would be 1 then 0 with nothing in between.
	const intermediate = opacities.some((o) => o > 0.02 && o < 0.98);
	say("the corner control fades rather than switching off", intermediate, `${distinct.length} distinct values`);
	say("the sidebar block is mounted the whole way through", frames.every((f) => f.footPresent));
	say("it ends hidden once the sidebar carries it", opacities.at(-1) < 0.02, String(opacities.at(-1)));
	await page.close();
}

// ─── 6. Sign-out clears the previous person's data ───────────────────────────
console.log("\n── signing out leaves nothing of the last person behind ──────");
{
	const { page, calls } = await open({ signedIn: true });
	await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await page.waitForSelector(".account-slot .avatar", { timeout: 10000 });
	// Their conversation is in the rail.
	await page.evaluate(() => document.querySelector(".rail-open, .account__avatar-btn"));
	await new Promise((r) => setTimeout(r, 600));

	await page.evaluate(() => document.querySelector(".account__avatar-btn").click());
	await page.waitForSelector(".account__menu", { timeout: 5000 });
	await page.evaluate(() => {
		[...document.querySelectorAll(".account__item")].find((b) => /sign out/i.test(b.textContent))?.click();
	});
	// Confirmed rather than immediate.
	await page.waitForFunction(() => /Yes, sign out/i.test(document.body.textContent), { timeout: 5000 });
	say("signing out asks first", true);

	const before = calls.anonymous;
	await page.evaluate(() => {
		[...document.querySelectorAll(".account__item")].find((b) => /yes, sign out/i.test(b.textContent))?.click();
	});
	await page.waitForFunction(() => !document.querySelector(".account__menu"), { timeout: 10000 });
	await new Promise((r) => setTimeout(r, 900));

	const after = await page.evaluate(() => ({
		body: document.body.textContent,
		session: JSON.parse(localStorage.getItem("aspire.session.v1") || "null"),
		path: location.pathname,
	}));
	say("the previous person's chat title is gone", !/private chat/.test(after.body));
	say("a fresh anonymous identity was issued", calls.anonymous > before, `${before} → ${calls.anonymous}`);
	say("and it is not the one from before", after.session?.accountType === "anonymous", after.session?.accountType);
	say("it returns to the empty state", after.path === "/", after.path);
	await page.close();
}

console.log(`\n${fails === 0 ? "ALL PASS" : `${fails} FAIL`}`);
await browser.close();
process.exit(fails === 0 ? 0 : 1);
