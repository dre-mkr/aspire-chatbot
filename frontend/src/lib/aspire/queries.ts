/** The Query boundary: what TanStack Query is allowed to own, and its keys. */
import type { QueryClient } from "@tanstack/react-query";
import { queryOptions } from "@tanstack/react-query";
import { fetchConversation, fetchConversations } from "./conversations";
import { fetchEligibilityState } from "./eligibility";
import { fetchGameState } from "./games";
import type { StoredConversation } from "./history";
import { currentSession } from "./session";

/** Every cache key in the product. */
export const keys = {
	/** The rail's list, for one identity. */
	conversations: (ownerId = "anon") => ["conversations", ownerId] as const,
	/** The prefix every identity's list sits under. */
	allConversations: () => ["conversations"] as const,
	conversation: (ownerId: string, threadId: string) =>
		["conversations", ownerId, threadId] as const,
	/** One conversation's transcript. */
	messages: (ownerId: string, threadId: string) =>
		["conversations", ownerId, threadId, "messages"] as const,

	/** The prefix every game cache entry sits under. */
	allGames: () => ["games"] as const,
	/** The running game for a thread, or null once it is over. */
	gameState: (threadId: string, ownerId = "anon") =>
		["games", "state", ownerId, threadId] as const,

	/** The prefix every eligibility cache entry sits under. See `allGames`. */
	allEligibility: () => ["eligibility"] as const,
	/** The eligibility flow's server-side state for a thread. See `gameState`. */
	eligibilityState: (threadId: string, ownerId = "anon") =>
		["eligibility", "state", ownerId, threadId] as const,
} as const;

/** The rail's list of conversations. */
export const conversationsQuery = (
	ownerId = currentSession()?.userId ?? "anon",
) =>
	queryOptions({
		queryKey: keys.conversations(ownerId),
		queryFn: fetchConversations,
		// Identity is client-only, so this cannot be answered during SSR.
		enabled: Boolean(currentSession()),
		staleTime: 30_000,
		// History that fails to load must never be an error in the reader's face.
		retry: 1,
	});

/** One conversation, whole, for reopening it. */
export const conversationQuery = (
	threadId: string | null,
	ownerId = currentSession()?.userId ?? "anon",
) =>
	queryOptions({
		queryKey: keys.messages(ownerId, threadId ?? ""),
		queryFn: () => fetchConversation(threadId as string),
		enabled: Boolean(threadId) && Boolean(currentSession()),
		staleTime: Number.POSITIVE_INFINITY,
		// Without this the entry is evicted five minutes after its last observer.
		gcTime: Number.POSITIVE_INFINITY,
		refetchOnWindowFocus: false,
		retry: 1,
	});

/** The game the server is currently running for this thread. */
export const gameStateQuery = (threadId: string | null, settled = true) =>
	queryOptions({
		queryKey: keys.gameState(threadId ?? "", owner()),
		queryFn: () => fetchGameState(threadId as string),
		// Gated on the turn being over, not merely on having a thread.
		enabled: Boolean(threadId) && settled,
		staleTime: Number.POSITIVE_INFINITY,
		// See `conversationQuery`: the default gcTime would evict a merely off-screen card.
		gcTime: Number.POSITIVE_INFINITY,
		refetchOnWindowFocus: false,
		refetchOnReconnect: false,
		refetchOnMount: false,
		retry: false,
	});

/** The eligibility flow's state, while the server still has a session for it. */
export const eligibilityStateQuery = (
	threadId: string | null,
	language: string,
	settled = true,
) =>
	queryOptions({
		queryKey: keys.eligibilityState(threadId ?? "", owner()),
		queryFn: () => fetchEligibilityState(threadId as string, language),
		// Same gate, same reason as the game query above.
		enabled: Boolean(threadId) && settled,
		staleTime: Number.POSITIVE_INFINITY,
		// See `conversationQuery`: the default gcTime would evict a merely off-screen card.
		gcTime: Number.POSITIVE_INFINITY,
		refetchOnWindowFocus: false,
		refetchOnReconnect: false,
		refetchOnMount: false,
		retry: false,
	});

/** Writing to the conversation list without waiting for the server. */
type Conversations = Array<StoredConversation>;

/** Everything the rail currently knows, straight out of the cache. */
function owner(): string {
	return currentSession()?.userId ?? "anon";
}

export function readConversations(queryClient: QueryClient): Conversations {
	return (
		queryClient.getQueryData<Conversations>(keys.conversations(owner())) ?? []
	);
}

export function readConversation(
	queryClient: QueryClient,
	threadId: string,
): StoredConversation | undefined {
	// The list carries no transcripts, so prefer a loaded full record over the summary.
	return (
		queryClient.getQueryData<StoredConversation>(
			keys.messages(owner(), threadId),
		) ?? readConversations(queryClient).find((c) => c.threadId === threadId)
	);
}

/** Inserts or replaces one conversation, newest first. */
export function upsertConversation(
	queryClient: QueryClient,
	conversation: StoredConversation,
) {
	// Cancel first.
	void queryClient.cancelQueries(
		{ queryKey: keys.conversations(owner()) },
		{ revert: false },
	);
	queryClient.setQueryData<Conversations>(
		keys.conversations(owner()),
		(previous) => [
			conversation,
			...(previous ?? []).filter((c) => c.threadId !== conversation.threadId),
		],
	);

	// And the transcript itself, which is the half that was missing.
	if (conversation.messages.length > 0) {
		queryClient.setQueryData<StoredConversation>(
			keys.messages(owner(), conversation.threadId),
			conversation,
		);
	}
}

/** Takes one conversation out of the cache entirely. */
export function removeConversationFromCache(
	queryClient: QueryClient,
	threadId: string,
): StoredConversation | undefined {
	// An in-flight list fetch still holds this conversation and would overwrite this.
	void queryClient.cancelQueries(
		{ queryKey: keys.conversations(owner()) },
		{ revert: false },
	);

	// Handed back so a failed delete can be undone.
	const removed = readConversations(queryClient).find(
		(conversation) => conversation.threadId === threadId,
	);

	queryClient.setQueryData<Conversations>(
		keys.conversations(owner()),
		(previous) =>
			(previous ?? []).filter(
				(conversation) => conversation.threadId !== threadId,
			),
	);
	queryClient.removeQueries({
		queryKey: keys.messages(owner(), threadId),
		exact: true,
	});
	// Whatever the conversation was part-way through.
	queryClient.removeQueries({
		queryKey: keys.gameState(threadId, owner()),
		exact: true,
	});
	queryClient.removeQueries({
		queryKey: keys.eligibilityState(threadId, owner()),
		exact: true,
	});

	return removed;
}

/** Renames one conversation in the cache, without touching its timestamp. */
export function retitleInCache(
	queryClient: QueryClient,
	threadId: string,
	title: string,
	// `undefined` is a real value, not an omitted argument: the "nobody typed this" state.
	titleSource: "generated" | "manual" | undefined,
) {
	const apply = (conversation: StoredConversation) =>
		conversation.threadId === threadId
			? { ...conversation, title, titleSource }
			: conversation;

	// Same as the optimistic insert: an in-flight list fetch carries the old name.
	void queryClient.cancelQueries(
		{ queryKey: keys.conversations(owner()) },
		{ revert: false },
	);
	queryClient.setQueryData<Conversations>(
		keys.conversations(owner()),
		(previous) => (previous ?? []).map(apply),
	);
	queryClient.setQueryData<StoredConversation>(
		keys.messages(owner(), threadId),
		(previous) => (previous ? apply(previous) : previous),
	);
}

/** What a conversation is called right now, for putting back if a write fails. */
export function titleSnapshot(
	queryClient: QueryClient,
	threadId: string,
): { title: string; titleSource: "generated" | "manual" | undefined } {
	const current = readConversation(queryClient, threadId);
	return { title: current?.title ?? "", titleSource: current?.titleSource };
}

/** Drops the "a person typed this" lock, so a regenerate may replace it. */
export function clearTitleLockInCache(
	queryClient: QueryClient,
	threadId: string,
) {
	queryClient.setQueryData<Conversations>(
		keys.conversations(owner()),
		(previous) =>
			(previous ?? []).map((conversation) =>
				conversation.threadId === threadId
					? { ...conversation, titleSource: undefined }
					: conversation,
			),
	);
}

/** The completion handoff, and the only place the two layers touch. */
export function invalidateAfterTurn(
	queryClient: QueryClient,
	threadId: string | null,
) {
	if (!threadId) return;
	void queryClient.invalidateQueries({
		queryKey: keys.gameState(threadId, owner()),
	});
	void queryClient.invalidateQueries({
		queryKey: keys.eligibilityState(threadId, owner()),
	});
	// Reaches the transcript too: its key is prefixed by `["conversations", id]`.
	void queryClient.invalidateQueries({
		queryKey: keys.conversation(owner(), threadId),
	});
	// `exact`, because `["conversations", owner]` is a PREFIX of every transcript key for that owner.
	void queryClient.invalidateQueries({
		queryKey: keys.conversations(owner()),
		exact: true,
	});
}
