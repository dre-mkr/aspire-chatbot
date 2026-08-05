/**
 * The v2 SSE client: an ordered buffer keyed by ordinal.
 *
 * ## Why an ordinal buffer rather than "handle events as they arrive"
 *
 * SSE guarantees order over one connection, so arrival order IS ordinal order
 * on the wire. The buffer is not there to fix the network -- it is there to fix
 * the client. React batches state updates, a directive's component may suspend,
 * and a token handler that setStates on every chunk will be coalesced. Once any
 * of that happens, "the order I received them in" is no longer a thing the
 * render can consult; the ordinal is.
 *
 * So every event is recorded with its `i`, and the consumer reads a snapshot
 * that is ordered by `i`. A directive that arrives between token 7 and token 8
 * renders between token 7 and token 8, whatever the scheduler did in between.
 *
 * ## Prose is never blocked on a directive
 *
 * `onDelta` fires the instant a token event is parsed. Nothing waits for a
 * directive to be understood, rendered, or even recognised -- an unknown
 * directive is recorded and passed on, and the prose keeps typing.
 *
 * ## Falling back
 *
 * Only when the stream never opened. A stream that opened and then broke is a
 * failed turn, reported as one: the service records the question before it
 * answers, so retrying would ask the model twice and append a second turn.
 * That rule is inherited from `lib/aspire/stream.ts` and is the same rule.
 */
import type { Directive, TurnUsage, WireEvent } from "./types.ts";

/**
 * Read at call time, not at module scope, and defensively.
 *
 * `import.meta.env` is a Vite construct and is `undefined` under `node --test`,
 * where this module's pure parts (`OrdinalBuffer`, `parseFrame`, `splitFrames`)
 * are exercised. Touching it at module scope would make importing this file
 * throw in the one place its logic is actually tested.
 *
 * The v2 endpoint takes an explicit `Authorization` header from the graph
 * session token, so this module deliberately does NOT pull in
 * `lib/aspire/session` -- one fewer module, and no ambiguity about which of two
 * tokens authorises the call.
 */
function apiUrl(): string {
	const configured =
		typeof import.meta !== "undefined" && import.meta.env
			? import.meta.env.VITE_ASPIRE_API_URL
			: undefined;
	return (configured ?? "http://localhost:8000").replace(/\/$/, "");
}

/**
 * How long a turn may take before the client gives up.
 *
 * 90s, not the 45s this inherited from the v1 streaming transport. A graph turn
 * is strictly more work than the single agent call that number was chosen for:
 * classify, rewrite the query, retrieve on two paths, rerank through a
 * cross-encoder, generate, ground-check, and pass the outbound gate. Measured
 * against the live service on a cold reranker, an ordinary Q&A turn took 21-46s
 * -- so 45s failed real answers that were seconds from arriving, and the reader
 * saw "That took too long" over a turn the server went on to complete and bill.
 *
 * The server's own backstop is 120s (`TURN_TIMEOUT_SECONDS`). This sits inside
 * it deliberately: the client should give up first, so the reader gets a
 * message written for them rather than a closed socket.
 */
const TIMEOUT_MS = 90_000;

export interface StreamCallbacks {
	/** One token of prose. Fires immediately, never buffered behind anything. */
	onToken?: (text: string, ordinal: number) => void;
	/** One directive, with the ordinal that positions it in the prose. */
	onDirective?: (directive: Directive, ordinal: number) => void;
	onDone?: (usage: TurnUsage) => void;
	onError?: (code: string, message: string) => void;
}

export interface StreamInput extends StreamCallbacks {
	message: string;
	token: string;
	signal?: AbortSignal;
	/**
	 * A different v2 endpoint, when the turn is not a typed message.
	 *
	 * `/widget/interaction` is the one that exists: what a child did with a
	 * widget is a TURN, not telemetry -- the agent has to answer it within one
	 * turn, referencing their actual numbers -- so it streams back over exactly
	 * this transport. Defaults to the ordinary chat path.
	 */
	path?: string;
	/** Replaces `{message}` as the request body. Used with `path`. */
	body?: Record<string, unknown>;
}

export interface StreamResult {
	/** Every token concatenated, in ordinal order. */
	text: string;
	directives: Array<{ directive: Directive; ordinal: number }>;
	usage: TurnUsage;
	error: { code: string; message: string } | null;
}

/**
 * A turn's events, held by ordinal and readable as an ordered snapshot.
 *
 * Exported because the transcript component owns one per streaming message --
 * the client fills it, the component reads it, and neither has to know about
 * the other's update timing.
 */
export class OrdinalBuffer {
	private readonly tokens = new Map<number, string>();
	private readonly directives = new Map<number, Directive>();
	private highest = 0;

	token(ordinal: number, text: string): void {
		this.tokens.set(ordinal, text);
		this.highest = Math.max(this.highest, ordinal);
	}

	directive(ordinal: number, directive: Directive): void {
		this.directives.set(ordinal, directive);
		this.highest = Math.max(this.highest, ordinal);
	}

	/** All prose so far, in ordinal order. */
	text(): string {
		const parts: Array<string> = [];
		for (let i = 1; i <= this.highest; i += 1) {
			const part = this.tokens.get(i);
			if (part !== undefined) parts.push(part);
		}
		return parts.join("");
	}

	/**
	 * Each directive with the character offset of the prose that preceded it.
	 *
	 * Converting the ordinal to a character offset happens here, once, because
	 * the parser works in characters and re-deriving this on every render tick
	 * would be O(events) per frame for the life of the turn.
	 */
	placed(): Array<{
		directive: Directive;
		ordinal: number;
		afterChars: number;
	}> {
		const out: Array<{
			directive: Directive;
			ordinal: number;
			afterChars: number;
		}> = [];
		let chars = 0;
		for (let i = 1; i <= this.highest; i += 1) {
			const part = this.tokens.get(i);
			if (part !== undefined) {
				chars += part.length;
				continue;
			}
			const directive = this.directives.get(i);
			if (directive !== undefined) {
				out.push({ directive, ordinal: i, afterChars: chars });
			}
		}
		return out;
	}
}

/**
 * Read one SSE frame out of a raw block.
 *
 * Returns null for anything malformed rather than throwing. A single corrupt
 * frame must not end a turn that is otherwise arriving fine -- and a comment
 * line (`: keep-alive`) is a legitimate frame with no event name at all.
 */
export function parseFrame(block: string): WireEvent | null {
	let name = "";
	let raw = "";
	for (const line of block.split("\n")) {
		if (line.startsWith("event:")) name = line.slice(6).trim();
		else if (line.startsWith("data:")) raw += line.slice(5).replace(/^ /, "");
	}
	if (!name || !raw) return null;
	try {
		return { event: name, data: JSON.parse(raw) } as WireEvent;
	} catch {
		return null;
	}
}

/**
 * Split a growing buffer into complete frames.
 *
 * Returns the frames and whatever is left over, because a chunk boundary falls
 * inside a frame constantly and a parser that assumed otherwise would drop
 * roughly one event in three.
 */
export function splitFrames(buffer: string): {
	frames: Array<string>;
	rest: string;
} {
	const parts = buffer.split("\n\n");
	const rest = parts.pop() ?? "";
	return { frames: parts.filter((part) => part.trim()), rest };
}

/** One turn, streamed. */
export async function streamTurn(input: StreamInput): Promise<StreamResult> {
	const {
		message,
		token,
		signal,
		path = "/v2/chat/stream",
		body,
		onToken,
		onDirective,
		onDone,
		onError,
	} = input;

	const controller = new AbortController();
	const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
	const onExternalAbort = () => controller.abort();
	if (signal) {
		if (signal.aborted) controller.abort();
		else signal.addEventListener("abort", onExternalAbort, { once: true });
	}

	const buffer = new OrdinalBuffer();
	let usage: TurnUsage = {};
	let failure: { code: string; message: string } | null = null;

	try {
		const response = await fetch(`${apiUrl()}${path}`, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Accept: "text/event-stream",
				Authorization: `Bearer ${token}`,
			},
			body: JSON.stringify(body ?? { message }),
			signal: controller.signal,
		});

		if (!response.ok || !response.body) {
			throw new Error(`stream did not open: ${response.status}`);
		}

		const reader = response.body.getReader();
		const decoder = new TextDecoder();
		let pending = "";

		for (;;) {
			const { done, value } = await reader.read();
			if (done) break;
			// `stream: true` matters: a multi-byte character split across two
			// chunks decodes to a replacement character without it, and EC$ and
			// accented copy are both multi-byte.
			pending += decoder.decode(value, { stream: true });

			const { frames, rest } = splitFrames(pending);
			pending = rest;

			for (const block of frames) {
				const event = parseFrame(block);
				if (!event) continue;

				if (event.event === "token") {
					buffer.token(event.data.i, event.data.t);
					// Immediately. Nothing waits for a directive to be understood.
					onToken?.(event.data.t, event.data.i);
				} else if (event.event === "directive") {
					buffer.directive(event.data.i, event.data.d);
					onDirective?.(event.data.d, event.data.i);
				} else if (event.event === "done") {
					usage = event.data.usage ?? {};
					onDone?.(usage);
				} else if (event.event === "error") {
					failure = event.data;
					onError?.(event.data.code, event.data.message);
				}
			}
		}
	} catch (error) {
		const aborted = error instanceof Error && error.name === "AbortError";
		failure = {
			code: aborted ? "timeout" : "transport",
			message: aborted
				? "That took too long. Please try again."
				: "The connection to the assistant was lost. Please try again.",
		};
		onError?.(failure.code, failure.message);
	} finally {
		clearTimeout(timer);
		signal?.removeEventListener("abort", onExternalAbort);
	}

	return {
		text: buffer.text(),
		directives: buffer
			.placed()
			.map(({ directive, ordinal }) => ({ directive, ordinal })),
		usage,
		error: failure,
	};
}
