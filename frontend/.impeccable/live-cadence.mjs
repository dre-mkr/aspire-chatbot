/**
 * The reveal's cadence against the real service, not a stub.
 *
 * The stubs prove the rule; only the running backend proves the feel, because
 * only it produces the arrival pattern the reveal is being paced against — real
 * retrieval latency, real token gaps, real markdown. This asks it a question and
 * watches the transcript every animation frame, reporting the three numbers that
 * describe what the reader actually experienced:
 *
 *   time to first word   — how long the orb was alone
 *   worst gap            — the longest the screen sat unchanged mid-answer
 *   final jump           — how much text appeared in the single last frame
 *
 * The third is the one the recording was made about. A reveal that strands
 * content shows it here as a large number: everything the typewriter stepped
 * past arrives at once when the finished answer replaces the revealed one.
 *
 *   node .impeccable/preview-server.mjs &
 *   node .impeccable/live-cadence.mjs "How are ASPIRE savings invested?"
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";

const BASE = process.env.PREVIEW ?? "http://localhost:4173";
const QUESTION = process.argv[2] ?? "How are ASPIRE savings invested?";
const STALL_MS = 400;

const browser = await puppeteer.launch({ headless: "new" });
const p = await browser.newPage();
await p.setViewport({ width: 1280, height: 900 });

/**
 * Timestamps the wire itself, so the orb's time can be attributed.
 *
 * "Nothing on screen" is two different faults wearing the same face: the
 * service not having sent a word yet, and the client holding words it already
 * has. Only one of them is this repository's reveal. Teeing the response body
 * separates them — `firstDelta` is when the first token existed in the browser,
 * and everything after that is the client's to answer for.
 */
await p.evaluateOnNewDocument(() => {
	window.__wire = { firstDelta: null, lastDelta: null, textEnd: null, done: null };
	const real = window.fetch;
	window.fetch = async (input, init) => {
		const url = typeof input === "string" ? input : (input?.url ?? "");
		if (!url.includes("/chat/stream")) return real(input, init);
		const response = await real(input, init);
		// A clone reads the same bytes without consuming the body the app needs.
		const probe = response.clone();
		void (async () => {
			const reader = probe.body.getReader();
			const decode = new TextDecoder();
			let buffered = "";
			for (;;) {
				const { done, value } = await reader.read();
				if (done) break;
				buffered += decode.decode(value, { stream: true });
				const frames = buffered.split("\n\n");
				buffered = frames.pop();
				for (const frame of frames) {
					const line = frame.trim();
					if (!line.startsWith("data:")) continue;
					let event;
					try {
						event = JSON.parse(line.slice(5));
					} catch {
						continue;
					}
					const now = performance.now();
					if (event.type === "TEXT_MESSAGE_CONTENT") {
						window.__wire.firstDelta ??= now;
						window.__wire.lastDelta = now;
					} else if (event.type === "TEXT_MESSAGE_END") {
						window.__wire.textEnd = now;
					} else if (event.type === "CUSTOM") {
						window.__wire.done = now;
					}
				}
			}
		})();
		return response;
	};
});
await p.goto(`${BASE}/`, { waitUntil: "networkidle2" });
await p.evaluate(() => localStorage.clear());
await p.goto(`${BASE}/`, { waitUntil: "networkidle2" });

await p.evaluate(() => {
	window.__samples = [];
	const read = () => {
		const turn = [...document.querySelectorAll(".transcript .turn--assistant")].pop();
		const answer = turn?.querySelector(".answer");
		// Only the rendered blocks. `.answer` also carries a visually-hidden
		// label for screen readers, and counting it would report the answer as
		// having text from the moment the turn mounted.
		const text = [...(answer?.children ?? [])]
			.filter((el) => el.tagName === "P" || el.tagName === "UL")
			.map((el) => el.textContent)
			.join("\n");
		window.__samples.push({ t: performance.now(), text });
		window.__raf = requestAnimationFrame(read);
	};
	read();
});

await p.click("#aspire-composer");
await p.type("#aspire-composer", QUESTION);
const asked = await p.evaluate(() => performance.now());
await p.keyboard.press("Enter");

await p.waitForFunction(() => !document.querySelector(".composer__send--stop"), {
	timeout: 120000,
	polling: 50,
});
await new Promise((r) => setTimeout(r, 900));

const samples = await p.evaluate(() => {
	cancelAnimationFrame(window.__raf);
	return window.__samples;
});

const withText = samples.filter((s) => s.text.length > 0);
const first = withText[0];
// The last sample the text actually CHANGED on — not the last sample recorded.
// The recorder runs on past the end of the answer, so using its final frame
// reported the length of the recording rather than the length of the reveal.
const last =
	[...withText].reverse().find((s, i, all) => {
		const older = all[i + 1];
		return !older || s.text.length !== older.text.length;
	}) ?? withText[withText.length - 1];
let worst = 0;
let worstAt = 0;
let rewrite = null;
for (let i = 1; i < withText.length; i += 1) {
	const gap = withText[i].t - withText[i - 1].t;
	if (withText[i].text.length > withText[i - 1].text.length && gap > worst) {
		worst = gap;
		worstAt = withText[i - 1].t;
	}
	if (!withText[i].text.startsWith(withText[i - 1].text) && !rewrite) {
		rewrite = `"...${withText[i - 1].text.slice(-40)}" → "...${withText[i].text.slice(-40)}"`;
	}
}
// The single last change: how much landed in one frame at the end.
let jump = 0;
for (let i = withText.length - 1; i > 0; i -= 1) {
	if (withText[i].text.length !== withText[i - 1].text.length) {
		jump = withText[i].text.length - withText[i - 1].text.length;
		break;
	}
}

let fails = 0;
const say = (label, ok, detail = "") => {
	if (!ok) fails += 1;
	console.log(`  ${ok ? "PASS" : "FAIL"}  ${label}${detail ? ` — ${detail}` : ""}`);
};

const wire = await p.evaluate(() => window.__wire);

console.log(`\n── "${QUESTION}" against the running service ──`);
console.log(`     ${last.text.length} characters revealed over ${Math.round(last.t - first.t)}ms`);
console.log(`     worst gap mid-answer ${Math.round(worst)}ms (at +${Math.round(worstAt - first.t)}ms)`);
console.log(`     last frame added ${jump} characters`);
// What changed, if anything, once the turn's payload arrived. This is the
// number the recording was made about: everything the reveal had stranded used
// to land here, in one frame, seconds after the answer looked finished.
const lastBefore = [...withText].reverse().find((s) => s.t <= wire.done);
const settleJump = last.text.length - (lastBefore?.text.length ?? 0);

console.log("\n     where the waiting went:");
console.log(`       ${String(Math.round(wire.firstDelta - asked)).padStart(6)}ms  the service, before its first token`);
console.log(`       ${String(Math.round(first.t - wire.firstDelta)).padStart(6)}ms  the client, before its first word`);
console.log(`       ${String(Math.round(wire.lastDelta - wire.firstDelta)).padStart(6)}ms  the service, writing`);
console.log(`       ${String(Math.round(wire.textEnd - wire.lastDelta)).padStart(6)}ms  until the text was declared final`);
console.log(`       ${String(Math.round(wire.done - wire.textEnd)).padStart(6)}ms  follow-ups and persistence, after that`);
console.log(`       ${String(Math.round(last.t - wire.textEnd)).padStart(6)}ms  the reveal, after the text was final\n`);

say(`no gap mid-answer reaches ${STALL_MS}ms`, worst < STALL_MS, `${Math.round(worst)}ms`);
say(
	"the client adds under 400ms to the service's own wait",
	first.t - wire.firstDelta < 400,
	`${Math.round(first.t - wire.firstDelta)}ms`,
);
// Not measured against the last token: when the service delivers a whole answer
// in one burst — which it often does — the reveal is *supposed* to outlast it.
// What must not outlast anything is the finishing pace once the text is known
// to be final, which is bounded below by `MIN_RATE_ENDED`.
say(
	"the reveal finishes within 1.5s of the text being final",
	last.t - wire.textEnd < 1500,
	`${Math.round(last.t - wire.textEnd)}ms`,
);
say(
	"the turn settling adds nothing to the screen",
	settleJump === 0,
	`${settleJump} characters after the payload`,
);
say("nothing already on screen is rewritten", rewrite === null, rewrite ?? "");
say("the answer does not land in one frame at the end", jump < 60, `${jump} characters`);

console.log(`\n${fails === 0 ? "ALL PASS" : `${fails} FAIL`}`);
await browser.close();
process.exit(fails === 0 ? 0 : 1);
