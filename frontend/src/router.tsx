import { createRouter as createTanStackRouter } from "@tanstack/react-router";
import { setupRouterSsrQueryIntegration } from "@tanstack/react-router-ssr-query";
import {
	RouteError,
	RouteNotFound,
	RoutePending,
} from "./components/RouteStates";
import { getContext } from "./integrations/tanstack-query/root-provider";
import { routeTree } from "./routeTree.gen";

export function getRouter() {
	const context = getContext();

	const router = createTanStackRouter({
		routeTree,
		context,
		scrollRestoration: true,
		defaultPreload: "intent",
		defaultPreloadStaleTime: 0,

		// The last line of defence, set once here rather than per route.
		//
		// Nothing defined any of these, so an unknown URL or a thrown loader error
		// landed on TanStack's developer-facing defaults -- a stack trace, off
		// brand, with no route back into the app.
		defaultErrorComponent: RouteError,
		defaultNotFoundComponent: RouteNotFound,
		defaultPendingComponent: RoutePending,
		// Nothing pending is shown for the first 300ms. Navigations here are
		// mostly between views of one conversation and usually resolve well inside
		// that; a spinner that flashes for 80ms reads as a fault, not as progress.
		defaultPendingMs: 300,
		// Once it is shown it stays for 400ms. Without a floor, a pending state
		// that appears at 301ms and resolves at 320ms is a flicker -- which is the
		// thing `defaultPendingMs` exists to avoid, moved 300ms later.
		defaultPendingMinMs: 400,
	});

	setupRouterSsrQueryIntegration({ router, queryClient: context.queryClient });

	return router;
}

declare module "@tanstack/react-router" {
	interface Register {
		router: ReturnType<typeof getRouter>;
	}
}

/**
 * The Start-side registration, moved here out of the generated route tree.
 *
 * It used to live at the bottom of `routeTree.gen.ts`, which `tsr generate`
 * rewrites from scratch. Regenerating — which anyone adding a route does —
 * silently deleted the type registration for the entire router along with the
 * app's only `ssr: true` declaration. Reproduced during the audit by
 * regenerating and diffing; the file was then restored byte for byte.
 *
 * This file already owns the sibling `@tanstack/react-router` augmentation
 * above, so both halves of the registration now sit together in a file nothing
 * generates. `import type` on both, so nothing here survives into the bundle
 * and the cycle with `start.ts` is erased.
 */
import type { startInstance } from "./start";

declare module "@tanstack/react-start" {
	interface Register {
		ssr: true;
		router: Awaited<ReturnType<typeof getRouter>>;
		config: Awaited<ReturnType<typeof startInstance.getOptions>>;
	}
}
