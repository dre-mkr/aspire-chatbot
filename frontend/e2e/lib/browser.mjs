/**
 * The browser, and the one piece of instrumentation the page needs.
 *
 * The app drops `usage` from the `done` event (lib/aspire/stream.ts), so the agent
 * that answered a turn exists on the wire and nowhere else. We tee a clone of every
 * /v2 response into `window.__aspire_turns` and leave the app's own reader untouched.
 */

import puppeteer from "puppeteer";

/** Injected into every document, before any app code runs. */
function installTee() {
	window.__aspire_turns = [];
	window.__aspire_aux = [];

	const original = window.fetch;

	window.fetch = function (input, init) {
		const url = typeof input === "string" ? input : (input && input.url) || "";
		const method = String(
			(init && init.method) || (input && input.method) || "GET",
		).toUpperCase();

		let request = null;
		const raw = init && init.body;
		if (typeof raw === "string") {
			try {
				request = JSON.parse(raw);
			} catch {
				request = raw;
			}
		}

		const isTurn =
			method === "POST" &&
			/\/v2\/(chat\/stream|widget\/interaction|game\/result)(\?|$)/.test(url);
		const isAux =
			method === "POST" &&
			/\/(v2\/session|v2\/documents\/presign|api\/auth\/[a-z-]+)(\?|$)/.test(url);

		const pending = original.apply(this, arguments);

		if (!isTurn && !isAux) return pending;

		return pending.then((response) => {
			if (isAux) {
				const copy = response.clone();
				copy
					.json()
					.then((body) => {
						window.__aspire_aux.push({
							url,
							status: response.status,
							request,
							response: body,
						});
					})
					.catch(() => {});
				return response;
			}

			const record = {
				url,
				request,
				status: response.status,
				frames: [],
				tokens: "",
				directives: [],
				usage: null,
				error: null,
				closed: false,
				startedAt: Date.now(),
			};
			window.__aspire_turns.push(record);

			const copy = response.clone();
			(async () => {
				try {
					const reader = copy.body.getReader();
					const decoder = new TextDecoder();
					let buffer = "";
					for (;;) {
						const { done, value } = await reader.read();
						if (done) break;
						buffer += decoder.decode(value, { stream: true });
						let cut;
						// The v2 wire: `event:` names the kind, `data:` carries the body.
						while ((cut = buffer.indexOf("\n\n")) !== -1) {
							const block = buffer.slice(0, cut);
							buffer = buffer.slice(cut + 2);
							let name = "";
							let payload = "";
							for (const line of block.split("\n")) {
								if (line.startsWith("event:")) name = line.slice(6).trim();
								else if (line.startsWith("data:"))
									payload += line.slice(5).replace(/^ /, "");
							}
							if (!name) continue;
							let data = null;
							try {
								data = JSON.parse(payload);
							} catch {}
							record.frames.push({ event: name, data });
							if (name === "token" && data) record.tokens += data.t || "";
							else if (name === "directive" && data) record.directives.push(data.d);
							else if (name === "done") record.usage = (data && data.usage) || {};
							else if (name === "error") record.error = data;
						}
					}
				} catch (error) {
					record.teeError = String(error);
				} finally {
					record.closed = true;
					record.endedAt = Date.now();
				}
			})();

			return response;
		});
	};
}

export async function launch({ headed = false, slowMo = 0 } = {}) {
	return puppeteer.launch({
		headless: !headed,
		slowMo,
		defaultViewport: { width: 1280, height: 900 },
		args: ["--no-sandbox", "--disable-dev-shm-usage"],
	});
}

/**
 * A context per identity: localStorage (`aspire.session.v1`, `aspire.device.v1`) is
 * per-context, so identities cannot leak into one another.
 */
export async function newIdentityContext(browser) {
	return browser.createBrowserContext();
}

export async function newPage(context, { onConsole, onPageError } = {}) {
	const page = await context.newPage();
	await page.evaluateOnNewDocument(installTee);

	page.on("console", (message) => {
		if (onConsole) onConsole({ type: message.type(), text: message.text() });
	});
	page.on("pageerror", (error) => {
		if (onPageError) onPageError(String(error));
	});

	return page;
}

/** The auxiliary calls the tee recorded — session mints, presigns, auth. */
export async function auxCalls(page, pattern) {
	const calls = await page.evaluate(() => window.__aspire_aux || []);
	return pattern ? calls.filter((call) => call.url.includes(pattern)) : calls;
}
