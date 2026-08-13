/** The v2 SSE client: an ordered buffer keyed by ordinal. */
import type { Directive, TurnUsage, WireEvent } from "./types.ts";

/** Read at call time, not at module scope, and defensively. */
function apiUrl(): string {
	const configured =
		typeof import.meta !== "undefined" && import.meta.env
			? import.meta.env.VITE_ASPIRE_API_URL
			: undefined;
	return (configured ?? "http://localhost:8000").replace(/\/$/, "");
}

/** How long a turn may take before the client gives up. */
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
	/** A different v2 endpoint, when the turn is not a typed message. */
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

/** A turn's events, held by ordinal and readable as an ordered snapshot. */
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

	/** Each directive with the character offset of the prose that preceded it. */
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

/** Read one SSE frame out of a raw block. */
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

/** Split a growing buffer into complete frames. */
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

	/** One place the result shape is written, so early returns cannot drift. */
	const result = () => ({
		text: buffer.text(),
		directives: buffer
			.placed()
			.map(({ directive, ordinal }) => ({ directive, ordinal })),
		usage,
		error: failure,
	});

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
			// A refusal before the stream opens arrives as a status with the same shape.
			const refusal = await response
				.json()
				.then((body: unknown) =>
					body &&
					typeof body === "object" &&
					typeof (body as { code?: unknown }).code === "string" &&
					typeof (body as { message?: unknown }).message === "string"
						? (body as { code: string; message: string })
						: null,
				)
				.catch(() => null);

			if (refusal) {
				failure = refusal;
				onError?.(refusal.code, refusal.message);
				return result();
			}
			throw new Error(`stream did not open: ${response.status}`);
		}

		const reader = response.body.getReader();
		const decoder = new TextDecoder();
		let pending = "";

		for (;;) {
			const { done, value } = await reader.read();
			if (done) break;
			// `stream: true` matters: multi-byte chars split across chunks decode wrong.
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

	return result();
}
