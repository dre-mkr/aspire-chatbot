/** Conversations, read back from the service. */

import type { Source } from "./api";
import type { StoredConversation, StoredMessage } from "./history";
import { parseAnswer } from "./knowledge";
import { authHeaders } from "./session";

const API_URL = (
	import.meta.env.VITE_ASPIRE_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

/** Long enough for a cold Neon instance, short enough not to hang the rail. */
const TIMEOUT_MS = 12000;

interface WireMessage {
	role: string;
	text?: string;
	sources?: Array<Source>;
	follow_ups?: Array<string>;
	game_type?: string | null;
}

interface WireConversation {
	thread_id: string;
	title?: string | null;
	title_source?: "generated" | "manual" | null;
	updated_at: number;
	/** Detail only — the rail's list does not carry these. */
	language?: string | null;
	persona?: string | null;
	messages?: Array<WireMessage>;
}

/** A failed request that still knows what the server said. */
export class HttpError extends Error {
	readonly status: number;

	constructor(path: string, status: number) {
		super(`${path} failed: ${status}`);
		this.name = "HttpError";
		this.status = status;
	}
}

async function call<T>(
	path: string,
	init?: RequestInit,
	/** Checked before the value is handed back, where a shape matters. */
	guard?: (value: unknown) => value is T,
): Promise<T> {
	const response = await fetch(`${API_URL}${path}`, {
		...init,
		headers: {
			"Content-Type": "application/json",
			...authHeaders(),
			...(init?.headers ?? {}),
		},
		signal: AbortSignal.timeout(TIMEOUT_MS),
	});
	if (!response.ok) throw new HttpError(path, response.status);
	if (response.status === 204) return undefined as T;

	const body: unknown = await response.json();
	if (guard && !guard(body)) {
		throw new Error(`${path} returned a shape this client cannot read`);
	}
	return body as T;
}

/** Shallow: `toStored` already tolerates every optional field being absent. */
function isWireConversation(value: unknown): value is WireConversation {
	if (typeof value !== "object" || value === null) return false;
	const row = value as Record<string, unknown>;
	return (
		typeof row.thread_id === "string" &&
		typeof row.updated_at === "number" &&
		(row.messages === undefined || Array.isArray(row.messages))
	);
}

function isConversationList(
	value: unknown,
): value is { conversations: Array<WireConversation> } {
	if (typeof value !== "object" || value === null) return false;
	const body = (value as Record<string, unknown>).conversations;
	// Absent is legitimate and means "none"; present and wrong is not.
	return (
		body === undefined ||
		(Array.isArray(body) && body.every(isWireConversation))
	);
}

/** The prose a turn is rendered from. */
/** Give a stored citation the shape the renderer expects. */
function normaliseSource(source: Source | Record<string, unknown>): Source {
	if (
		source &&
		typeof source === "object" &&
		"metadata" in source &&
		source.metadata
	)
		return source as Source;
	const { content, ...rest } = (source ?? {}) as Record<string, unknown>;
	return {
		content: typeof content === "string" ? content : "",
		metadata: rest as Record<string, string | number>,
	};
}

function toStoredMessage(message: WireMessage): StoredMessage | null {
	if (message.role === "user")
		return { role: "user", text: message.text ?? "" };
	if (message.role === "game")
		return { role: "game", gameType: message.game_type ?? "" };
	if (message.role === "eligibility") return { role: "eligibility" };
	if (message.role === "assistant") {
		return {
			role: "assistant",
			blocks: parseAnswer(message.text ?? ""),
			sources: (message.sources ?? []).map(normaliseSource),
			followUps: message.follow_ups ?? [],
		};
	}
	return null;
}

const LANGUAGES = ["en", "es", "fr"] as const;

function toStored(wire: WireConversation): StoredConversation {
	const language = (LANGUAGES as ReadonlyArray<string>).includes(
		wire.language ?? "",
	)
		? (wire.language as "en" | "es" | "fr")
		: undefined;

	return {
		threadId: wire.thread_id,
		title: wire.title ?? "",
		...(wire.title_source ? { titleSource: wire.title_source } : {}),
		...(language ? { language } : {}),
		...(wire.persona ? { persona: wire.persona } : {}),
		updatedAt: wire.updated_at,
		messages: (wire.messages ?? [])
			.map(toStoredMessage)
			.filter((m): m is StoredMessage => m !== null),
	};
}

/** Every conversation this browser owns, newest first, without transcripts. */
export async function fetchConversations(): Promise<Array<StoredConversation>> {
	const body = await call<{ conversations: Array<WireConversation> }>(
		"/api/conversations",
		undefined,
		isConversationList,
	);
	return (body.conversations ?? []).map(toStored);
}

/** One conversation, whole. */
export async function fetchConversation(
	threadId: string,
): Promise<StoredConversation> {
	return toStored(
		await call<WireConversation>(
			`/api/conversations/${encodeURIComponent(threadId)}`,
			undefined,
			isWireConversation,
		),
	);
}

/** Rename, or record where a generated title came from. */
export async function renameConversation(
	threadId: string,
	title: string,
	titleSource: "generated" | "manual",
): Promise<void> {
	await call<void>(`/api/conversations/${encodeURIComponent(threadId)}`, {
		method: "PATCH",
		body: JSON.stringify({ title, title_source: titleSource }),
	});
}

/** Delete one conversation, permanently. */
export async function deleteConversation(threadId: string): Promise<void> {
	await call<void>(`/api/conversations/${encodeURIComponent(threadId)}`, {
		method: "DELETE",
	});
}

/** Adopt conversations this browser started before ownership was recorded. */
export async function claimConversations(
	threadIds: Array<string>,
): Promise<number> {
	if (threadIds.length === 0) return 0;
	const body = await call<{ claimed: number }>("/api/conversations/claim", {
		method: "POST",
		body: JSON.stringify({ thread_ids: threadIds.slice(0, 500) }),
	});
	return body.claimed ?? 0;
}
