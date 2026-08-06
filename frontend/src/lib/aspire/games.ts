/**
 * The games half of the ASPIRE backend client.
 *
 * The card talks to these directly rather than through `/chat`. A child taps
 * letters into place and presses Check; the verdict has to land now, not after
 * a model round trip — and the model is deliberately not the thing deciding it.
 *
 * The answer is not in any of these types. `Reveal` is the exception, and the
 * server only produces one for a word it has already moved past.
 */

const API_URL = (
	import.meta.env.VITE_ASPIRE_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

/** Every action is a tap away from the next; a slow one reads as broken. */
const TIMEOUT_MS = 10_000;

export type GamePersona = "stella" | "orion" | "aurora" | "nova";

/** How an item is put to the player. */
export type PromptKind = "scramble" | "statement";

/**
 * An item as the player sees it.
 *
 * `kind` says how to render `text` — letters to arrange, or a statement to
 * judge. `choices` is empty when the player composes their own answer.
 */
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

/**
 * A resolved item's answer and its teaching.
 *
 * `explanation` is always the whole thing as flat text. Everything after it is
 * the same words laid out, for content that has been — a line to lead with, the
 * paragraphs it breaks into, a numbered list where one belongs.
 */
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
	/**
	 * Present only when this answer RESOLVED the item — right, or wrong in a
	 * game that moves on. An unresolved wrong answer carries none, which keeps
	 * a scramble's word secret while it is still being guessed at.
	 */
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

/**
 * A refusal the UI is expected to handle.
 *
 * `reason` is the machine-readable half — the server sends a code so the
 * interface can choose its own wording rather than surfacing a sentence written
 * for a developer.
 */
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

/**
 * The running game, or null.
 *
 * Called on mount and after every assistant turn. The browser holds no game
 * state of its own, which is what makes a mid-word refresh a non-event — and
 * it is also how the card learns the assistant just started a game through its
 * own tools, without the chat response needing a field for it.
 */
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
		language?: string;
		/**
		 * The engine's own identifier — `word_scramble`, not `scramble`. The
		 * directive's names are mapped at the call site so the two spellings
		 * meet in exactly one place.
		 */
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
