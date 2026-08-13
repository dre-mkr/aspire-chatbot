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
		defaultErrorComponent: RouteError,
		defaultNotFoundComponent: RouteNotFound,
		defaultPendingComponent: RoutePending,
		// Nothing pending is shown for the first 300ms.
		defaultPendingMs: 300,
		// Once it is shown it stays for 400ms.
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

