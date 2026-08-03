/**
 * Drift probe, games half. Drives the two game cards against the REAL games
 * service and measures every tappable control they paint, plus the header and
 * progress treatments, so the matrix carries measured values rather than values
 * read off the stylesheet.
 *
 * `/chat` is stubbed to announce a game; the games endpoints are left alone.
 * `/api/games/start` has its body rewritten so both game types are reachable.
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";

const BASE = process.argv[2] ?? "http://localhost:4173";
const API = process.argv[4] ?? "http://localhost:8000";
const CORS = {
	"Access-Control-Allow-Origin": "*",
	"Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
	"Access-Control-Allow-Headers": "Content-Type, Authorization, X-Aspire-Device",
};

const browser = await puppeteer.launch({ headless: "new" });
const settle = (ms = 500) => new Promise((r) => setTimeout(r, ms));

const PROBE = `(el) => {
  if (!el) return null;
  const s = getComputedStyle(el);
  const r = el.getBoundingClientRect();
  return {
    h: Math.round(r.height * 10) / 10,
    w: Math.round(r.width),
    radius: s.borderRadius,
    padding: s.padding,
    fs: s.fontSize,
    fw: s.fontWeight,
    border: s.borderTopWidth + " " + s.borderTopStyle,
    bg: s.backgroundImage !== "none" ? "gradient" : s.backgroundColor,
    color: s.color,
    shadow: s.boxShadow === "none" ? "none" : "yes",
  };
}`;

async function play(gameType, scale) {
	const p = await browser.newPage();
	await p.setViewport({ width: 1280, height: 1200 });
	await p.setRequestInterception(true);
	p.on("request", (r) => {
		if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
		if (r.url().endsWith("/chat")) {
			// The client answers a `game_started` turn by GETting the session
			// state, never by starting one — so the session has to exist against
			// this thread id before the reply lands.
			const threadId = JSON.parse(r.postData() ?? "{}").thread_id;
			return void fetch(`${API}/api/games/start`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					thread_id: threadId,
					persona: scale,
					language: "en",
					game_type: gameType,
				}),
			})
				.catch(() => {})
				.then(() =>
					r.respond({
						status: 200,
						contentType: "application/json",
						headers: CORS,
						body: JSON.stringify({
							reply: "",
							thread_id: threadId,
							sources: [],
							follow_ups: [],
							game_started: { game_type: gameType },
						}),
					}),
				);
		}
		r.continue();
	});
	await p.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await settle(300);
	await p.type("#aspire-composer", "let's play a game");
	await p.keyboard.press("Enter");
	const ok = await p
		.waitForSelector(".game", { timeout: 20000 })
		.then(() => true)
		.catch(() => false);
	if (!ok) {
		await p.close();
		return null;
	}
	await settle(700);
	return p;
}

const measure = async (p, sel) => p.$eval(sel, eval(PROBE)).catch(() => null);

const out = {};

/* ── Word scramble ─────────────────────────────────────────────────────── */
for (const scale of ["orion", "stella"]) {
	const p = await play("word_scramble", scale);
	if (!p) {
		out[`scramble/${scale}`] = "UNREACHABLE";
		continue;
	}
	out[`scramble/${scale}`] = {
		container: await measure(p, ".game"),
		head: await measure(p, ".game__head"),
		title: await measure(p, ".game__title"),
		sub: await measure(p, ".game__sub"),
		leave: await measure(p, ".game__leave"),
		progressStep: await measure(p, ".game__step"),
		progressKind: await p.evaluate(() => ({
			steps: document.querySelectorAll(".game__step").length,
			shape: "numbered circles",
		})),
		tileTray: await measure(p, ".tile--tray"),
		tileSlot: await measure(p, ".tile--slot"),
		btnClue: await measure(p, ".game__btn--clue"),
		btnQuiet: await measure(p, ".game__btn--quiet"),
		btnGhost: await measure(p, ".game__btn--ghost"),
		btnGo: await measure(p, ".game__btn--go"),
		btnGoDisabled: await p.evaluate(() => {
			const b = document.querySelector(".game__btn--go");
			return b?.disabled ? getComputedStyle(b).opacity : "not disabled";
		}),
		cardWidth: await p.evaluate(() => document.querySelector(".game")?.getBoundingClientRect().width),
	};
	if (scale === "orion") {
		// Real Tab traversal, so :focus-visible actually applies.
		out.focusRings = await p.evaluate(async () => {
			const seen = {};
			const els = [
				...document.querySelectorAll(
					".tile--tray, .game__btn, .game__leave, .tile--slot",
				),
			];
			for (const el of els.slice(0, 6)) {
				el.focus();
				const s = getComputedStyle(el);
				seen[el.className] = `${s.outlineWidth} ${s.outlineStyle} ${s.outlineColor} / offset ${s.outlineOffset}`;
			}
			return seen;
		});
	}
	await p.close();
}

/* ── True / false ──────────────────────────────────────────────────────── */
for (const scale of ["orion", "stella"]) {
	const p = await play("true_false", scale);
	if (!p) {
		out[`truefalse/${scale}`] = "UNREACHABLE";
		continue;
	}
	out[`truefalse/${scale}`] = {
		container: await measure(p, ".game"),
		head: await measure(p, ".game__head"),
		title: await measure(p, ".game__title"),
		sub: await measure(p, ".game__sub"),
		leave: await measure(p, ".game__leave"),
		progressStep: await measure(p, ".game__step"),
		progressKind: await p.evaluate(() => ({
			steps: document.querySelectorAll(".game__step").length,
			shape: "numbered circles",
		})),
		choice: await measure(p, ".tf__choice"),
		btnGhost: await measure(p, ".game__btn--ghost"),
		label: await measure(p, ".game__eyebrow"),
		statement: await measure(p, ".tf__statement"),
		cardWidth: await p.evaluate(() => document.querySelector(".game")?.getBoundingClientRect().width),
	};
	await p.close();
}

await browser.close();
console.log(JSON.stringify(out, null, 2));
