/** The shapes a turn returns, shared by every ASPIRE backend client module. */

import type { Directive } from "../stream/types";

/** One knowledge-base snippet the agent actually used for an answer. */
export interface Source {
	content: string;
	metadata: Record<string, string | number>;
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

