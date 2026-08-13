/** Start instance — global server/RPC configuration. */
import { createStart } from "@tanstack/react-start";
import { securityHeadersMiddleware, timingMiddleware } from "./middleware";

export const startInstance = createStart(() => ({
	/** Full document SSR by default; a route must opt out. */
	defaultSsr: true,
	requestMiddleware: [securityHeadersMiddleware],
	functionMiddleware: [timingMiddleware],
}));
