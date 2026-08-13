/**
 * Sending a turn, and knowing when it is over.
 *
 * Three layers, because each fails differently and a timeout should say which:
 *   1. the tee saw EOF on the stream            — exact, typewriter-independent
 *   2. `.composer__send--stop` is gone          — the app's own `settled`
 *   3. one more settled assistant turn in DOM   — not one React commit early
 *
 * Directives are only read after all three: they do not enter the DOM until the
 * typewriter finishes (Transcript.tsx), and quick replies are `inert` until then.
 */

const SETTLE_TIMEOUT = 120_000;

export async function snapshot(page) {
	return page.evaluate(() => ({
		turns: (window.__aspire_turns || []).length,
		settled: document.querySelectorAll(
			'.turn--assistant:not([aria-busy="true"])',
		).length,
	}));
}

/** Wait for the turn started after `before` to finish, whatever started it. */
export async function settle(page, before, { timeout = SETTLE_TIMEOUT } = {}) {
	try {
		await page.waitForFunction(
			(index, settled) => {
				const record = (window.__aspire_turns || [])[index];
				if (!record || !record.closed) return false;
				if (document.querySelector(".composer__send--stop")) return false;
				return (
					document.querySelectorAll('.turn--assistant:not([aria-busy="true"])')
						.length > settled
				);
			},
			{ timeout, polling: 100 },
			before.turns,
			before.settled,
		);
	} catch (error) {
		const stage = await page.evaluate(
			(index, settled) => {
				const record = (window.__aspire_turns || [])[index];
				if (!record) return "network:no-request";
				if (!record.closed) return "network:stream-open";
				if (document.querySelector(".composer__send--stop")) return "app:busy";
				return "dom:not-committed";
			},
			before.turns,
			before.settled,
		);
		throw new Error(`settle_timeout:${stage}`);
	}

	return page.evaluate(
		(index) => (window.__aspire_turns || [])[index] || null,
		before.turns,
	);
}

/**
 * Type a message and wait for the answer.
 * A leading space in an empty composer starts voice recording, so refuse one.
 */
export async function say(page, text, options = {}) {
	if (!text || text !== text.trimStart()) {
		throw new Error(`refusing to send ${JSON.stringify(text)}`);
	}

	const before = await snapshot(page);
	await page.waitForSelector("#aspire-composer", { visible: true });

	// The page is server-rendered: text typed before React attaches is dropped, and
	// Enter on an unhydrated composer does nothing. Retry until the request appears.
	let sent = false;
	for (let attempt = 0; attempt < 4 && !sent; attempt++) {
		await page.click("#aspire-composer");
		await page.type("#aspire-composer", text, { delay: 1 });
		if (!(await page.$eval("#aspire-composer", (node) => node.value.trim().length))) {
			await new Promise((resolve) => setTimeout(resolve, 300));
			continue;
		}
		await page.keyboard.press("Enter");
		try {
			await page.waitForFunction(
				(index) => (window.__aspire_turns || []).length > index,
				{ timeout: 5000, polling: 100 },
				before.turns,
			);
			sent = true;
		} catch {
			await page.evaluate(() => {
				const box = document.querySelector("#aspire-composer");
				if (box) box.value = "";
			});
		}
	}
	if (!sent) throw new Error("composer never sent the message");

	return settle(page, before, options);
}

/** Click something that itself starts a turn — a chip, a widget, a game answer. */
export async function act(page, action, options = {}) {
	const before = await snapshot(page);
	await action(page);
	return settle(page, before, options);
}

/** Click something that does NOT start a graph turn — an eligibility option. */
export async function actDom(page, action, predicate, { timeout = 30_000 } = {}) {
	await action(page);
	await page.waitForFunction(predicate, { timeout, polling: 100 });
}

/** Everything on screen, after the turn settled. */
export async function readTranscript(page) {
	return page.evaluate(() => {
		const clean = (node) => (node?.innerText || "").trim();
		const turns = [...document.querySelectorAll(".turn--user, .turn--assistant")];
		return turns.map((turn) => ({
			role: turn.classList.contains("turn--user") ? "user" : "assistant",
			text: clean(turn.querySelector(".answer") || turn),
			failure: clean(turn.querySelector(".failure")) || null,
		}));
	});
}

/** What the last answer rendered — used to prove a directive reached the reader. */
export async function readSurfaces(page) {
	return page.evaluate(() => {
		const text = (selector) => {
			const node = document.querySelector(selector);
			return node ? (node.innerText || "").trim() : null;
		};
		return {
			chips: [...document.querySelectorAll(".follow-ups button.follow-up")].map(
				(button) => (button.innerText || "").trim(),
			),
			chipsInert: !!document.querySelector(".follow-ups[data-pending]"),
			widget: !!document.querySelector("figure.w-panel"),
			game: !!document.querySelector("section.game.tf, section.game:not(.elig)"),
			eligibility: !!document.querySelector("section.game.elig"),
			upload: !!document.querySelector('input[type="file"]'),
			review: !!document.querySelector(".review-card, dl"),
			sources: text("details.sources summary"),
			signupLink: !!document.querySelector('a[href^="/signup"]'),
			lastAnswer: (() => {
				const all = [...document.querySelectorAll(".turn--assistant")];
				const last = all[all.length - 1];
				return last ? (last.innerText || "").trim() : "";
			})(),
		};
	});
}

/** The kinds of directive that crossed the wire on this turn — authoritative. */
export function directiveKinds(record) {
	// The wire tags a directive with `t` (see backend/app/schemas/directives.py).
	return (record?.directives || []).map((d) => d?.t || d?.type || "unknown");
}
