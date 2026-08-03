/**
 * Conversations, read back from the service.
 *
 * History used to be whatever this browser had written into localStorage, which
 * made a conversation a property of a device rather than of a person. The
 * transcripts were already in Postgres — written on every turn since the
 * persistence step — but nothing recorded whose they were, so nothing could
 * read them back.
 *
 * This module is the client for that read path. It deliberately returns the
 * same `StoredConversation` shape the rail and the transcript already consume:
 * the point of the change is where history comes from, not what a message looks
 * like, and a component that has to be rewritten to read its own history is a
 * migration nobody finishes.
 */

import { authHeaders } from "./session";
import type { StoredConversation, StoredMessage } from "./history";
import { parseAnswer } from "./knowledge";
import type { Source } from "./api";

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
	messages?: Array<WireMessage>;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
	const response = await fetch(`${API_URL}${path}`, {
		...init,
		headers: {
			"Content-Type": "application/json",
			...authHeaders(),
			...(init?.headers ?? {}),
		},
		signal: AbortSignal.timeout(TIMEOUT_MS),
	});
	if (!response.ok) throw new Error(`${path} failed: ${response.status}`);
	if (response.status === 204) return undefined as T;
	return (await response.json()) as T;
}

/**
 * The prose a turn is rendered from.
 *
 * Parsed here rather than on the server, because the parser already exists here
 * and a second implementation over the wire is two implementations to keep in
 * agreement. A game or eligibility turn carries no prose at all — the card is
 * the whole turn — so it is reconstructed as the marker it is.
 */
function toStoredMessage(message: WireMessage): StoredMessage | null {
	if (message.role === "user") return { role: "user", text: message.text ?? "" };
	if (message.role === "game")
		return { role: "game", gameType: message.game_type ?? "" };
	if (message.role === "eligibility") return { role: "eligibility" };
	if (message.role === "assistant") {
		return {
			role: "assistant",
			blocks: parseAnswer(message.text ?? ""),
			sources: message.sources ?? [],
			followUps: message.follow_ups ?? [],
		};
	}
	return null;
}

function toStored(wire: WireConversation): StoredConversation {
	return {
		threadId: wire.thread_id,
		title: wire.title ?? "",
		...(wire.title_source ? { titleSource: wire.title_source } : {}),
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

/**
 * Adopt conversations this browser started before ownership was recorded.
 *
 * Every transcript written before the owner column existed is readable by
 * nobody. This browser still has their ids in localStorage, and presenting an
 * id it could only have if it created the conversation is the strongest claim
 * available in a product with no accounts. The service only ever adopts rows
 * that are currently unowned, so replaying somebody else's ids takes nothing.
 */
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
