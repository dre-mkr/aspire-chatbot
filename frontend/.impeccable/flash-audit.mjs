/**
 * The completion flash: audit + frame-accurate verification.
 *
 * Three instruments, because the artifact has three parts and each needs its
 * own kind of evidence:
 *
 *   1. A lifecycle log. `Transcript` can be instrumented with mount/unmount
 *      effects (see --instrumented), and a MutationObserver on `.transcript`
 *      records whether the DOM node holding the answer is REPLACED at
 *      completion or kept. A node that survives cannot flash; a node that is
 *      swapped will. The observer is the load-bearing one: it cannot be fooled
 *      by a component that merely re-renders, and it needs no source changes.
 *
 *   2. A per-frame geometry sampler, running on rAF for the whole window, so
 *      the answer's vertical position is known at every painted frame rather
 *      than at two hopeful point reads.
 *
 *   3. A CDP screencast, cropped to the message band, reduced to mean luminance
 *      per frame. A 400ms artifact is three frames at 30fps and is not
 *      reliably visible by eye, so it is measured rather than watched.
 *
 * Frame timestamps and page timestamps are put on one clock via
 * `performance.timeOrigin`, so every frame can be placed relative to the
 * instant the answer settled.
 *
 * Backend is stubbed. Every assertion is about the client's render lifecycle.
 *
 *   node .impeccable/preview-server.mjs &
 *   node .impeccable/flash-audit.mjs [base] [--case=name] [--title-off]
 *
 * Review-only. Never built or shipped.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer";

const args = process.argv.slice(2);
const BASE = args.find((a) => !a.startsWith("--")) ?? "http://localhost:4173";
/** Answers `/api/title` with a failure, to take title generation out of the picture. */
const TITLE_OFF = args.includes("--title-off");
const ONLY = args.find((a) => a.startsWith("--case="))?.slice(7);
const OUT = fileURLToPath(new URL("./flash-out", import.meta.url));
mkdirSync(OUT, { recursive: true });

const CORS = {
	"Access-Control-Allow-Origin": "*",
	"Access-Control-Allow-Methods": "GET,POST,OPTIONS",
	"Access-Control-Allow-Headers": "Content-Type",
};

const SHORT = "Index funds spread your money across many companies at once.";
const LONG = [
	"An **index fund** holds a little of every company on a list, so instead of betting on one name you own a slice of hundreds at the same time.",
	"That matters because nobody can reliably pick the winners in advance, and the fund does not need anybody to.",
	"- You own a slice of hundreds of companies at once",
	"- Fees are low because nothing has to be chosen",
	"- It rebalances itself as the list changes",
	"Over a long enough stretch this is the boring approach that tends to beat the exciting one, and it asks almost nothing of you.",
].join("\n\n");

/**
 * Long enough to actually be interrupted.
 *
 * The typewriter reveals ~100 words a second, so `LONG` is over in 480ms — a
 * window too narrow to click a button in while a screencast is starving the
 * main thread. The stop case needs seconds, not milliseconds.
 */
const VERY_LONG = Array.from(
	{ length: 9 },
	(_, i) =>
		`Paragraph ${i + 1}. An index fund holds a little of every company on a list, so instead of betting on one name you own a slice of hundreds at the same time, and that matters because nobody can reliably pick the winners in advance.`,
).join("\n\n");

const SOURCES = [
	{
		content: "An index fund tracks a market index rather than picking stocks.",
		metadata: { question: "What is an index fund?" },
	},
	{
		content: "Low fees compound in the investor's favour over decades.",
		metadata: { category: "Investing basics" },
	},
];

let fails = 0;
const say = (label, ok, detail = "") => {
	if (!ok) fails += 1;
	console.log(`  ${ok ? "PASS" : "FAIL"}  ${label}${detail ? " — " + detail : ""}`);
};

const browser = await puppeteer.launch({
	headless: "new",
	args: ["--force-device-scale-factor=1", "--disable-lcd-text"],
});

async function open({
	reply = SHORT,
	sources = [],
	followUps = [],
	chatStatus = 200,
	game = false,
	width = 1280,
	height = 900,
} = {}) {
	const page = await browser.newPage();
	await page.setViewport({ width, height, deviceScaleFactor: 1 });

	await page.setRequestInterception(true);
	page.on("request", async (r) => {
		if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
		if (r.url().endsWith("/chat")) {
			const sent = JSON.parse(r.postData() || "{}");
			if (chatStatus !== 200) {
				return r.respond({
					status: chatStatus,
					contentType: "application/json",
					headers: CORS,
					body: '{"detail":"The assistant is temporarily unavailable."}',
				});
			}
			return r.respond({
				status: 200,
				contentType: "application/json",
				headers: CORS,
				body: JSON.stringify({
					reply,
					thread_id: sent.thread_id || "t-server",
					sources,
					follow_ups: followUps,
					// `game_started`, which is what the client actually reads. Spelled
					// `started_game` this silently fell through to the prose path and
					// the case tested nothing it claimed to.
					...(game
						? {
								game_started: {
									game_type: "true_false",
									display_name: "True or false",
									kind: "statement",
									total: 5,
								},
							}
						: {}),
				}),
			});
		}
		if (r.url().endsWith("/api/title")) {
			if (TITLE_OFF) {
				return r.respond({ status: 500, contentType: "application/json", headers: CORS, body: "{}" });
			}
			return r.respond({
				status: 200,
				contentType: "application/json",
				headers: CORS,
				body: JSON.stringify({ title: "Index fund basics" }),
			});
		}
		if (r.url().includes("/api/games/state")) {
			// A real card, not a 404. The widget case exists to check that a turn
			// whose whole content is a card behaves like every other turn at
			// completion, and a 404 renders nothing at all — which would have the
			// case quietly passing on an empty transcript.
			return r.respond({
				status: 200,
				contentType: "application/json",
				headers: CORS,
				body: JSON.stringify({
					active: game,
					game: game
						? {
								game_type: "true_false",
								display_name: "True or false",
								prompt: {
									kind: "statement",
									text: "An index fund lets you own a slice of many companies at once.",
									position: 1,
									total: 5,
									choices: [],
								},
								supports_hints: false,
								hint_level: 0,
								max_hint_level: 0,
								hints: [],
								attempts: 0,
								solved: 0,
								skipped: 0,
								language: "en",
								persona: null,
							}
						: null,
				}),
			});
		}
		if (r.url().includes("/api/games/") || r.url().includes("/api/eligibility")) {
			return r.respond({ status: 404, contentType: "application/json", headers: CORS, body: "{}" });
		}
		r.continue();
	});

	await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await page.evaluate(() => localStorage.clear());
	await page.reload({ waitUntil: "networkidle2" });
	return page;
}

/**
 * Starts both in-page instruments: the node-identity observer and the rAF
 * geometry sampler.
 *
 * The observer watches `.transcript`'s own children. That is the question the
 * whole audit turns on — not "did React render" but "is the element holding
 * the answer the same element before and after completion".
 */
async function instrument(page) {
	await page.evaluate(() => {
		window.__origin = performance.timeOrigin;
		window.__life ??= [];
		window.__dom = [];
		window.__geom = [];

		const root = document.querySelector(".transcript");
		const seen = new WeakMap();
		let n = 0;
		const tag = (el) => {
			if (!seen.has(el)) seen.set(el, ++n);
			return seen.get(el);
		};
		for (const el of root.children) tag(el);

		new MutationObserver((records) => {
			for (const rec of records) {
				for (const el of rec.removedNodes) {
					if (el.nodeType !== 1) continue;
					window.__dom.push({
						t: performance.now(),
						event: "removed",
						node: tag(el),
						cls: el.className,
						busy: el.getAttribute("aria-busy"),
					});
				}
				for (const el of rec.addedNodes) {
					if (el.nodeType !== 1) continue;
					window.__dom.push({
						t: performance.now(),
						event: "added",
						node: tag(el),
						cls: el.className,
						enter: el.hasAttribute("data-enter"),
					});
				}
			}
		}).observe(root, { childList: true, subtree: false });

		// Once a turn has been seen revealing, that is the turn under test for the
		// rest of the run — `stop` appends an error turn after it, and "the last
		// assistant turn" would silently start measuring that instead.
		let tracked = null;
		const sample = () => {
			const turns = [...document.querySelectorAll(".transcript .turn--assistant")];
			const busyNow = turns.find((t) => t.getAttribute("aria-busy") === "true");
			if (busyNow) tracked = busyNow;
			const turn = tracked?.isConnected ? tracked : turns[turns.length - 1];
			if (turn) {
				const p = turn.querySelector(".answer > p, .answer > ul");
				const tr = turn.getBoundingClientRect();
				const pr = p ? p.getBoundingClientRect() : null;
				const cs = getComputedStyle(turn);
				// The prose band: the answer's own words, excluding the tail. This
				// is "the message content area" the artifact was reported against,
				// and cropping to it is what keeps the action row's intended
				// appearance from reading as a defect.
				// Everything the answer actually shows, minus the reserved tail and
				// the screen-reader heading. Generic on purpose: a game turn and an
				// eligibility turn are a card and nothing else, and the band has to
				// find them too.
				const blocks = [...turn.querySelectorAll(".answer > :not(.answer__tail):not(.sr-only)")];
				const first = blocks[0]?.getBoundingClientRect();
				const last = blocks[blocks.length - 1]?.getBoundingClientRect();
				// Measured against the transcript's own box, not the viewport, so
				// neither scrolling nor the hero→chat morph can masquerade as the
				// answer moving. This is the number the reflow check turns on.
				const rootTop = root.getBoundingClientRect().top;
				window.__geom.push({
					t: performance.now(),
					node: tag(turn),
					turnTop: Math.round(tr.top * 100) / 100,
					turnHeight: Math.round(tr.height * 100) / 100,
					textTop: pr ? Math.round(pr.top * 100) / 100 : null,
					// Layout position, scroll-free.
					textOffset: pr ? Math.round((pr.top - rootTop) * 100) / 100 : null,
					turnOffset: Math.round((tr.top - rootTop) * 100) / 100,
					proseTop: first ? Math.round(first.top * 100) / 100 : null,
					proseBottom: last ? Math.round(last.bottom * 100) / 100 : null,
					// Layout positions, which `rise`'s translateY cannot move. The
					// reflow question is "did the box change", and measuring it
					// through a transform reports the entrance as a 12px jump.
					layoutTop: turn.offsetTop,
					layoutHeight: turn.offsetHeight,
					textLayoutTop: p ? p.offsetTop : null,
					opacity: Number(cs.opacity),
					// `animationName` is a static cascade value — it says "rise" for
					// the life of the element whether or not anything is playing.
					// The Web Animations API is the only thing that answers the
					// question actually being asked: is an animation RUNNING now.
					// `currentTime` is the discriminator the whole replay check turns
					// on: an entrance that started when the turn ARRIVED has a large
					// clock by the time the answer settles, even on a stalled machine.
					// One that started AT completion reads near zero — and that is the
					// bug, stated in the only terms that cannot be faked by jank.
					running: turn
						.getAnimations()
						.filter((a) => a.playState === "running")
						.map((a) => ({
							name: a.animationName || "anon",
							clock: Math.round(Number(a.currentTime) || 0),
						})),
					busy: turn.getAttribute("aria-busy"),
					actions: !!turn.querySelector(".answer-actions"),
				});
			}
			window.__raf = requestAnimationFrame(sample);
		};
		sample();
	});
}

/**
 * Records a screencast over `run`, returning frames stamped on the page clock.
 */
async function record(page, run) {
	const client = await page.createCDPSession();
	const frames = [];
	client.on("Page.screencastFrame", async ({ data, sessionId, metadata }) => {
		frames.push({ data, ts: metadata.timestamp });
		try {
			await client.send("Page.screencastFrameAck", { sessionId });
		} catch {}
	});
	// jpeg and downscaled, not full-size png. Encoding every frame at 1280x900
	// starves the main thread badly enough to stall the rAF sampler for 300ms+,
	// which shows up as phantom movement when a frame is paired with a stale
	// geometry sample. Three quarters scale costs nothing here — the signal is a
	// whole band of text appearing or vanishing — and buys back the frame rate.
	// `analyse` reads the true scale off the decoded image, so crops stay in CSS
	// pixels at the call site.
	await client.send("Page.startScreencast", {
		format: "jpeg",
		quality: 80,
		everyNthFrame: 1,
		maxWidth: 960,
		maxHeight: 675,
	});
	await run();
	await client.send("Page.stopScreencast");
	await client.detach();
	return frames;
}

/**
 * Decodes captured frames in-page (the browser already has a PNG decoder) and
 * reduces the crop to mean luminance and an ink count — the pixels that are
 * text rather than the panel behind them.
 */
async function analyse(page, frames) {
	return page.evaluate(
		async (list) => {
			const canvas = document.createElement("canvas");
			const ctx = canvas.getContext("2d", { willReadFrequently: true });
			const out = [];
			for (const f of list) {
				const box = f.crop;
				const img = new Image();
				await new Promise((res, rej) => {
					img.onload = res;
					img.onerror = rej;
					img.src = `data:image/jpeg;base64,${f.data}`;
				});
				canvas.width = img.width;
				canvas.height = img.height;
				ctx.drawImage(img, 0, 0);
				// The screencast is downscaled; crops are quoted in CSS pixels.
				const k = img.width / 1280;
				const x = Math.max(0, Math.min(Math.round(box.x * k), img.width - 1));
				const y = Math.max(0, Math.min(Math.round(box.y * k), img.height - 1));
				const w = Math.max(1, Math.min(Math.round(box.width * k), img.width - x));
				const h = Math.max(1, Math.min(Math.round(box.height * k), img.height - y));
				const { data } = ctx.getImageData(x, y, w, h);
				let sum = 0;
				let ink = 0;
				let firstInkRow = -1;
				for (let row = 0; row < h; row += 1) {
					let rowInk = 0;
					for (let col = 0; col < w; col += 1) {
						const i = (row * w + col) * 4;
						const lum = 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2];
						sum += lum;
						// The transcript is dark text on a light panel, so "ink" is the
						// DARK pixels: the words themselves. A blanked frame has none,
						// which makes this the most direct signal there is — it counts
						// the letters on screen.
						if (lum < 140) {
							rowInk += 1;
							ink += 1;
						}
					}
					if (rowInk > 3 && firstInkRow === -1) firstInkRow = row;
				}
				out.push({
					t: f.t,
					fresh: f.fresh,
					anchored: f.anchored,
					opacity: f.opacity,
					moving: f.moving,
					lum: Math.round((sum / (w * h)) * 1000) / 1000,
					ink,
					// Absolute viewport row of the answer's first line of pixels.
					inkTop: firstInkRow === -1 ? null : y + firstInkRow,
				});
			}
			return out;
		},
		frames,
	);
}

async function ask(page, question) {
	await page.waitForSelector("#aspire-composer", { timeout: 10000 });
	await page.click("#aspire-composer");
	await page.type("#aspire-composer", question);
	await page.keyboard.press("Enter");
}

/** Resolves once nothing is revealing and the turn has settled. */
async function settled(page, { widget = false, error = false } = {}) {
	await page.waitForFunction(
		(w, e) => {
			if (document.querySelector('.transcript [aria-busy="true"]')) return false;
			if (w) return !!document.querySelector(".game, .scramble, .truefalse");
			if (e) return !!document.querySelector(".failure");
			return document.querySelectorAll(".transcript .answer-actions").length > 0;
		},
		{ timeout: 20000 },
		widget,
		error,
	);
}

const dump = (page) =>
	page.evaluate(() => {
		cancelAnimationFrame(window.__raf);
		return { life: window.__life ?? [], dom: window.__dom, geom: window.__geom, origin: window.__origin };
	});

// ─── the cases ───────────────────────────────────────────────────────────────

const CASES = {
	short: { reply: SHORT },
	long: { reply: LONG },
	sources: { reply: LONG, sources: SOURCES, followUps: ["How much do I need to start?", "What is compound interest?"] },
	second: { reply: LONG, second: true },
	widget: { reply: SHORT, game: true, widget: true },
	error: { reply: SHORT, chatStatus: 503, error: true },
	/**
	 * Stop, pressed mid-reveal.
	 *
	 * This is the closest thing the app has to a stream failing in flight: the
	 * reply arrives whole and the typewriter reveals it locally, so there is no
	 * mid-transfer error — but `stop` abandons the reveal at an arbitrary word
	 * and settles only what was shown. It runs through `settleRevealed` rather
	 * than `finishStream`, a second path to the same swap, and it must not flash
	 * either.
	 */
	stopped: { reply: VERY_LONG, stop: true, error: true },
};

const report = {};

for (const [name, cfg] of Object.entries(CASES)) {
	if (ONLY && ONLY !== name) continue;
	console.log(`\n── ${name}${TITLE_OFF ? " (title generation disabled)" : ""} ───────────────`);
	const page = await open(cfg);

	// A second message needs a first one to have landed and gone quiet.
	if (cfg.second) {
		await ask(page, "What is an index fund?");
		await settled(page);
		await new Promise((r) => setTimeout(r, 900));
	}

	await instrument(page);

	const frames = await record(page, async () => {
		await ask(page, cfg.second ? "And what about bonds?" : "What is an index fund?");
		if (cfg.stop) {
			// Part-way through, so there is something revealed to keep — but while
			// the reveal is definitely still running. Waiting a fixed beat after the
			// first paragraph raced the end of a reveal that had been slowed by the
			// screencast; waiting for a second block is bounded by the content.
			// Polled on a timer, not on rAF: the screencast starves animation
			// frames, and an rAF-polled condition can sleep straight through a
			// reveal and then never be true again.
			await page.waitForFunction(
				() => document.querySelectorAll('.transcript [aria-busy="true"] .answer > p').length >= 3,
				{ timeout: 20000, polling: 50 },
			);
			await page.click(".composer__send--stop");
		}
		await settled(page, cfg).catch(() => {});
		// Long enough to cover a 400ms entry animation plus the title round trip.
		await new Promise((r) => setTimeout(r, 1200));
	});

	const { life, dom, geom, origin } = await dump(page);

	// The completion instant: the moment the streaming node left the transcript,
	// or failing that the moment `aria-busy` disappeared from the sampler.
	// Before the fix this was the instant the streaming node was removed. With
	// one node throughout there is nothing to remove, so it is the instant
	// `aria-busy` came off the turn. A widget or an error turn never streams at
	// all, so for those it is the moment the turn itself arrived — the only
	// event in the run, and the one its entrance is allowed to be attached to.
	const removal = dom.find((d) => d.event === "removed" && d.busy === "true");
	const busyEnd = geom.find((g, i) => i > 0 && geom[i - 1].busy === "true" && g.busy !== "true");
	const arrival = dom.filter((d) => d.event === "added" && /turn--assistant/.test(d.cls || "")).at(-1);
	const t0 = removal?.t ?? busyEnd?.t ?? arrival?.t ?? null;

	/**
	 * Each frame gets its OWN crop, anchored to where the answer actually was
	 * when that frame was painted.
	 *
	 * A fixed crop cannot tell "the content blinked" apart from "the page moved
	 * under the crop" — and on a first message the hero→chat morph is moving the
	 * whole column for 560ms, straight through the moment being measured. The
	 * tracking crop removes that confound entirely: what it measures is the
	 * answer's own pixels, wherever they are.
	 */
	const nearest = (t) =>
		geom.reduce((best, g) => (best === null || Math.abs(g.t - t) < Math.abs(best.t - t) ? g : best), null);
	// Was the column itself moving when this sample was taken? The thread
	// scroll-follows the answer, and a crop pinned to a viewport position 20ms
	// stale during a smooth scroll slices off a line of text — which the ink
	// count then reports as content that came or went.
	const movingAt = (g) => {
		const i = geom.indexOf(g);
		if (i < 1) return true;
		return Math.abs(geom[i - 1].turnTop - g.turnTop) > 1;
	};

	const stamped = frames
		// Frame stamps are Unix seconds; page stamps are relative to timeOrigin.
		// One clock, so every frame can be placed against the completion instant.
		.map((f) => ({ ...f, t: f.ts * 1000 - origin }))
		.map((f) => {
			const g = nearest(f.t);
			// A frame paired with a geometry sample from another era is measuring
			// the page having moved, not the answer having changed.
			const fresh = g != null && Math.abs(g.t - f.t) < 30;
			// Cropped to the prose band, not the whole turn: the action row and the
			// sources chip are SUPPOSED to become visible at completion, and a crop
			// that includes them cannot tell that apart from the answer blinking.
			const top = g?.proseTop ?? g?.turnTop;
			const bottom = g?.proseBottom ?? (g ? g.turnTop + g.turnHeight : null);
			// Whether this frame's crop is actually pinned to a turn, or is the
			// fallback region used when no turn exists yet. Unanchored frames must
			// never contribute a baseline: the fallback box lands over the hero and
			// its ink would read as an answer that later "vanished".
			const anchored = top != null && bottom != null && bottom > top;
			return {
				...f,
				fresh,
				anchored,
				// Carried onto the frame so the pixel checks can ask what the turn
				// was doing when it was painted, not merely where it was.
				opacity: g?.opacity ?? null,
				moving: g == null || movingAt(g),
				crop: anchored
					? { x: 300, y: Math.max(0, top - 6), width: 680, height: Math.min(600, bottom - top + 12) }
					: { x: 300, y: 180, width: 680, height: 300 },
			};
		});

	const series = (await analyse(page, stamped)).sort((a, b) => a.t - b.t);

	// Geometry either side of completion, from the sampler.
	const beforeG = t0 == null ? null : [...geom].reverse().find((g) => g.t < t0);
	const afterG = geom.at(-1);

	// A turn that ARRIVES at t0 is allowed its entrance — that is a widget or an
	// error turn appearing, and animating in once is correct. What must never
	// happen is an entrance on a turn that was already on screen.
	// A turn REPLACED at completion is the bug. A turn that merely ARRIVES there
	// — a widget, an error, or a reply so short that the reveal and the arrival
	// are the same moment — is allowed its one entrance. The difference is
	// whether an assistant turn was also torn out at t0.
	const removedAtT0 = dom.some(
		(d) => d.event === "removed" && /turn--assistant/.test(d.cls || "") && t0 != null && Math.abs(d.t - t0) < 60,
	);
	/**
	 * When the arriving turn's own entrance actually finished.
	 *
	 * Read from the Web Animations API rather than assumed from the declared
	 * 400ms: recording a screencast starves the main thread, and under that load
	 * a 400ms entrance can still be playing 900ms after the element appeared. A
	 * fixed grace measures the machine; this measures the animation.
	 */
	// The first moment the tracked turn is genuinely at rest: nothing playing,
	// fully opaque. Everything after this must be motionless.
	const quietFrom = geom.find((g) => t0 != null && g.t >= t0 && g.running.length === 0 && g.opacity === 1)?.t ?? t0;
	// An animation whose own clock is near zero at completion STARTED at
	// completion. On a turn that was already on screen there is no innocent
	// reading of that: it is the entry animation replaying.
	//
	// Stated against the node's own history rather than against a time window:
	// an animation is a REPLAY only if it started at completion on a turn that
	// was already on screen well before it. A short reply whose reveal lasts
	// 40ms has its arrival and its completion in the same breath, and its one
	// legitimate entrance was being flagged by any window tight enough to be
	// meaningful. `nodeSwapped` is what catches the original bug — where the
	// turn animates because it is genuinely new — and this catches a regression
	// the new architecture could still have: a stable node re-armed at t0.
	const trackedNode = afterG?.node;
	const firstSeen = geom.find((g) => g.node === trackedNode)?.t;
	/**
	 * A replay, stated as what the eye actually sees rather than as an
	 * animation's start time.
	 *
	 * Deriving "this animation began at t0" from `currentTime` looked exact and
	 * was not: when the screencast starves the main thread the animation clock
	 * lags wall time, so a perfectly innocent entrance drifts until it appears to
	 * have started at completion. Opacity has no such problem. An arriving turn
	 * goes 0 → 1 and never returns; a turn that was already up and then replays
	 * its entrance goes 1 → 0 → 1. That second shape is the bug, it is the shape
	 * the recording showed, and no amount of jank can counterfeit it.
	 */
	const wasOpaque = geom.some((g) => t0 != null && g.t < t0 && g.node === trackedNode && g.opacity === 1);
	const dropsAfter = geom.some((g) => t0 != null && g.t >= t0 - 5 && g.node === trackedNode && g.opacity < 0.9);
	const replayed = wasOpaque && dropsAfter;
	const animAfter = geom.some((g) => g.t > quietFrom + 16 && g.running.length > 0);

	/**
	 * Two windows, because "after the last streamed token" is the spec and the
	 * last token lands ON t0.
	 *
	 *   settled  — every frame from completion (or, for a turn that arrives at
	 *              completion, from the far side of its entrance). Nothing in the
	 *              prose band may change here, in either direction.
	 *   boundary — the last frame before t0 against the first frame at or after
	 *              it. Text APPEARING across this line is the final token and is
	 *              correct; text VANISHING is the bug.
	 */
	const settleFrom = quietFrom;
	const window_ = (t0 == null ? series : series.filter((f) => f.t >= settleFrom)).filter((f) => f.fresh && !f.moving);
	const deltas = window_.map((f, i) => (i === 0 ? 0 : Math.round((f.lum - window_[i - 1].lum) * 1000) / 1000));
	const inkDeltas = window_.map((f, i) => (i === 0 ? 0 : f.ink - window_[i - 1].ink));

	/**
	 * The blank, stated as a DIP rather than as a difference across t0.
	 *
	 * Text that was on screen immediately before completion and is gone
	 * immediately after it is the artifact, and saying it that way needs no
	 * judgement about whether the turn "already existed": a turn that is merely
	 * arriving has nothing in the band beforehand, so it has no baseline to fall
	 * from and cannot produce a dip. A turn that was fully drawn and then went
	 * blank produces one that is impossible to miss.
	 *
	 * `ink` — the count of dark pixels, i.e. the letters — because on this light
	 * UI a blank frame is the panel showing through, which mean luminance
	 * registers only weakly but a letter count registers absolutely.
	 */
	const baseline = Math.max(0, ...series.filter((f) => f.anchored && f.fresh && f.opacity === 1 && t0 != null && f.t >= t0 - 300 && f.t < t0).map((f) => f.ink));
	const after = series.filter((f) => f.anchored && f.fresh && t0 != null && f.t >= t0 && f.t < t0 + 600);
	const trough = after.length ? Math.min(...after.map((f) => f.ink)) : baseline;
	// A baseline that low means there was nothing drawn there to lose.
	const hadContent = baseline > 500;
	const blanked = hadContent && trough < baseline * 0.5;

	report[name] = { t0, life, dom, geom, series: window_, deltas, baseline, trough };

	const lifeLine = life.map((l) => `${l.what}#${l.key}:${l.event}@${Math.round(l.t)}`).join("  ");
	console.log(`  lifecycle: ${lifeLine || "(source not instrumented)"}`);
	console.log(
		`  dom      : ${dom.map((d) => `${d.event} node${d.node}${d.enter ? "+data-enter" : ""}@${Math.round(d.t)}`).join("  ") || "(none)"}`,
	);
	console.log(`  t0       : ${t0 == null ? "n/a" : Math.round(t0)}ms   frames in window ${window_.length}`);
	console.log(
		`  geometry : node ${beforeG?.node} → ${afterG?.node}   textTop ${beforeG?.textLayoutTop} → ${afterG?.textLayoutTop}   height ${beforeG?.layoutHeight} → ${afterG?.layoutHeight}`,
	);
	console.log(`  opacity  : ${[...new Set(geom.filter((g) => t0 != null && g.t >= t0).map((g) => g.opacity.toFixed(2)))].join(" ")}`);
	console.log(
		`  running  : ${geom
			.filter((g) => t0 != null && g.t >= t0 - 5 && g.t <= t0 + 400)
			.flatMap((g) => g.running.map((a) => `${a.name}@${a.clock}`))
			.slice(0, 8)
			.join(" ") || "(nothing at t0)"}`,
	);
	console.log(`  lum      : min ${Math.min(...window_.map((f) => f.lum))} max ${Math.max(...window_.map((f) => f.lum))}`);
	console.log(`  ink      : ${window_.map((f) => f.ink).join(" ")}`);
	console.log(`  Δlum     : ${deltas.map((d) => d.toFixed(2)).join(" ")}`);

	// ── assertions ──
	// Taken from the MutationObserver first and the rAF sampler second. The
	// observer runs off a microtask and records every removal; the sampler runs
	// off requestAnimationFrame and can be starved for 300ms by the screencast,
	// which on a short reply left no sample before t0 at all — and a comparison
	// against nothing silently PASSES. The load-bearing assertion of this suite
	// must not be the one that can be starved into agreeing.
	const nodeSwapped = removedAtT0 || !!(beforeG && afterG && beforeG.node !== afterG.node);
	const remounted = (() => {
		const un = life.filter((l) => l.event === "unmount");
		return un.length > 0 && life.some((m) => m.event === "mount" && un.some((u) => Math.abs(m.t - u.t) < 50));
	})();
	// A frame measurably darker, then measurably brighter, is the flash.
	// Thresholds set between the noise and the signal, not at the noise.
	// Measured: jpeg/antialiasing chatter runs to ~2.8 mean-luminance units and
	// ~50 ink pixels on a small crop; the artifact this suite exists for moved
	// luminance by 136 units and erased 13,233 ink pixels. Anything in between
	// would be a new phenomenon worth a new test, not a quiet threshold nudge.
	const inkFloor = Math.max(300, Math.max(...window_.map((f) => f.ink), 1) * 0.15);
	const moved = deltas.filter((d) => Math.abs(d) > 3);
	const inkMoved = inkDeltas.filter((d) => Math.abs(d) > inkFloor);
	// Layout offset, not viewport position: the answer must not move WITHIN the
	// transcript when the action row mounts beneath it.
	const shift =
		beforeG && afterG && beforeG.textLayoutTop != null && afterG.textLayoutTop != null
			? Math.abs(afterG.textLayoutTop - beforeG.textLayoutTop)
			: 0;

	say(`${name}: assistant turn keeps its DOM node through completion`, !nodeSwapped, nodeSwapped ? (removedAtT0 ? "an assistant turn was torn out at t0" : `node ${beforeG?.node} → ${afterG?.node}`) : "");
	if (life.length) say(`${name}: no unmount/remount at completion`, !remounted, remounted ? "unmount+mount within 50ms" : "");
	// Deliberately says nothing about OTHER turns appearing at t0 — `stop` adds
	// its "you stopped this answer" turn at exactly that moment, and that turn is
	// arriving, so its entrance is correct. What matters is the turn under test.
	say(
		`${name}: entry animation does not replay at completion`,
		!animAfter && !replayed,
		replayed
			? "an animation started at t0 on a turn that was already up"
			: animAfter
				? "still animating after the turn went quiet"
				: "",
	);
	say(
		`${name}: message area does not blank at completion`,
		!blanked,
		hadContent ? `ink ${baseline} before → ${trough} lowest after` : "nothing drawn before t0 to lose",
	);
	// Not asked of a widget turn: a game card is a live control with its own
	// ambient motion (the stars, the badge), and "holds perfectly still" is not
	// a property it is supposed to have. Its blank check and node identity above
	// are the parts that carry over.
	if (name !== "widget")
		say(
			`${name}: prose band is still for every frame after completion`,
			moved.length === 0 && inkMoved.length === 0,
			moved.length
				? `${moved.length} frame(s), worst Δlum ${moved.reduce((a, b) => (Math.abs(b) > Math.abs(a) ? b : a), 0)}`
				: inkMoved.length
					? `ink moved by ${inkMoved.reduce((a, b) => (Math.abs(b) > Math.abs(a) ? b : a), 0)}`
					: `${window_.length} frames`,
		);
	if (name === "stopped") {
		// Stopping mid-word settles LESS text than was on screen a moment before,
		// by design — so "the box is the same size either side of t0" is not a
		// question that means anything here. What must hold is that once the
		// truncated answer has settled, it never moves again.
		const settledGeom = geom.filter((g) => g.t >= quietFrom);
		const heights = new Set(settledGeom.map((g) => g.layoutHeight));
		const tops = new Set(settledGeom.map((g) => g.textLayoutTop));
		say(
			`${name}: truncated answer is stable once settled`,
			heights.size <= 1 && tops.size <= 1,
			`height ${[...heights].join("/")}, textTop ${[...tops].join("/")} over ${settledGeom.length} frames`,
		);
	} else if (name !== "widget" && name !== "error") {
		say(`${name}: answer text holds its vertical position`, shift < 1, `${shift.toFixed(2)}px`);
		// The text can hold position and the turn still grow underneath it — the
		// action row and the sources chip mount at completion. Everything below
		// moves by that much, which is the reflow in the recording.
		const grew = beforeG && afterG ? afterG.layoutHeight - beforeG.layoutHeight : 0;
		say(`${name}: turn does not change height at completion`, Math.abs(grew) < 1, `${grew > 0 ? "+" : ""}${grew.toFixed(2)}px`);
	}

	await page.close();
}

writeFileSync(`${OUT}/report${TITLE_OFF ? "-titleoff" : ""}.json`, JSON.stringify(report, null, 2));
console.log(`\n${fails === 0 ? "ALL PASS" : `${fails} FAIL`}`);
await browser.close();
process.exit(fails === 0 ? 0 : 1);
