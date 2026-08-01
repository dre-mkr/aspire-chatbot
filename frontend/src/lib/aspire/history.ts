/**
 * Conversation history for the rail.
 *
 * Phase 1 of the backend has no database, so history lives in this browser.
 * The thread id is stored alongside the transcript, so reopening a conversation
 * continues the same server-side thread when the backend is still running.
 * The backend keeps conversation memory in process: after it restarts, an old
 * transcript still reads back correctly but the agent no longer remembers it.
 */

import type { Source } from "./api";
import type { AnswerBlock } from "./knowledge";

const STORAGE_KEY = "aspire.conversations.v1";
/** Enough for the rail to feel lived-in without unbounded growth. */
const MAX_CONVERSATIONS = 50;
const TITLE_MAX = 60;

export type StoredMessage =
	| { role: "user"; text: string }
	| {
			role: "assistant";
			blocks: Array<AnswerBlock>;
			sources: Array<Source>;
			followUps: Array<string>;
	  };

export interface StoredConversation {
	threadId: string;
	/**
	 * What this conversation is called, everywhere.
	 *
	 * The single source of truth for both the top bar and the rail — they never
	 * derive their own. Falls back through: generated title → truncated first
	 * message → "New chat".
	 */
	title: string;
	/**
	 * Where the title came from, which decides whether it may be replaced.
	 *
	 * Absent means it is still the truncated first message and generation is
	 * welcome to improve it. "generated" means the model named it, and it is
	 * only replaced on an explicit regenerate. "manual" means a person typed it,
	 * and generation must never touch it again.
	 */
	titleSource?: "generated" | "manual";
	updatedAt: number;
	messages: Array<StoredMessage>;
}

export interface HistoryGroup {
	label: string;
	items: Array<StoredConversation>;
}

function canStore() {
	// This module is imported during SSR, where there is no window at all.
	return typeof window !== "undefined" && !!window.localStorage;
}

export function loadConversations(): Array<StoredConversation> {
	if (!canStore()) return [];

	try {
		const raw = window.localStorage.getItem(STORAGE_KEY);
		if (!raw) return [];

		const parsed: unknown = JSON.parse(raw);
		if (!Array.isArray(parsed)) return [];

		// Storage is shared with older builds and with hand-editing, so nothing
		// out of it is trusted structurally.
		return (parsed as Array<StoredConversation>)
			.filter(
				(item) =>
					item &&
					typeof item.threadId === "string" &&
					typeof item.title === "string" &&
					Array.isArray(item.messages),
			)
			.sort((a, b) => b.updatedAt - a.updatedAt);
	} catch {
		return [];
	}
}

/** Inserts or replaces one conversation, newest first. */
export function saveConversation(
	conversation: StoredConversation,
): Array<StoredConversation> {
	const next = [
		conversation,
		...loadConversations().filter((c) => c.threadId !== conversation.threadId),
	].slice(0, MAX_CONVERSATIONS);

	if (canStore()) {
		try {
			window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
		} catch {
			// Private browsing and full quotas both throw here. History is a
			// convenience; losing it must never interrupt the conversation.
		}
	}

	return next;
}

/** Shown when there is nothing better — never "Untitled", never empty. */
export const FALLBACK_TITLE = "New chat";

/**
 * The middle rung of the fallback ladder: the first question, truncated.
 *
 * Only ever a placeholder. Nearly every conversation here opens with a question
 * about ASPIRE, so a list built from these reads as a column of near-identical
 * entries — which is the problem generated titles exist to solve. An opening
 * message with no words in it gets the fallback instead.
 */
export function titleFor(question: string) {
	const clean = question.trim().replace(/\s+/g, " ");
	if (!clean) return FALLBACK_TITLE;
	return clean.length > TITLE_MAX ? `${clean.slice(0, TITLE_MAX - 1)}…` : clean;
}

/** What any surface should render for a conversation, fallbacks applied. */
export function displayTitle(conversation: {
	title?: string | null;
}): string {
	return conversation.title?.trim() || FALLBACK_TITLE;
}

/** Buckets conversations the way the rail groups them. */
export function groupByRecency(
	conversations: Array<StoredConversation>,
): Array<HistoryGroup> {
	const startOfToday = new Date();
	startOfToday.setHours(0, 0, 0, 0);

	const today = startOfToday.getTime();
	const yesterday = today - 86_400_000;
	const lastWeek = today - 7 * 86_400_000;

	const groups: Array<HistoryGroup> = [
		{ label: "Today", items: [] },
		{ label: "Yesterday", items: [] },
		{ label: "Last 7 days", items: [] },
		{ label: "Earlier", items: [] },
	];

	for (const conversation of conversations) {
		const at = conversation.updatedAt;
		if (at >= today) groups[0].items.push(conversation);
		else if (at >= yesterday) groups[1].items.push(conversation);
		else if (at >= lastWeek) groups[2].items.push(conversation);
		else groups[3].items.push(conversation);
	}

	return groups.filter((group) => group.items.length > 0);
}

/**
 * Renames one conversation in place.
 *
 * Separate from `saveConversation` because a rename must not touch the
 * transcript or the timestamp — reordering the rail because a title arrived
 * would move a row out from under the reader's cursor.
 *
 * A manual title is never overwritten by a generated one; that is the whole
 * point of the flag. An explicit regenerate clears it first.
 */
export function retitleConversation(
	threadId: string,
	title: string,
	source: "generated" | "manual",
): Array<StoredConversation> {
	const clean = title.trim().slice(0, TITLE_MAX);
	if (!clean) return loadConversations();

	const next = loadConversations().map((conversation) => {
		if (conversation.threadId !== threadId) return conversation;
		if (source === "generated" && conversation.titleSource === "manual") {
			return conversation;
		}
		return { ...conversation, title: clean, titleSource: source };
	});

	if (canStore()) {
		try {
			window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
		} catch {
			// Same reasoning as saveConversation: history is a convenience.
		}
	}
	return next;
}

/** Drops the manual flag so a regenerate is allowed to replace the title. */
export function clearTitleLock(threadId: string): Array<StoredConversation> {
	const next = loadConversations().map((conversation) =>
		conversation.threadId === threadId
			? { ...conversation, titleSource: undefined }
			: conversation,
	);
	if (canStore()) {
		try {
			window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
		} catch {
			// As above.
		}
	}
	return next;
}
