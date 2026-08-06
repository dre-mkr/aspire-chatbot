/**
 * The ASPIRE backend client.
 *
 * The shapes a turn resolves to, and the liveness probe.
 *
 * This used to be the whole client -- `askAspire()` lived here and everything
 * above it consumed that. The transport moved to `./stream.ts` when `/chat`
 * went; what stays is the contract, because that is what the components are
 * written against and it did not change when the wire underneath it did.
 */

import type { Directive } from "../stream/types";

/** Where the FastAPI service lives. Override with VITE_ASPIRE_API_URL. */
const API_URL = (
	import.meta.env.VITE_ASPIRE_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

/** One knowledge-base snippet the agent actually used for an answer. */
export interface Source {
	content: string;
	metadata: Record<string, string | number>;
}

/**
 * The game a turn started, when it started one.
 *
 * Its presence is what makes a turn a game turn, and a game turn has no prose:
 * the service sends `reply: ""` because the card the client renders IS the
 * answer. Anything the model said alongside it would put the same puzzle on
 * screen twice.
 */
export interface StartedGame {
	gameType: string;
	displayName: string;
	kind: string;
	total: number;
}

/**
 * The eligibility check a turn opened, when it opened one.
 *
 * Deliberately almost empty. The card fetches its own question from the
 * eligibility endpoint, so nothing about the flow rides on the chat response —
 * and because nothing does, there is no field here that a person's answers
 * could travel in. `language` is the one thing the client cannot re-derive: a
 * running flow answers in the language it was started in.
 */
export interface StartedEligibility {
	check: string;
	language: string;
}

export interface AskResult {
	reply: string;
	threadId: string;
	sources: Array<Source>;
	followUps: Array<string>;
	/** Null on every ordinary turn. */
	startedGame: StartedGame | null;
	/** Null on every ordinary turn. */
	startedEligibility: StartedEligibility | null;
	/**
	 * Everything the turn asked the client to render, in ordinal order.
	 *
	 * Widgets, upload cards, review cards, progress, escalation. Sources and
	 * chips are NOT here — they arrive as directives on the wire and are mapped
	 * onto `sources` and `followUps` above, because the transcript has drawn
	 * those in its own places since long before this channel existed.
	 *
	 * Nor are `game` and `eligibility`: those are mapped onto `startedGame` and
	 * `startedEligibility`, and removed from here so that exactly one thing can
	 * mount a card.
	 */
	directives: Array<Directive>;
}

export interface AskInput {
	message: string;
	/**
	 * Cancels the turn, and with it the model call behind it.
	 *
	 * Optional because the transport applies its own timeout regardless -- this
	 * composes with that rather than replacing it. Passing one is what lets Stop,
	 * navigation and unmount actually stop the work: without it the request ran
	 * to completion and was billed in full no matter what the reader did, because
	 * nothing outside the transport could reach the controller.
	 */
	signal?: AbortSignal;
	/** Null starts a new conversation; pass the returned id to continue one. */
	threadId: string | null;
	simpleMode: boolean;
	/**
	 * Who is talking: "stella", "orion", "aurora" or "nova".
	 *
	 * Null means "we do not know", which the backend treats as permissive rather
	 * than as any particular persona — an unknown caller can still play the
	 * games, where an explicit parent account cannot.
	 */
	persona?: string | null;
	/**
	 * Which language the conversation is being held in.
	 *
	 * Already part of the response cache key server-side. It matters here
	 * because the eligibility card opens in whatever this says: a French
	 * speaker asking "puis-je m'inscrire ?" must not get an English flow.
	 */
	language?: string;
}

/**
 * A failure worth showing a person.
 *
 * `message` is written to be rendered as-is: it names what went wrong and what
 * to do about it, never a status code or a stack.
 */
export class AspireError extends Error {
	readonly canRetry: boolean;

	constructor(message: string, canRetry = true) {
		super(message);
		this.name = "AspireError";
		this.canRetry = canRetry;
	}
}

/*
 * `askAspire` stood here, with its response-body validator and its failure
 * describer: a non-streaming `POST /chat` that returned the whole turn as one
 * JSON object, and the fallback `streamAspire` reached for when a stream would
 * not open.
 *
 * Both are gone with the endpoint. There is nothing to fall back TO -- a second
 * path that answered the same question differently is how a streaming transport
 * quietly becomes a second product, and the graph is now the only thing that
 * answers. `lib/aspire/stream.ts` is the transport; `AskResult` above is still
 * its shape, which is why nothing above this layer had to change.
 */

/** Liveness probe, used to explain a dead backend before the first question. */
export async function checkHealth(): Promise<boolean> {
	try {
		const response = await fetch(`${API_URL}/health`, {
			signal: AbortSignal.timeout(4000),
		});
		return response.ok;
	} catch {
		return false;
	}
}
