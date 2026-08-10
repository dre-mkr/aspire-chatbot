/** The ASPIRE backend client. */

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

/* `askAspire` stood here, with its response-body validator and its failure describer: a non-streaming `POST /ch… */

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
