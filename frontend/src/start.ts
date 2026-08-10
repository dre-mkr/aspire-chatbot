/** Start instance — global server/RPC configuration. */
import { createStart } from "@tanstack/react-start";
import { securityHeadersMiddleware, timingMiddleware } from "./middleware";

export const startInstance = createStart(() => ({
	/** Full document SSR is the default: every route renders to HTML on the server unless it opts out. */
	defaultSsr: true,
	requestMiddleware: [securityHeadersMiddleware],
	functionMiddleware: [timingMiddleware],
}));
