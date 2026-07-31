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
	title: string;
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

/** First question asked, which is what the rail lists it under. */
export function titleFor(question: string) {
	const clean = question.trim().replace(/\s+/g, " ");
	return clean.length > TITLE_MAX ? `${clean.slice(0, TITLE_MAX - 1)}…` : clean;
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
