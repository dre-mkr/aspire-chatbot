/** Conversation history for the rail. */

import type { Source } from "./api";
import type { AnswerBlock } from "./knowledge";

const STORAGE_KEY = "aspire.conversations.v1";
const TITLE_MAX = 60;

export type StoredMessage =
	| { role: "user"; text: string }
	| {
			role: "assistant";
			blocks: Array<AnswerBlock>;
			sources: Array<Source>;
			followUps: Array<string>;
	  }
	/** A turn that started a game. */
	| { role: "game"; gameType: string }
	/** A turn that opened the eligibility check. */
	| { role: "eligibility" };

export interface StoredConversation {
	threadId: string;
	/** What this conversation is called, everywhere. */
	title: string;
	/** Where the title came from, which decides whether it may be replaced. */
	titleSource?: "generated" | "manual";
	/** The language it was held in, and who it was answered for. */
	language?: "en" | "es" | "fr";
	persona?: string;
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

		// Storage is shared with older builds and hand-edits, so trust no shape from it.
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

/** Drops one conversation from this browser's copy of history. */
export function forgetLocalConversation(threadId: string) {
	if (!canStore()) return;
	const next = loadConversations().filter(
		(conversation) => conversation.threadId !== threadId,
	);
	try {
		window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
	} catch {
		// Storage is a convenience: a quota or a private window must not break this.
	}
}

/** Shown when there is nothing better — never "Untitled", never empty. */
export const FALLBACK_TITLE = "New chat";

/** The middle rung of the fallback ladder: the first question, truncated. */
export function titleFor(question: string) {
	const clean = question.trim().replace(/\s+/g, " ");
	if (!clean) return FALLBACK_TITLE;
	return clean.length > TITLE_MAX ? `${clean.slice(0, TITLE_MAX - 1)}…` : clean;
}

/** What any surface should render for a conversation, fallbacks applied. */
export function displayTitle(conversation: { title?: string | null }): string {
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

