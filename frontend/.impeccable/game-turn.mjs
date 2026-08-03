/**
 * A game start renders as ONE turn: the card, and nothing beside it.
 *
 *   node .impeccable/game-turn.mjs
 *
 * Runs against the REAL backend (port 8021 by default), not a stub. The whole
 * point of this fix is what a live model does when asked to play, so stubbing
 * the reply would test the stub. Only the games endpoints are left alone --
 * they are the same service.
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";

const BASE = process.argv[2] ?? "http://localhost:4173";
const API = process.argv[3] ?? "http://localhost:8000";

let fails = 0;
const say = (n, label, ok, detail = "") => {
	if (!ok) fails += 1;
	console.log(`  ${ok ? "PASS" : "FAIL"}  ${n}. ${label}${detail ? " — " + detail : ""}`);
};
const settle = (ms = 600) => new Promise((r) => setTimeout(r, ms));

const browser = await puppeteer.launch({ headless: "new" });

async function open({ language = "en" } = {}) {
	const page = await browser.newPage();
	await page.setViewport({ width: 1280, height: 900 });
	// The API base is baked in at build time (VITE_ASPIRE_API_URL, default
	// :8000), so the backend has to be there rather than being redirected here.
	await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await page.evaluate((lang) => {
		localStorage.clear();
		localStorage.setItem(
			"aspire.voice.prefs.v1",
			JSON.stringify({ autoSpeak: false, speed: "1", language: lang }),
		);
	}, language);
	await page.reload({ waitUntil: "networkidle2" });
	await settle(400);
	return page;
}

const ask = async (page, text) => {
	await page.type("#aspire-composer", text);
	await page.keyboard.press("Enter");
	await page.waitForFunction(
		() => !document.querySelector(".composer__send--stop"),
		{ timeout: 90000 },
	);
	await settle(1200);
};

/** What the transcript actually contains, by kind. */
const shape = (page) =>
	page.evaluate(() => {
		const turns = [...document.querySelectorAll(".transcript > *")];
		return turns.map((el) => {
			if (el.classList.contains("turn--user")) return { kind: "user" };
			if (el.querySelector(".game")) return { kind: "game" };
			if (el.classList.contains("turn--assistant")) {
				return {
					kind: "assistant-text",
					text: (el.querySelector(".answer")?.innerText ?? "").trim().slice(0, 90),
				};
			}
			if (el.classList.contains("follow-ups")) {
				return {
					kind: "chips",
					chips: [...el.querySelectorAll(".follow-up")].map((c) => c.innerText.trim()),
				};
			}
			return { kind: el.className };
		});
	});

const chips = (page) =>
	page.evaluate(() =>
		[...document.querySelectorAll(".follow-up")].map((c) => c.innerText.trim()),
	);

const puzzle = (page) =>
	page.evaluate(() => {
		const tray = [...document.querySelectorAll(".game__tray .tile--tray")].map((t) =>
			t.innerText.trim(),
		);
		const statement = document.querySelector(".game__prompt, .game__statement")?.innerText ?? "";
		return { letters: tray.join(""), statement: statement.trim().slice(0, 60) };
	});

console.log("\n═══ Game turn renders as the card alone ═══\n");

/* 1-3 ── five phrasings, none may produce a prose turn. */
const PHRASINGS = [
	"Can we play the word scramble?",
	"What about scramble?",
	"I'm bored, quiz me",
	"play true or false",
	"can I do a word puzzle",
];

let duplicated = 0;
let started = 0;
for (const phrase of PHRASINGS) {
	const page = await open();
	await ask(page, phrase);
	const turns = await shape(page);
	const prose = turns.filter((t) => t.kind === "assistant-text");
	const games = turns.filter((t) => t.kind === "game");
	if (games.length) started += 1;
	// THE invariant. Not "the model always starts a game" -- whether a given
	// phrasing starts one or asks which one is game-selection behaviour that
	// this change deliberately does not touch, and it varies run to run. What
	// must never happen is a card and prose in the same turn.
	if (games.length && prose.length) duplicated += 1;
	console.log(
		`    "${phrase}" -> ${turns.map((t) => t.kind).join(" + ")}` +
			(prose.length ? `  [prose: ${JSON.stringify(prose[0].text)}]` : ""),
	);
	await page.close();
}
say(
	"1-3",
	"Five phrasings: no turn ever renders a card and prose together",
	duplicated === 0,
	`${started}/5 started a game; ${duplicated} of those also showed prose`,
);

/* 4 ── no chip reveals or hints at the answer. */
{
	const page = await open();
	await ask(page, "Can we play the word scramble?");
	const shown = await chips(page);
	const { letters } = await puzzle(page);
	// The scramble's letters are the answer's letters. Any chip containing a
	// word built from exactly them has solved it.
	const sorted = (w) => [...w.toLowerCase()].sort().join("");
	const leaks = shown.filter((c) =>
		c
			.split(/\W+/)
			.some((word) => word.length === letters.length && sorted(word) === sorted(letters)),
	);
	say(
		4,
		"No suggestion chip reveals the answer",
		shown.length === 0 && leaks.length === 0,
		`letters=${letters} chips=${JSON.stringify(shown)}`,
	);

	/* 5 ── refresh mid-game restores one turn, not two. */
	const url = await page.evaluate(() => location.href);
	await page.goto(url, { waitUntil: "networkidle2" });
	await settle(1500);
	const after = await shape(page);
	say(
		5,
		"Refresh mid-game: the game restores as a single turn",
		after.filter((t) => t.kind === "game").length === 1 &&
			after.filter((t) => t.kind === "assistant-text").length === 0,
		after.map((t) => t.kind).join(" + "),
	);

	/* 6 ── a normal question straight after is unaffected. */
	await ask(page, "What is the ASPIRE programme?");
	const mixed = await shape(page);
	const texts = mixed.filter((t) => t.kind === "assistant-text");
	say(
		6,
		"A normal question right after a game still answers as text",
		texts.length === 1 && texts[0].text.length > 0,
		mixed.map((t) => t.kind).join(" + "),
	);
	await page.close();
}

/* 7 ── leave a game, ask for another: still one turn. */
{
	const page = await open();
	await ask(page, "Can we play the word scramble?");
	await page.click(".game__leave");
	await settle(1200);
	await ask(page, "play true or false");
	const turns = await shape(page);
	say(
		7,
		"After leaving a game, starting another is still one turn",
		turns.filter((t) => t.kind === "game").length === 1 &&
			turns.filter((t) => t.kind === "assistant-text").length === 0,
		turns.map((t) => t.kind).join(" + "),
	);
	await page.close();
}

/* 8 ── Español and Français. */
for (const [language, phrase] of [
	["es", "Juguemos a las palabras revueltas"],
	["fr", "On joue au jeu des mots mélangés"],
]) {
	const page = await open({ language });
	await ask(page, phrase);
	const turns = await shape(page);
	const games = turns.filter((t) => t.kind === "game").length;
	const texts = turns.filter((t) => t.kind === "assistant-text");
	const shown = await chips(page);
	say(
		`8${language}`,
		`${language.toUpperCase()}: no duplicate turn, no answer in any chip`,
		// No content exists in these languages, so the honest outcome is a
		// decline: one explanatory turn, no card, and nothing to leak.
		games + texts.length === 1 && shown.every((c) => !/[A-Z]{4,}/.test(c)),
		`turns=${turns.map((t) => t.kind).join(" + ")} chips=${JSON.stringify(shown)}`,
	);
	await page.close();
}

await browser.close();
console.log(`\n${fails === 0 ? "All green." : `${fails} failing.`}\n`);
process.exit(fails === 0 ? 0 : 1);
