/** The shapes a turn returns, shared by every ASPIRE backend client module. */

import type { Directive } from "../stream/types";

/**
 * Where a cited row came from, when the knowledge base knew.
 *
 * Every field is the server's, validated there; nothing here is derived from an
 * answer's text. `url` is empty whenever there is nothing to open — programme
 * material with no public page, a row whose stored URL would not validate, or a
 * reader whose persona is not shown links — and `site`/`page` still name the
 * source in all three cases.
 */
export interface SourceOrigin {
	url: string;
	site: string;
	page: string;
	domain: string;
	updated: string;
}

/** One knowledge-base snippet the agent actually used for an answer. */
export interface Source {
	content: string;
	metadata: Record<string, string | number>;
	/** Absent on a row the corpus could not attribute at all. */
	origin?: SourceOrigin;
}

/** The game a turn started, when it started one. */
export interface StartedGame {
	gameType: string;
	displayName: string;
	kind: string;
	total: number;
	/** The concept the game teaches; carried so the result can record mastery. */
	concept: string;
}

/** The eligibility check a turn opened, when it opened one. */
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
	/** Everything the turn asked the client to render, in ordinal order. */
	directives: Array<Directive>;
}

export interface AskInput {
	message: string;
	/** Cancels the turn, and with it the model call behind it. */
	signal?: AbortSignal;
	/** Null starts a new conversation; pass the returned id to continue one. */
	threadId: string | null;
	simpleMode: boolean;
	/** Who is talking: "stella", "orion", "aurora" or "nova". */
	persona?: string | null;
	/**
	 * Which of the persona's own bands to answer at.
	 *
	 * Skye and Kaleb are both `stella` and are told apart by this alone, so
	 * without it the picker offers a name the server cannot deliver. Honoured
	 * only inside the persona's own cards -- a band `stella` has no card for
	 * falls back rather than reaching another persona's material.
	 */
	band?: string | null;
	/** Which language the conversation is being held in. */
	language?: string;
}

/** A failure worth showing a person. */
export class AspireError extends Error {
	readonly canRetry: boolean;

	constructor(message: string, canRetry = true) {
		super(message);
		this.name = "AspireError";
		this.canRetry = canRetry;
	}
}

