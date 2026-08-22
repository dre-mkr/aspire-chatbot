/** The games half of the ASPIRE backend client. */
import { API_URL } from "../config";

/** Every action is a tap away from the next; a slow one reads as broken. */
const TIMEOUT_MS = 10_000;

// Mirrors `PersonaId`. The engine refuses aurora and nova, which is why the
// caller must send the real value rather than null: the refusal is the point.
export type GamePersona =
	| "stella"
	| "kaleb"
	| "orion"
	| "aurora"
	| "nova"
	| "guest";

/** How an item is put to the player. */
export type PromptKind = "scramble" | "statement" | "quiz" | "hangman";

/** An item as the player sees it. */
export interface GamePrompt {
	kind: PromptKind;
	text: string;
	position: number;
	total: number;
	choices: Array<string>;
}

/** A running game, exactly as the server describes it. Never holds the answer. */
export interface GameState {
	game_type: string;
	display_name: string;
	prompt: GamePrompt;
	supports_hints: boolean;
	hint_level: number;
	max_hint_level: number;
	hints: Array<string>;
	attempts: number;
	solved: number;
	skipped: number;
	language: string;
	persona: GamePersona | null;
}

/** What a set says once every item is done. */
export interface Closing {
	lead: string;
	text: string;
}

export interface GameSummary {
	solved: number;
	/** Answered wrong, in a game where that resolves the item. */
	missed: number;
	skipped: number;
	total: number;
	hints_used: number;
	duration_seconds: number;
	closing: Closing | null;
}

/** One row of a numbered breakdown inside an explanation. */
export interface Bullet {
	marker: string;
	label: string;
	text: string;
}

/** A resolved item's answer and its teaching. */
export interface Reveal {
	answer: string;
	explanation: string;
	takeaway: string | null;
	paragraphs: Array<string>;
	bullets: Array<Bullet>;
	after: string | null;
	topic: string | null;
	topic_line: string | null;
}

export interface SubmitResult {
	correct: boolean;
	attempts: number;
	teaching_note: string | null;
	/** Present only when this answer RESOLVED the item — right, or wrong in a game that moves on. */
	reveal: Reveal | null;
	/** The answer could not be read at all. Not wrong: nothing was spent. */
	unreadable: string | null;
	finished: boolean;
	game: GameState | null;
	summary: GameSummary | null;
}

export interface HintResult {
	revealed: boolean;
	hint: string | null;
	level: number;
	reveal: Reveal | null;
	finished: boolean;
	game: GameState | null;
	summary: GameSummary | null;
}

export interface SkipResult {
	reveal: Reveal;
	finished: boolean;
	game: GameState | null;
	summary: GameSummary | null;
}

/** A refusal the UI is expected to handle. */
export class GameError extends Error {
	readonly reason: string;
	readonly status: number;

	constructor(reason: string, message: string, status: number) {
		super(message);
		this.name = "GameError";
		this.reason = reason;
		this.status = status;
	}
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
	let response: Response;
	try {
		response = await fetch(`${API_URL}${path}`, {
			...init,
			headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
			signal: AbortSignal.timeout(TIMEOUT_MS),
		});
	} catch {
		throw new GameError("offline", "The game could not be reached.", 0);
	}

	if (!response.ok) {
		// FastAPI puts our {reason, message} under `detail`.
		let reason = "game_error";
		let message = "Something went wrong with the game.";
		try {
			const body = (await response.json()) as {
				detail?: { reason?: string; message?: string } | string;
			};
			if (body.detail && typeof body.detail === "object") {
				reason = body.detail.reason ?? reason;
				message = body.detail.message ?? message;
			}
		} catch {
			// Not JSON. The generic message stands.
		}
		throw new GameError(reason, message, response.status);
	}

	return (await response.json()) as T;
}

/** The running game, or null. */
export async function fetchGameState(
	threadId: string,
): Promise<GameState | null> {
	const body = await call<{ active: boolean; game: GameState | null }>(
		`/api/games/state?thread_id=${encodeURIComponent(threadId)}`,
	);
	return body.game;
}

export async function startGame(
	threadId: string,
	options: {
		persona?: GamePersona | null;
		/**
		 * Which age band to draw items for.
		 *
		 * Separate from the persona because one persona can span two ages:
		 * `orion` serves 13-15 and 16-18 from a single bank, and an item pitched
		 * at a sixteen-year-old had no way to say so. Omitted means every item
		 * the persona may see, which is how this behaved before the dimension
		 * existed.
		 */
		age_band?: string | null;
		language?: string;
		/** The engine's own identifier — `word_scramble`, not `scramble`. */
		game_type?: string;
	} = {},
): Promise<GameState | null> {
	const body = await call<{ active: boolean; game: GameState | null }>(
		"/api/games/start",
		{
			method: "POST",
			body: JSON.stringify({
				thread_id: threadId,
				persona: options.persona ?? null,
				...(options.age_band ? { age_band: options.age_band } : {}),
				language: options.language ?? "en",
				...(options.game_type ? { game_type: options.game_type } : {}),
			}),
		},
	);
	return body.game;
}

export function submitAnswer(threadId: string, answer: string) {
	return call<SubmitResult>("/api/games/submit", {
		method: "POST",
		body: JSON.stringify({ thread_id: threadId, answer }),
	});
}

export function requestHint(threadId: string) {
	return call<HintResult>("/api/games/hint", {
		method: "POST",
		body: JSON.stringify({ thread_id: threadId }),
	});
}

export function skipWord(threadId: string) {
	return call<SkipResult>("/api/games/skip", {
		method: "POST",
		body: JSON.stringify({ thread_id: threadId }),
	});
}

export function quitGame(threadId: string) {
	return call<GameSummary>("/api/games/quit", {
		method: "POST",
		body: JSON.stringify({ thread_id: threadId }),
	});
}
