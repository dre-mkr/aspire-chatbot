/**
 * Does streamed audio actually play in a browser? (P14-C)
 *
 * `scripts/voice_probe.py` proves the SERVER streams — first byte at 221ms
 * instead of 1030ms. That says nothing about whether the client can consume it:
 * `speakStream` feeds bytes into a MediaSource SourceBuffer, and MSE is exactly
 * the kind of API that works in theory and throws `InvalidStateError` in
 * practice. Nothing else in the suite exercises it.
 *
 * This drives the real page, clicks Play on a real answer, and reports what the
 * audio element actually did: whether MSE was used, how many appends landed,
 * whether duration became a real number, and whether currentTime advanced.
 *
 *   node .impeccable/preview-server.mjs &
 *   node .impeccable/voice-stream.mjs
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";

const BASE = process.env.PREVIEW ?? "http://localhost:4173";
const QUESTION = process.argv[2] ?? "What is ASPIRE Day?";

const browser = await puppeteer.launch({
	headless: "new",
	// Without a real audio device the element still buffers and reports
	// duration; this stops Chrome refusing to start playback unprompted.
	args: ["--autoplay-policy=no-user-gesture-required", "--mute-audio"],
});
const p = await browser.newPage();
await p.setViewport({ width: 1280, height: 900 });

const consoleErrors = [];
p.on("console", (m) => {
	if (m.type() === "error") consoleErrors.push(m.text());
});
p.on("pageerror", (e) => consoleErrors.push(`pageerror: ${e.message}`));

/** Instrument MediaSource and Audio before any app code runs. */
await p.evaluateOnNewDocument(() => {
	window.__audio = {
		mseSupported:
			typeof MediaSource !== "undefined" &&
			MediaSource.isTypeSupported("audio/mpeg"),
		sourcesOpened: 0,
		appends: 0,
		appendErrors: 0,
		endOfStream: 0,
		elements: [],
		streamRequests: 0,
	};

	const RealMediaSource = window.MediaSource;
	if (RealMediaSource) {
		const realAdd = RealMediaSource.prototype.addSourceBuffer;
		RealMediaSource.prototype.addSourceBuffer = function (type) {
			window.__audio.sourcesOpened += 1;
			const buffer = realAdd.call(this, type);
			const realAppend = buffer.appendBuffer;
			buffer.appendBuffer = function (data) {
				window.__audio.appends += 1;
				try {
					return realAppend.call(this, data);
				} catch (error) {
					window.__audio.appendErrors += 1;
					throw error;
				}
			};
			return buffer;
		};
		const realEnd = RealMediaSource.prototype.endOfStream;
		RealMediaSource.prototype.endOfStream = function (...args) {
			window.__audio.endOfStream += 1;
			return realEnd.apply(this, args);
		};
	}

	const RealAudio = window.Audio;
	window.Audio = function (...args) {
		const el = new RealAudio(...args);
		window.__audio.elements.push(el);
		return el;
	};
	window.Audio.prototype = RealAudio.prototype;

	// Count which endpoint the client actually chose.
	const realFetch = window.fetch;
	window.fetch = (input, init) => {
		const url = typeof input === "string" ? input : (input?.url ?? "");
		if (url.includes("/api/voice/speak-stream")) window.__audio.streamRequests += 1;
		return realFetch(input, init);
	};
});

await p.goto(BASE, { waitUntil: "networkidle0", timeout: 60000 });

await p.click("#aspire-composer");
await p.type("#aspire-composer", QUESTION);
await p.keyboard.press("Enter");

// Wait for the answer to settle, which is when the Play control exists.
await p.waitForFunction(() => !document.querySelector(".composer__send--stop"), {
	timeout: 120000,
	polling: 100,
});

const playSelector = await p.evaluate(() => {
	const buttons = [...document.querySelectorAll("button")];
	const play = buttons.find((b) =>
		/play|listen|read aloud/i.test(
			`${b.getAttribute("aria-label") ?? ""} ${b.textContent ?? ""}`,
		),
	);
	if (!play) return null;
	play.setAttribute("data-probe-play", "1");
	return "[data-probe-play]";
});

if (!playSelector) {
	console.log("FAIL  no Play control found on the settled answer");
	console.log(
		"      buttons:",
		await p.evaluate(() =>
			[...document.querySelectorAll("button")]
				.map((b) => (b.getAttribute("aria-label") ?? b.textContent ?? "").trim())
				.filter(Boolean)
				.slice(0, 20),
		),
	);
	await browser.close();
	process.exit(1);
}

await p.click(playSelector);

// Give the stream time to open, append and start advancing.
await p
	.waitForFunction(
		() => {
			const el = window.__audio.elements.at(-1);
			return el && (el.duration > 0 || window.__audio.appends > 0);
		},
		{ timeout: 45000, polling: 100 },
	)
	.catch(() => {});
await new Promise((r) => setTimeout(r, 3500));

const report = await p.evaluate(() => {
	const a = window.__audio;
	const el = a.elements.at(-1);
	return {
		mseSupported: a.mseSupported,
		streamRequests: a.streamRequests,
		sourcesOpened: a.sourcesOpened,
		appends: a.appends,
		appendErrors: a.appendErrors,
		endOfStream: a.endOfStream,
		haveElement: Boolean(el),
		src: el ? el.src.slice(0, 12) : null,
		duration: el ? el.duration : null,
		currentTime: el ? el.currentTime : null,
		readyState: el ? el.readyState : null,
		error: el?.error ? el.error.code : null,
	};
});

console.log(`\n── streamed audio, "${QUESTION}" ──`);
for (const [k, v] of Object.entries(report)) {
	console.log(`   ${k.padEnd(16)} ${v}`);
}

let fails = 0;
const say = (label, ok, detail = "") => {
	if (!ok) fails += 1;
	console.log(`  ${ok ? "PASS" : "FAIL"}  ${label}${detail ? ` — ${detail}` : ""}`);
};

console.log("");
say("the client called /api/voice/speak-stream", report.streamRequests > 0);
say(
	"a MediaSource buffer was opened (or MSE unsupported, blob fallback)",
	report.sourcesOpened > 0 || !report.mseSupported,
	report.mseSupported ? `${report.sourcesOpened} opened` : "MSE unsupported here",
);
say(
	"audio bytes were appended without error",
	report.appends > 0 && report.appendErrors === 0,
	`${report.appends} appends, ${report.appendErrors} errors`,
);
say("the element reports a playable duration", Number(report.duration) > 0, `${report.duration}s`);
say("the element reports no media error", report.error === null, `code ${report.error}`);
say("playback advanced", Number(report.currentTime) > 0, `${report.currentTime}s`);
say(
	"no console errors",
	consoleErrors.length === 0,
	consoleErrors.slice(0, 3).join(" | "),
);

console.log(`\n${fails === 0 ? "ALL PASS" : `${fails} FAIL`}`);
await browser.close();
process.exit(fails === 0 ? 0 : 1);
