/**
 * A stand-in for `POST /chat/stream`, and the adversarial corpus it serves.
 *
 * Built for the end state rather than the checkpoint: it emits AG-UI events
 * incrementally, at boundaries chosen to land in the worst possible places, so
 * that the same stubs prove the buffered transport in step 2 and the live-drain
 * parser in step 3. Paying for a stub that only splits on whitespace would mean
 * paying again the moment the parser is the thing under test.
 *
 * ## Why there is a real server in here
 *
 * Puppeteer's `request.respond()` sends a complete body. It cannot deliver one
 * response in pieces, which makes it useless for the only question that matters
 * here: what does the screen do while text is still arriving. So the timing
 * harnesses talk to an actual HTTP server that writes chunks with real gaps
 * between them, and `sseBody` exists for the harnesses that only need the
 * transport not to break.
 *
 * ## The corpus
 *
 * Every entry is a growth sequence whose intermediate states parse differently
 * from their final state. They are the cases that make revealed text move: a
 * line that is a paragraph until a hyphen turns it into a list item, a `#` that
 * is literal text until a space makes it a heading, and so on. If a stub cannot
 * reproduce them, the flash suite cannot prove anything about the parser.
 *
 * Review-only. Never built or shipped.
 */
import { createServer } from "node:http";

/**
 * Growth sequences that change meaning as they arrive.
 *
 * `chunks` are delivered in order; `final` is what the whole thing should be
 * once it has. Each case names the transition it is probing so a failure report
 * says which construct broke rather than which index.
 */
export const ADVERSARIAL = [
	{
		name: "paragraph→list-item",
		why: "`-` is prose until a space and a word make it a bullet",
		chunks: ["Ways to save:\n", "-", " open an account\n", "-", " set a budget\n"],
	},
	{
		name: "paragraph→ordered-item",
		why: "`1.` is prose until a space makes it an ordered item",
		chunks: ["Steps:\n", "1.", " open an account\n", "2.", " set a budget\n"],
	},
	{
		name: "hash→heading",
		why: "`#` is literal text; `# ` strips to a heading and the text changes",
		chunks: ["#", " Saving money\n", "It adds up.\n"],
	},
	{
		name: "blockquote-marker",
		why: "`>` alone, then a quote",
		chunks: [">", " a quote arrives late\n"],
	},
	{
		name: "paragraph→table",
		why: "a pipe row is prose until the delimiter row arrives beneath it",
		chunks: ["|Fund|Fee|\n", "|---|---|\n", "|Index|0.1%|\n"],
	},
	{
		name: "paragraph→setext-heading",
		why: "`===` on the next line retroactively re-reads the line above it",
		chunks: ["Compound interest\n", "===", "==\n"],
	},
	{
		name: "dashes-after-paragraph",
		why: "`---` under prose is a setext h2; under a blank line it is a rule",
		chunks: ["Some prose\n", "---\n"],
	},
	{
		name: "dashes-after-blank",
		// Split mid-token deliberately. In a full CommonMark renderer this is a
		// thematic rule where the previous case is a setext heading; in this
		// product's subset neither is special, so the only hazard left is the
		// text growing `--` → `---`. Kept, and split, so it still probes
		// something — a case that reaches no ambiguous state is not coverage.
		why: "the same three characters, one blank line earlier, arriving split",
		chunks: ["Some prose\n", "\n", "--", "-\n"],
	},
	{
		name: "unterminated-code-fence",
		why: "an open fence stays open across many chunks and closes at the end",
		chunks: [
			"```js\n",
			"const rate = 0.05;\n",
			"const years = 10;\n",
			"const total = 100 * (1 + rate) ** years;\n",
			"```\n",
			"That is compounding.\n",
		],
	},
	{
		name: "late-nested-indent",
		why: "the indentation that makes an item nested arrives a chunk after the dash",
		chunks: ["- outer item\n", " ", " - inner item\n", "- another outer\n"],
	},
	{
		name: "emphasis-split",
		why: "`*fo` then `o*` — a bold run split across a chunk boundary",
		chunks: ["Rates can be *fo", "o*lish to chase.\n"],
	},
	{
		name: "bullet-char-mid-word",
		why: "a hyphen inside a word must never be read as a bullet",
		chunks: ["Long", "-term saving beats short", "-term guessing.\n"],
	},
];

/** The corpus as one reply, so a single run exercises every transition. */
export const ADVERSARIAL_CHUNKS = ADVERSARIAL.flatMap((c) => [...c.chunks, "\n"]);

/**
 * Splits text at deliberately awkward places.
 *
 *   "words"    — whole words, the friendly case
 *   "chars"    — fixed width, which lands mid-word and mid-construct
 *   "cruel"    — one character after every markdown-significant character, so
 *                every construct is observed in its ambiguous half-state
 */
export function chunkText(text, strategy = "words", size = 7) {
	if (strategy === "chars") {
		const out = [];
		for (let i = 0; i < text.length; i += size) out.push(text.slice(i, i + size));
		return out;
	}
	if (strategy === "cruel") {
		const out = [];
		let buf = "";
		for (const ch of text) {
			buf += ch;
			// Break immediately after anything that could begin a block, so the
			// consumer necessarily sees the ambiguous state.
			if ("-*#>|=`.\n".includes(ch)) {
				out.push(buf);
				buf = "";
			}
		}
		if (buf) out.push(buf);
		return out;
	}
	return text.split(/(?<=\s)/).reduce((acc, word) => {
		const last = acc[acc.length - 1];
		if (last && last.split(/\s+/).filter(Boolean).length < size) {
			acc[acc.length - 1] = last + word;
		} else acc.push(word);
		return acc;
	}, []);
}

const frame = (event) => `data: ${JSON.stringify(event)}\n\n`;

/** The AG-UI events for one turn, in order. */
export function sseEvents(chunks, done, { messageId = "m1", runId = "r1", threadId = "t" } = {}) {
	const events = [{ type: "RUN_STARTED", threadId, runId }];
	const text = chunks.filter(Boolean);
	if (text.length && !done.game_started && !done.eligibility_started) {
		events.push({ type: "TEXT_MESSAGE_START", messageId, role: "assistant" });
		for (const delta of text) {
			events.push({ type: "TEXT_MESSAGE_CONTENT", messageId, delta });
		}
		events.push({ type: "TEXT_MESSAGE_END", messageId });
	}
	// The turn, then the chips, in that order and as two events -- which is what
	// the service does, because the chips cost a second model call and the rest
	// of the turn has been known since the last token.
	events.push({
		type: "CUSTOM",
		name: "aspire.turn",
		value: { ...done, follow_ups: [] },
	});
	events.push({
		type: "CUSTOM",
		name: "aspire.follow_ups",
		value: { follow_ups: done.follow_ups ?? [] },
	});
	events.push({ type: "RUN_FINISHED", threadId, runId });
	return events;
}

/** The whole turn as one body — for harnesses that only need it not to break. */
export function sseBody(chunks, done, options) {
	return sseEvents(chunks, done, options).map(frame).join("");
}

/**
 * Answers `/chat/stream` from an intercepted request, or returns false.
 *
 * One line per harness. The body arrives whole rather than in pieces — see the
 * note at the top about `respond()` — which is enough for every harness whose
 * subject is not the reveal itself. The ones that ARE about the reveal use
 * `startSseServer`.
 *
 * `reply` is taken from whatever the harness already had configured for
 * `/chat`, so the two endpoints cannot drift apart and a harness does not have
 * to describe its fixture twice.
 */
export function handleChatStream(request, respond, config = {}) {
	if (!request.url().endsWith("/chat/stream")) return false;

	const raw = JSON.parse(request.postData() || "{}");
	// AG-UI clients wrap the application's own fields in `forwardedProps` and
	// keep the top level for their correlation ids. Flattened here so a harness
	// reads `sent.message` whichever transport produced the request.
	const sent = { ...raw, ...(raw.forwardedProps ?? {}) };
	const {
		reply = "",
		sources = [],
		followUps = [],
		gameStarted = null,
		eligibilityStarted = null,
		chunks,
		strategy = "cruel",
	} = typeof config === "function" ? config(sent) : config;

	const threadId = sent.thread_id || "t-server";
	const pieces = chunks ?? (reply ? chunkText(reply, strategy) : []);

	respond(
		sseBody(pieces, {
			reply,
			thread_id: threadId,
			sources,
			follow_ups: followUps,
			game_started: gameStarted,
			eligibility_started: eligibilityStarted,
		}),
		sent,
	);
	return true;
}

/**
 * A real server that writes chunks with real gaps between them.
 *
 * `config` is mutable so a harness can change what the next request returns
 * without restarting anything: the scenarios run in sequence on one page, and
 * standing a server up per case would dominate the runtime.
 */
export function startSseServer({ port = 8000 } = {}) {
	const state = {
		chunks: ["Hello.\n"],
		/** Milliseconds between chunks. Real gaps, or the test proves nothing. */
		gap: 25,
		/**
		 * Milliseconds between the turn's payload and its follow-up chips.
		 *
		 * The real service takes two to five seconds here: the chips are a second
		 * model call, and the transcript is persisted alongside it. A stub that
		 * sends `aspire.turn` and `aspire.follow_ups` back to back cannot tell
		 * whether a client settles on the first or waits for the second — which
		 * is exactly the distinction that made a finished answer sit on screen
		 * with no sources and no action row.
		 */
		tailGap: 0,
		done: {
			reply: "Hello.",
			thread_id: "t",
			sources: [],
			follow_ups: [],
			game_started: null,
			eligibility_started: null,
		},
		/** Cut the connection after N chunks, to exercise a mid-stream failure. */
		dropAfter: null,
		status: 200,
		seen: [],
	};

	const cors = {
		"Access-Control-Allow-Origin": "*",
		"Access-Control-Allow-Methods": "GET,POST,PATCH,OPTIONS",
		"Access-Control-Allow-Headers": "Content-Type, Authorization, X-Aspire-Device",
	};

	const server = createServer(async (req, res) => {
		if (req.method === "OPTIONS") {
			res.writeHead(204, cors);
			res.end();
			return;
		}

		if (!req.url.startsWith("/chat/stream")) {
			res.writeHead(404, { ...cors, "content-type": "application/json" });
			res.end("{}");
			return;
		}

		const body = await new Promise((resolve) => {
			let raw = "";
			req.on("data", (d) => {
				raw += d;
			});
			req.on("end", () => resolve(raw));
		});
		state.seen.push({ body: JSON.parse(body || "{}"), headers: req.headers });

		if (state.status !== 200) {
			res.writeHead(state.status, { ...cors, "content-type": "application/json" });
			res.end(JSON.stringify({ detail: "The assistant is temporarily unavailable." }));
			return;
		}

		res.writeHead(200, {
			...cors,
			"content-type": "text/event-stream",
			"cache-control": "no-cache",
			connection: "keep-alive",
			"x-accel-buffering": "no",
		});

		const events = sseEvents(state.chunks, state.done);
		let written = 0;
		for (const event of events) {
			res.write(frame(event));
			written += 1;
			if (state.dropAfter != null && written >= state.dropAfter) {
				// Half a turn, then the socket goes away — what a dropped
				// connection actually looks like to the client.
				res.destroy();
				return;
			}
			if (event.type === "TEXT_MESSAGE_CONTENT" && state.gap) {
				await new Promise((r) => setTimeout(r, state.gap));
			}
			if (event.name === "aspire.turn" && state.tailGap) {
				await new Promise((r) => setTimeout(r, state.tailGap));
			}
		}
		res.end();
	});

	return new Promise((resolve) => {
		server.listen(port, () => resolve({ server, state, port }));
	});
}

/**
 * Answers `/chat/stream` for a harness that only ever stubbed `/chat`.
 *
 * Seven suites were written before the transport moved to server-sent events
 * and were never updated. They passed anyway, which is the part worth
 * understanding: with nothing listening on the API port, the stream request was
 * refused, the client fell back to `/chat`, and the stub answered that. So they
 * were all quietly asserting against the fallback, and the moment a real
 * service was running on :8000 — which is the normal state for anyone actually
 * developing — they failed in ways that read as product regressions.
 *
 * `onSent` receives the request body already flattened (AG-UI puts the
 * application's own fields in `forwardedProps`), so a harness records exactly
 * what it recorded before, and returns the config for the reply — usually
 * `{ reply }`, the same text its `/chat` branch returns.
 *
 * Returns true when it handled the request, so the call site reads:
 *
 *     if (serveStream(r, CORS, (sent) => { seen.chat.push(sent); return { reply: A.reply }; })) return;
 */
export function serveStream(request, cors, onSent) {
	if (!request.url().endsWith("/chat/stream")) return false;
	const raw = JSON.parse(request.postData() || "{}");
	const sent = { ...raw, ...(raw.forwardedProps ?? {}) };
	const config = onSent?.(sent) ?? {};
	handleChatStream(
		request,
		(body) => request.respond({ status: 200, contentType: "text/event-stream", headers: cors, body }),
		config,
	);
	return true;
}
