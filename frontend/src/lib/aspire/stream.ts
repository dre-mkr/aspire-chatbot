/**
 * The chat transport, over server-sent events.
 *
 * `@tanstack/ai-client` is used for exactly one thing: its SSE connection
 * adapter, which opens the request and hands back an async iterable of parsed
 * AG-UI chunks. Its `ChatClient` is deliberately not used — that owns message
 * state, and message state belongs to `use-conversation`. Two things believing
 * they own the transcript is a worse problem than the one the library solves.
 *
 * ## Shape
 *
 * This resolves to the same `AskResult` that `askAspire` returns, so everything
 * downstream — the typewriter, the cards, the sources, the follow-ups — cannot
 * tell which transport produced it. That is the point of this step: the wire
 * changes and nothing else does.
 *
 * `onDelta` exists for the next step, where the typewriter drains text as it
 * arrives. Nothing passes it yet, and while nothing does, the reveal is
 * byte-for-byte the reveal we have always had.
 *
 * ## Falling back
 *
 * Only when the stream never opened: a 404 from an older deployment, a proxy
 * that will not do `text/event-stream`, a network refusal. Then `/chat` answers
 * the turn and the reader sees nothing unusual.
 *
 * A stream that opened and then broke is NOT retried, and that is deliberate.
 * The service records the question before it answers, so retrying would ask the
 * model a second time and append a second copy of the turn. A mid-stream
 * failure is a failed turn, reported exactly as a failed `/chat` is.
 */
import { fetchServerSentEvents } from "@tanstack/ai-client";
import {
	type AskInput,
	type AskResult,
	AspireError,
	askAspire,
	type Source,
	type StartedEligibility,
	type StartedGame,
} from "./api";
import { deviceHeaders } from "./device";

const API_URL = (
	import.meta.env.VITE_ASPIRE_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

/** Matches `askAspire`. A model call is slow; a stalled socket is not an answer. */
const TIMEOUT_MS = 45000;

/** What the service sends once the turn is decided. Mirrors `ChatResponse`. */
interface TurnPayload {
	reply: string;
	thread_id: string;
	sources?: Array<Source>;
	follow_ups?: Array<string>;
	game_started?: {
		game_type?: string;
		display_name?: string;
		kind?: string;
		total?: number;
	} | null;
	eligibility_started?: { check?: string; language?: string } | null;
}

function toResult(payload: TurnPayload, language: string): AskResult {
	const game = payload.game_started;
	const check = payload.eligibility_started;
	return {
		reply: payload.reply,
		threadId: payload.thread_id,
		sources: payload.sources ?? [],
		followUps: payload.follow_ups ?? [],
		startedGame: game
			? ({
					gameType: game.game_type ?? "",
					displayName: game.display_name ?? "",
					kind: game.kind ?? "",
					total: game.total ?? 0,
				} satisfies StartedGame)
			: null,
		startedEligibility: check
			? ({
					check: check.check ?? "aspire_eligibility",
					language: check.language ?? language,
				} satisfies StartedEligibility)
			: null,
	};
}

/** One turn, streamed. Resolves with the whole answer, as `askAspire` does. */
export async function streamAspire(
	input: AskInput & { onDelta?: (delta: string) => void },
): Promise<AskResult> {
	const {
		message,
		threadId,
		simpleMode,
		persona,
		language = "en",
		onDelta,
	} = input;

	const controller = new AbortController();
	const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

	/** Whether anything at all came back, which decides if falling back is safe. */
	let opened = false;
	let payload: TurnPayload | null = null;
	let failure: string | null = null;
	let text = "";

	try {
		const connection = fetchServerSentEvents(`${API_URL}/chat/stream`, {
			headers: { "Content-Type": "application/json", ...deviceHeaders() },
			body: {
				message,
				thread_id: threadId,
				simple_mode: simpleMode,
				persona,
				language,
			},
			signal: controller.signal,
		});

		for await (const chunk of connection.connect([], undefined, controller.signal)) {
			opened = true;
			const event = chunk as { type?: string; delta?: string; name?: string; value?: unknown; message?: string };

			if (event.type === "TEXT_MESSAGE_CONTENT" && event.delta) {
				text += event.delta;
				onDelta?.(event.delta);
				continue;
			}
			if (event.type === "CUSTOM" && event.name === "aspire.turn") {
				payload = event.value as TurnPayload;
				continue;
			}
			if (event.type === "RUN_ERROR") {
				failure = event.message ?? "The assistant is temporarily unavailable.";
				break;
			}
		}
	} catch (error) {
		if (!opened) {
			// Never got off the ground. `/chat` is still there and still correct.
			clearTimeout(timer);
			return askAspire(input);
		}
		throw new AspireError(
			error instanceof Error && error.name === "AbortError"
				? "That took too long. Please try again."
				: "The connection to the assistant was lost. Please try again.",
			true,
		);
	} finally {
		clearTimeout(timer);
	}

	if (failure) throw new AspireError(failure, true);

	if (!payload) {
		// The stream ended without the service saying what the turn was. Falling
		// back would ask the model twice; this is a failed turn.
		if (!opened) return askAspire(input);
		throw new AspireError(
			"The assistant did not finish its reply. Please try again.",
			true,
		);
	}

	// The payload is authoritative, not the accumulated text. On a card turn the
	// service sends an empty reply on purpose, and the deltas — if any escaped —
	// must not override that.
	return toResult(payload, language);
}
