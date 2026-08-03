/**
 * Cross-surface drift probe.
 *
 * Measures the ACTUAL computed values of every tappable pill and every widget
 * container, in the real production preview, across the surfaces that render
 * them. Also checks the top-bar / fade-mask geometry, which cannot be read off
 * the stylesheet because the two numbers live 500 lines apart.
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";

const BASE = process.argv[2] ?? "http://localhost:4173";
const API = process.argv[3] ?? "http://localhost:8000";
const CORS = {
	"Access-Control-Allow-Origin": "*",
	"Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
	"Access-Control-Allow-Headers": "Content-Type, Authorization, X-Aspire-Device",
};

const A = {
	reply: "An **index fund** holds a little of every company on a list.\n\n- You own a slice of hundreds at once\n- Fees are low",
	thread_id: "t",
	sources: [
		{
			content: "An index fund tracks a market index.",
			metadata: { question: "What is an index fund?" },
		},
	],
	follow_ups: ["How much do I need to start?", "What is compound interest?"],
};

const browser = await puppeteer.launch({ headless: "new" });
const settle = (ms = 500) => new Promise((r) => setTimeout(r, ms));

/** Everything about a control that a consistency matrix needs. */
const PROBE = `(el) => {
  if (!el) return null;
  const s = getComputedStyle(el);
  const r = el.getBoundingClientRect();
  return {
    h: Math.round(r.height * 10) / 10,
    radius: s.borderRadius,
    padding: s.padding,
    fs: s.fontSize,
    fw: s.fontWeight,
    border: s.borderTopWidth + " " + s.borderTopStyle,
    borderColor: s.borderTopColor,
    bg: s.backgroundImage !== "none" ? "gradient" : s.backgroundColor,
    color: s.color,
    shadow: s.boxShadow === "none" ? "none" : "yes",
  };
}`;

async function page({ width = 1280, height = 900, lang = "en", elig = false } = {}) {
	const p = await browser.newPage();
	await p.setViewport({ width, height });
	await p.setRequestInterception(true);
	p.on("request", async (r) => {
		if (r.method() === "OPTIONS") return r.respond({ status: 204, headers: CORS });
		if (r.url().endsWith("/chat")) {
			if (elig) {
				const threadId = JSON.parse(r.postData() ?? "{}").thread_id;
				await fetch(`${API}/api/eligibility/start`, {
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({ thread_id: threadId, language: lang }),
				}).catch(() => {});
				return r.respond({
					status: 200,
					contentType: "application/json",
					headers: CORS,
					body: JSON.stringify({
						reply: "",
						thread_id: threadId,
						sources: [],
						follow_ups: [],
						eligibility_started: { check: "aspire_eligibility", language: lang },
					}),
				});
			}
			return r.respond({
				status: 200,
				contentType: "application/json",
				headers: CORS,
				body: JSON.stringify(A),
			});
		}
		if (r.url().includes("/api/games/"))
			return r.respond({ status: 404, contentType: "application/json", headers: CORS, body: "{}" });
		r.continue();
	});
	await p.evaluateOnNewDocument((l) => {
		window.localStorage.setItem(
			"aspire.voice.prefs.v1",
			JSON.stringify({ autoSpeak: false, speed: 1, language: l }),
		);
	}, lang);
	await p.goto(`${BASE}/`, { waitUntil: "networkidle2" });
	await settle(400);
	return p;
}

const measure = async (p, sel) =>
	p.$eval(sel, eval(PROBE)).catch(() => null);

const out = { pills: {}, containers: {}, geometry: {}, focus: {} };

/* ── Landing: starters ─────────────────────────────────────────────────── */
{
	const p = await page();
	out.pills["starter (landing chip)"] = await measure(p, ".starter");
	out.geometry.landing = await p.evaluate(() => {
		const t = document.querySelector(".thread");
		return {
			threadMask: getComputedStyle(t).maskImage?.slice(0, 60) ?? "none",
			threadPadTop: getComputedStyle(t).paddingTop,
			titlebar: !!document.querySelector(".titlebar"),
		};
	});
	await p.close();
}

/* ── Chat: answered, with follow-ups ───────────────────────────────────── */
{
	const p = await page();
	await p.type("#aspire-composer", "What is an index fund?");
	await p.keyboard.press("Enter");
	await p.waitForFunction(() => !document.querySelector(".composer__send--stop"), { timeout: 20000 });
	await settle(900);

	out.pills["follow-up (suggestion chip)"] = await measure(p, ".follow-up");
	out.pills["text-btn (Ask again)"] = await measure(p, ".text-btn");
	out.pills["sources__toggle"] = await measure(p, ".sources__toggle");
	out.pills["tool-btn (Explain it simply)"] = await measure(p, ".tool-btn");
	out.pills["composer__send"] = await measure(p, ".composer__send");
	out.pills["icon-btn--sm (copy)"] = await measure(p, ".icon-btn--sm");

	// Disabled send, for the disabled-state comparison.
	out.pills["composer__send:disabled"] = await p.evaluate(() => {
		const b = document.querySelector(".composer__send");
		if (!b?.disabled) return "not disabled at rest";
		return getComputedStyle(b).opacity;
	});

	out.geometry.chat = await p.evaluate(() => {
		const bar = document.querySelector(".titlebar");
		const thread = document.querySelector(".thread");
		const cs = getComputedStyle(thread);
		const bs = bar ? getComputedStyle(bar) : null;
		// Parse the first opaque stop out of the mask gradient.
		const mask = cs.maskImage ?? "none";
		const stop = /#000\s+(\d+)px|rgb\(0,\s*0,\s*0\)\s+(\d+)px/.exec(mask);
		return {
			barHeight: bar ? Math.round(bar.getBoundingClientRect().height) : null,
			barBg: bs?.backgroundColor ?? null,
			barBlur: bs?.backdropFilter ?? null,
			threadPadTop: cs.paddingTop,
			maskFirstOpaqueStopPx: stop ? Number(stop[1] ?? stop[2]) : null,
			maskRaw: mask.slice(0, 120),
			transcriptWidth: document.querySelector(".transcript")?.getBoundingClientRect().width,
		};
	});

	out.focus = await p.evaluate(() => {
		const seen = {};
		for (const sel of [".follow-up", ".text-btn", ".composer__send", ".sources__toggle", ".starter"]) {
			const el = document.querySelector(sel);
			if (!el) continue;
			el.focus();
			const s = getComputedStyle(el);
			seen[sel] = `${s.outlineWidth} ${s.outlineStyle} ${s.outlineColor} / offset ${s.outlineOffset}`;
		}
		return seen;
	});

	out.containers["answer (no widget)"] = await measure(p, ".answer");
	await p.close();
}

/* ── Eligibility widget ────────────────────────────────────────────────── */
{
	const p = await page({ elig: true, height: 1100 });
	await p.type("#aspire-composer", "can I join ASPIRE?");
	await p.keyboard.press("Enter");
	const ok = await p.waitForSelector(".elig", { timeout: 15000 }).then(() => true).catch(() => false);
	if (ok) {
		await settle(500);
		out.containers["elig (.game.elig)"] = await measure(p, ".elig");
		out.pills["elig__option"] = await measure(p, ".elig__option");
		out.pills["game__leave (elig)"] = await measure(p, ".game__leave");
		out.pills["game__btn--quiet (elig back)"] = await measure(p, ".game__btn--quiet");
		out.geometry.eligProgress = await p.evaluate(() => {
			const pip = document.querySelector(".game__step");
			if (!pip) return null;
			const r = pip.getBoundingClientRect();
			return { kind: "numbered steps", h: r.height, w: Math.round(r.width), count: document.querySelectorAll(".game__step").length };
		});
		out.geometry.eligCardWidth = await p.evaluate(
			() => document.querySelector(".elig")?.getBoundingClientRect().width,
		);
	} else {
		out.containers["elig (.game.elig)"] = "UNREACHABLE — backend eligibility endpoint not answering";
	}
	await p.close();
}

await browser.close();
console.log(JSON.stringify(out, null, 2));
