/**
 * Global middleware registered on the Start instance in `src/start.ts`.
 *
 * Deliberately NOT under `src/server/` — `start.ts` is an isomorphic entry that
 * also loads in the browser (function middleware can have a `client` half), so
 * a module in the protected server-only directory would be a boundary
 * violation. The `.server()` bodies below are stripped from the client build by
 * the Start compiler; nothing privileged is imported here to begin with.
 *
 * `type: 'request'` runs once per inbound HTTP request (documents and server-fn
 * RPCs alike). `type: 'function'` wraps every server function call.
 */
import { createMiddleware } from "@tanstack/react-start";

/** Baseline security headers on every response. */
export const securityHeadersMiddleware = createMiddleware({
	type: "request",
}).server(async ({ next }) => {
	const result = await next();

	result.response.headers.set("X-Content-Type-Options", "nosniff");
	result.response.headers.set(
		"Referrer-Policy",
		"strict-origin-when-cross-origin",
	);
	result.response.headers.set("X-Frame-Options", "DENY");

	return result;
});

/** Times every server function invocation. */
export const timingMiddleware = createMiddleware({ type: "function" }).server(
	async ({ next }) => {
		const startedAt = Date.now();
		const result = await next();

		if (import.meta.env.DEV) {
			console.info(`[server-fn] handled in ${Date.now() - startedAt}ms`);
		}

		return result;
	},
);
