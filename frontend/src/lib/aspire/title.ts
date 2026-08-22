/** Conversation titles. */

import { API_URL } from "../config";
import { authHeaders } from "./session";

/** Short: nothing waits on this, but a hung request should not linger either. */
const TIMEOUT_MS = 15_000;

/** Hard cap, matched to the backend's own. */
export const TITLE_MAX = 48;

/**
 * What the tab says when no conversation is open. The chat page writes the
 * document title by hand, so both `__root`'s head and the landing page read it
 * from here rather than each keeping their own copy to drift from.
 */
export const DEFAULT_DOCUMENT_TITLE =
	"ASPIRE AI · Financial literacy assistant";

/** Asks the service to name a conversation. */
export async function requestTitle(input: {
	message: string;
	answer: string;
	language: string;
}): Promise<string | null> {
	try {
		const response = await fetch(`${API_URL}/api/title`, {
			method: "POST",
			// The session rides along: `/api/title` used to let anyone buy a model call.
			headers: { "Content-Type": "application/json", ...authHeaders() },
			body: JSON.stringify(input),
			signal: AbortSignal.timeout(TIMEOUT_MS),
		});
		if (!response.ok) return null;

		const body = (await response.json()) as { title?: string | null };
		const title = body.title?.trim();
		return title ? title.slice(0, TITLE_MAX) : null;
	} catch {
		// Offline, timed out, CORS, malformed JSON. All the same to the caller.
		return null;
	}
}
