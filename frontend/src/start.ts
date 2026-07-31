/**
 * Start instance — global server/RPC configuration.
 *
 * The plugin resolves this file by convention (`src/start.ts`) and requires the
 * `startInstance` export. `defaultSsr` lives here rather than on `createRouter`
 * because it is a Start-level concern; individual routes override it with their
 * own `ssr` option.
 */
import { createStart } from "@tanstack/react-start";
import { securityHeadersMiddleware, timingMiddleware } from "./middleware";

export const startInstance = createStart(() => ({
	/**
	 * Full document SSR is the default: every route renders to HTML on the
	 * server unless it opts out. Routes that should not are explicit about it
	 * (`/dashboard` uses 'data-only', `/settings` uses false).
	 */
	defaultSsr: true,
	requestMiddleware: [securityHeadersMiddleware],
	functionMiddleware: [timingMiddleware],
}));
