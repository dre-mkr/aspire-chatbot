/**
 * Conversation titles.
 *
 * A separate, small, non-streaming call, deliberately not folded into `/chat`:
 * that response streams and is RAG-grounded, and a title leaking into the
 * visible answer is worse than a title arriving a second late.
 *
 * Everything here is best effort. A failure returns null and the caller keeps
 * whatever fallback it already had, so a title never blocks, delays, or gates
 * the answer the reader is looking at.
 */

/** Where the FastAPI service lives. Override with VITE_ASPIRE_API_URL. */
const API_URL = (
	import.meta.env.VITE_ASPIRE_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

/** Short: nothing waits on this, but a hung request should not linger either. */
const TIMEOUT_MS = 15_000;

/** Hard cap, matched to the backend's own. */
export const TITLE_MAX = 48;

/**
 * Asks the service to name a conversation.
 *
 * Returns null for every unhappy path — the service declined because the
 * opening message had no subject, the call failed, the response was malformed.
 * The caller cannot tell them apart and does not need to.
 */
export async function requestTitle(input: {
	message: string;
	answer: string;
	language: string;
}): Promise<string | null> {
	try {
		const response = await fetch(`${API_URL}/api/title`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
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
