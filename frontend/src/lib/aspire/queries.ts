/**
 * The Query boundary: what TanStack Query is allowed to own, and its keys.
 *
 * One rule governs this file. **Query owns durable server state. It does not
 * own the in-flight assistant response.** The reply being revealed lives in
 * `use-conversation`, in component state, and nothing here may ever hold a
 * partial answer. If a query function in this file ever returns half a reply,
 * that is the bug, not a feature.
 *
 * The two layers meet at exactly one point, and it is `invalidateAfterTurn`
 * below: when a turn settles, the caches it could have changed are invalidated
 * and refetched from the server. Nothing else crosses.
 *
 * Keys are declared here rather than inline at the call sites so that
 * invalidation cannot silently miss one. A key written twice is a key that will
 * eventually be written differently.
 */
import type { QueryClient } from "@tanstack/react-query";
import { queryOptions } from "@tanstack/react-query";
import { fetchConversation, fetchConversations } from "./conversations";
import { deviceId } from "./device";
import { fetchEligibilityState } from "./eligibility";
import { fetchGameState } from "./games";
import type { StoredConversation } from "./history";

/**
 * Every cache key in the product.
 *
 * Hierarchical on purpose: `["conversations", id, "messages"]` is invalidated
 * by anything that invalidates `["conversations", id]`, which is what lets the
 * completion handoff name a conversation rather than enumerate its resources.
 */
export const keys = {
	/** The rail's list of conversations. */
	conversations: () => ["conversations"] as const,
	conversation: (threadId: string) => ["conversations", threadId] as const,
	/** One conversation's transcript. */
	messages: (threadId: string) => ["conversations", threadId, "messages"] as const,

	/** The running game for a thread, or null once it is over. */
	gameState: (threadId: string) => ["games", "state", threadId] as const,

	/** The eligibility flow's server-side state for a thread. */
	eligibilityState: (threadId: string) =>
		["eligibility", "state", threadId] as const,
} as const;

/**
 * The rail's list of conversations.
 *
 * Owned by the service now rather than by this browser's storage. Refetched on
 * focus, unlike everything else here, and that is the one place a refetch is
 * genuinely wanted: a conversation carried on in another tab should appear when
 * you come back to this one, and the list is cheap.
 */
export const conversationsQuery = () =>
	queryOptions({
		queryKey: keys.conversations(),
		queryFn: fetchConversations,
		// Identity is client-only, so this cannot be answered during SSR.
		enabled: Boolean(deviceId()),
		staleTime: 30_000,
		// History that fails to load must never be an error in the reader's face.
		// The rail simply shows what it has, which before the first load is
		// nothing — the same thing it showed while localStorage was being read.
		retry: 1,
	});

/**
 * One conversation, whole, for reopening it.
 *
 * Kept for the session once loaded: a transcript that has settled does not
 * change behind you, and re-reading it on every visit to a chat you are
 * flipping between would make the rail feel slower than the storage it replaced.
 */
export const conversationQuery = (threadId: string | null) =>
	queryOptions({
		queryKey: keys.messages(threadId ?? ""),
		queryFn: () => fetchConversation(threadId as string),
		enabled: Boolean(threadId) && Boolean(deviceId()),
		staleTime: Number.POSITIVE_INFINITY,
		refetchOnWindowFocus: false,
		retry: 1,
	});

/**
 * The game the server is currently running for this thread.
 *
 * `staleTime: Infinity` and every automatic refetch switched off, deliberately.
 * Before this was a query it was an effect that fired on exactly three things:
 * the thread changing, a message landing, and the turn settling. Query's
 * defaults would have added refetch-on-focus and refetch-on-reconnect, which
 * means alt-tabbing away from a half-finished word scramble and back would
 * re-read the session — a refetch nobody asked for, during a puzzle a child is
 * part-way through. The only thing that refreshes this is the completion
 * handoff, which is the same trigger it had before.
 *
 * `retry: false` because games are additive: an endpoint that is off or
 * unreachable means no card, and the conversation carries on unaffected. There
 * is nothing here worth making someone wait through three attempts for.
 */
export const gameStateQuery = (threadId: string | null, settled = true) =>
	queryOptions({
		queryKey: keys.gameState(threadId ?? ""),
		queryFn: () => fetchGameState(threadId as string),
		// Gated on the turn being over, not merely on having a thread. The effect
		// this replaced opened with `if (!threadId || !settled) return`, and
		// dropping that half asked the server for the game session at the instant
		// the question was sent — a request per turn that nobody had before, at the
		// one moment the answer to it is guaranteed not to have changed yet.
		enabled: Boolean(threadId) && settled,
		staleTime: Number.POSITIVE_INFINITY,
		refetchOnWindowFocus: false,
		refetchOnReconnect: false,
		refetchOnMount: false,
		retry: false,
	});

/**
 * The eligibility flow's state, while the server still has a session for it.
 *
 * Keyed by thread and NOT by language, which is not an oversight. The language
 * is read when the request is made, but a change to it must not re-key: someone
 * switching the interface language part-way through a check would otherwise
 * refetch and redraw the card they are answering. That was the behaviour before
 * this became a query and it is the behaviour worth keeping — the flow opened in
 * a language and finishes in it.
 *
 * Only half the story lives here. Once a verdict exists the server deletes the
 * session, and the result is read from device storage instead — see
 * `loadEligibilityResult`. That split is deliberate and predates this file: a
 * minor's answers were never meant to leave the device, so the durable half of
 * this flow is the half Query must not own.
 */
export const eligibilityStateQuery = (
	threadId: string | null,
	language: string,
	settled = true,
) =>
	queryOptions({
		queryKey: keys.eligibilityState(threadId ?? ""),
		queryFn: () => fetchEligibilityState(threadId as string, language),
		// Same gate, same reason as the game query above.
		enabled: Boolean(threadId) && settled,
		staleTime: Number.POSITIVE_INFINITY,
		refetchOnWindowFocus: false,
		refetchOnReconnect: false,
		refetchOnMount: false,
		retry: false,
	});

/**
 * Writing to the conversation list without waiting for the server.
 *
 * These exist because history used to be synchronous. Sending the first message
 * of a chat put a row in the rail in the same commit as the user's own bubble —
 * no spinner, no gap — and that was a deliberate property, not an accident of
 * localStorage being fast. Replacing it with "await the round trip" would be a
 * visible regression even though every byte on screen ends up identical.
 *
 * So the cache is written optimistically and the server is asked afterwards.
 * The completion handoff invalidates the list, so the server's version wins
 * within the same turn and nothing can drift for long.
 */
type Conversations = Array<StoredConversation>;

/** Everything the rail currently knows, straight out of the cache. */
export function readConversations(queryClient: QueryClient): Conversations {
	return queryClient.getQueryData<Conversations>(keys.conversations()) ?? [];
}

export function readConversation(
	queryClient: QueryClient,
	threadId: string,
): StoredConversation | undefined {
	// The list carries no transcripts, so a full record is preferred when one
	// has been loaded and the summary is the fallback.
	return (
		queryClient.getQueryData<StoredConversation>(keys.messages(threadId)) ??
		readConversations(queryClient).find((c) => c.threadId === threadId)
	);
}

/** Inserts or replaces one conversation, newest first. */
export function upsertConversation(
	queryClient: QueryClient,
	conversation: StoredConversation,
) {
	// Cancel first. A list fetch started on mount can still be in flight when the
	// first message is sent, and it resolves with a list that does not contain
	// the conversation being created — landing after this write and erasing the
	// row from the rail a beat after it appeared.
	void queryClient.cancelQueries({ queryKey: keys.conversations() }, { revert: false });
	queryClient.setQueryData<Conversations>(keys.conversations(), (previous) => [
		conversation,
		...(previous ?? []).filter((c) => c.threadId !== conversation.threadId),
	]);
}

/**
 * Renames one conversation in the cache, without touching its timestamp.
 *
 * The timestamp is left alone on purpose and it is the same reason it was left
 * alone when this wrote to localStorage: reordering the rail because a title
 * arrived would move a row out from under the reader's cursor.
 */
export function retitleInCache(
	queryClient: QueryClient,
	threadId: string,
	title: string,
	titleSource: "generated" | "manual",
) {
	const apply = (conversation: StoredConversation) =>
		conversation.threadId === threadId
			? { ...conversation, title, titleSource }
			: conversation;

	// Same reason as the optimistic insert: a list fetch already in flight
	// answers with the old name and would land on top of this one.
	void queryClient.cancelQueries({ queryKey: keys.conversations() }, { revert: false });
	queryClient.setQueryData<Conversations>(keys.conversations(), (previous) =>
		(previous ?? []).map(apply),
	);
	queryClient.setQueryData<StoredConversation>(
		keys.messages(threadId),
		(previous) => (previous ? apply(previous) : previous),
	);
}

/** Drops the "a person typed this" lock, so a regenerate may replace it. */
export function clearTitleLockInCache(
	queryClient: QueryClient,
	threadId: string,
) {
	queryClient.setQueryData<Conversations>(keys.conversations(), (previous) =>
		(previous ?? []).map((conversation) =>
			conversation.threadId === threadId
				? { ...conversation, titleSource: undefined }
				: conversation,
		),
	);
}

/**
 * The completion handoff, and the only place the two layers touch.
 *
 * Called when a turn has settled — not when one starts, and never per token.
 * The streaming layer knows when it is finished; Query knows what that could
 * have changed. This function is the whole of the contract between them.
 *
 * Invalidating rather than writing: the point is to ask the server what is now
 * true, because the turn may have started a game, closed one, opened the
 * eligibility check, or done nothing at all, and the client cannot tell which
 * from the text of a reply.
 *
 * The list is invalidated too, and not only for this conversation: a turn moves
 * a chat to the top of the rail and can give it its first real title, so the
 * ordering of every row is potentially stale.
 */
export function invalidateAfterTurn(
	queryClient: QueryClient,
	threadId: string | null,
) {
	if (!threadId) return;
	void queryClient.invalidateQueries({ queryKey: keys.gameState(threadId) });
	void queryClient.invalidateQueries({
		queryKey: keys.eligibilityState(threadId),
	});
	// Reaches this conversation's transcript too: `["conversations", id]` is a
	// prefix of `["conversations", id, "messages"]`.
	void queryClient.invalidateQueries({ queryKey: keys.conversation(threadId) });
	void queryClient.invalidateQueries({ queryKey: keys.conversations() });
}
