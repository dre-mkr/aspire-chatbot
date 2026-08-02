/**
 * The ASPIRE backend client.
 *
 * The single place that knows the service exists. Everything above it consumes
 * `askAspire()` and never sees a URL, a status code, or a fetch.
 */

/** Where the FastAPI service lives. Override with VITE_ASPIRE_API_URL. */
const API_URL = (
	import.meta.env.VITE_ASPIRE_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

/**
 * The agent retrieves, reasons, and then suggests follow-ups, so a reply is
 * several model calls deep. Generous enough not to cut off a slow-but-working
 * answer, short enough that a hung request eventually surfaces as an error.
 */
const TIMEOUT_MS = 90_000;

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
}

export interface AskInput {
	message: string;
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

interface ChatResponseBody {
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

export async function askAspire({
	message,
	threadId,
	simpleMode,
	persona = null,
	language = "en",
}: AskInput): Promise<AskResult> {
	// AbortSignal.timeout is unavailable in older Safari; a controller is not.
	const controller = new AbortController();
	const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

	let response: Response;
	try {
		response = await fetch(`${API_URL}/chat`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				message,
				thread_id: threadId,
				simple_mode: simpleMode,
				persona,
				language,
			}),
			signal: controller.signal,
		});
	} catch (error) {
		// Fetch rejects for aborts and for the network being unreachable alike,
		// and the two need different advice.
		if (error instanceof DOMException && error.name === "AbortError") {
			throw new AspireError(
				"That took longer than expected. Ask again, and try a shorter question if it keeps happening.",
			);
		}
		throw new AspireError(
			"I could not reach the ASPIRE service. Check that the backend is running, then try again.",
		);
	} finally {
		clearTimeout(timer);
	}

	if (!response.ok) {
		throw new AspireError(
			await describeFailure(response),
			response.status >= 500,
		);
	}

	const body = (await response.json()) as ChatResponseBody;
	const started = body.game_started;
	const check = body.eligibility_started;
	return {
		reply: body.reply,
		threadId: body.thread_id,
		sources: body.sources ?? [],
		followUps: body.follow_ups ?? [],
		startedGame: started
			? {
					gameType: started.game_type ?? "",
					displayName: started.display_name ?? "",
					kind: started.kind ?? "",
					total: started.total ?? 0,
				}
			: null,
		startedEligibility: check
			? {
					check: check.check ?? "aspire_eligibility",
					language: check.language ?? language,
				}
			: null,
	};
}

/** Turns an error response into something worth reading. */
async function describeFailure(response: Response): Promise<string> {
	if (response.status === 422) {
		return "That message could not be sent. It may be empty or too long.";
	}
	if (response.status === 429) {
		return "Too many questions at once. Wait a moment, then ask again.";
	}

	// The backend sends {"detail": "..."} and deliberately keeps it user-safe.
	try {
		const body = (await response.json()) as { detail?: string };
		if (typeof body.detail === "string" && body.detail.trim())
			return body.detail;
	} catch {
		// Not JSON — fall through to the generic message.
	}

	return "Something went wrong on the ASPIRE service. Please try again.";
}

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
