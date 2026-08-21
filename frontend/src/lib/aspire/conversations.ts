/** Conversations, read back from the service. */

import { API_URL } from "../config";
import type { Source } from "./api";
import type { StoredConversation, StoredMessage } from "./history";
import { parseAnswer } from "./knowledge";
import { authHeaders } from "./session";

/** Long enough for a cold Neon instance, short enough not to hang the rail. */
const TIMEOUT_MS = 12000;

/**
 * Mints the id for a conversation, in the browser, before anything is sent.
 * The service adopts whatever it is given, which is what lets the landing page
 * know a chat's address before it knows anything else about it.
 */
export function newThreadId(): string {
	const uuid = globalThis.crypto?.randomUUID?.();
	if (uuid) return uuid;
	return `t-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * A stored citation, as the server persisted it.
 *
 * Flat — `{kb_id, question, snippet, url, ...}` — which is NOT the `{content,
 * metadata}` shape the renderer takes. That mismatch is what `normaliseSource`
 * exists to bridge; typing it as `Source` here was what hid the bridge's bug.
 */
interface WireSource {
	kb_id?: string;
	title?: string;
	question?: string;
	snippet?: string;
	source_url?: string;
	site?: string;
	page?: string;
	domain?: string;
	updated?: string;
}

interface WireMessage {
	role: string;
	text?: string;
	sources?: Array<WireSource | Source>;
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
function text(value: unknown): string {
	return typeof value === "string" ? value : "";
}

/**
 * Give a stored citation the shape the renderer expects.
 *
 * The server persists citations flat, and the renderer reads the row's own
 * words out of `content`. The previous version moved every unrecognised key
 * into `metadata` and left `content` empty, so a reloaded conversation showed
 * the question and the reference and lost the evidence underneath them — the
 * one part of the panel that is the source's own text. `snippet` is now read
 * into `content` explicitly, and the provenance fields into `origin`.
 */
function normaliseSource(source: Source | WireSource): Source {
	if (
		source &&
		typeof source === "object" &&
		"metadata" in source &&
		source.metadata
	)
		return source as Source;

	const stored = (source ?? {}) as Record<string, unknown>;
	const { content, snippet, source_url, site, page, domain, updated, ...rest } =
		stored;
	const origin = {
		url: text(source_url),
		site: text(site),
		page: text(page),
		domain: text(domain),
		updated: text(updated),
	};

	// The same fallbacks the live path applies (stream.ts), deliberately kept
	// in step. They had drifted: live used `snippet || title || kb_id` for the
	// body and `question || title` for the label, and this read only `snippet`
	// and only `question` — so a row the corpus stores with no `question`,
	// which is every non-QA chunk, showed its title while the conversation was
	// open and nothing at all after a reload.
	const meta = rest as Record<string, string | number>;
	const title = typeof meta.title === "string" ? meta.title : "";
	const kbId = typeof meta.kb_id === "string" ? meta.kb_id : "";

	return {
		content: text(content) || text(snippet) || title || kbId,
		metadata: { ...meta, ...(meta.question || !title ? {} : { question: title }) },
		// Only when the row was actually attributed. An absent `origin` is how
		// the panel knows there is nothing to name, rather than a name that is
		// the empty string. `domain` counts: a source can arrive with a host and
		// no site name, and dropping `origin` there un-names it entirely.
		...(origin.url || origin.site || origin.page || origin.domain
			? { origin }
			: {}),
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
