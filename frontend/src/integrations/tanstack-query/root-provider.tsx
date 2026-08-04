import { QueryClient } from "@tanstack/react-query";
import { HttpError } from "#/lib/aspire/conversations";

/**
 * Whether a failure is worth asking again about.
 *
 * The client used to be constructed bare, so anything added later inherited
 * Query's default of three retries with backoff, and the queries that did
 * override it used an unconditional `retry: 1` — which retried a 401 from an
 * expired session and a 404 for a deleted conversation exactly as eagerly as a
 * 503. Neither can succeed the second time.
 *
 * So: server faults and rate limits are retried, client faults are not, and
 * anything without a status (a network drop, a timeout) is retried because it
 * genuinely might have been transient.
 *
 * Worth stating plainly, because it looks like a cost decision and is not: this
 * cannot multiply model spend. Every call that spends a model call — `/chat`,
 * `/chat/stream`, `/api/title` — is a bare `fetch` outside Query by deliberate
 * design (see `queries.ts`). Nothing this policy governs reaches a model.
 */
function retryable(failureCount: number, error: unknown): boolean {
	if (failureCount >= 2) return false;
	if (error instanceof HttpError) {
		return error.status === 429 || error.status >= 500;
	}
	return true;
}

export function getContext() {
	const queryClient = new QueryClient({
		defaultOptions: {
			queries: { retry: retryable },
			// A failed write is shown and offered again rather than retried behind
			// the reader's back: a rename that silently succeeds on the third
			// attempt, after the UI has already rolled back, is worse than one that
			// clearly failed.
			mutations: { retry: false },
		},
	});

	return {
		queryClient,
	};
}
export default function TanstackQueryProvider() {}
