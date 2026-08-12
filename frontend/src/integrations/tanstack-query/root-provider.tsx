import { QueryClient } from "@tanstack/react-query";
import { HttpError } from "#/lib/aspire/conversations";

/** Whether a failure is worth asking again about. */
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
			// A failed write is shown and offered again, never retried unseen.
			mutations: { retry: false },
		},
	});

	return {
		queryClient,
	};
}
export default function TanstackQueryProvider() {}
