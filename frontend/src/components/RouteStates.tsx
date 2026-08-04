import { Link } from "@tanstack/react-router";

/**
 * What a route shows when it cannot show what was asked for.
 *
 * There were no `errorComponent`, `notFoundComponent` or `pendingComponent`
 * anywhere — not per route, not as a router default, not on the root. An
 * unknown URL or a thrown loader error landed on TanStack's built-in
 * developer-facing defaults: a stack trace, off-brand, with no route back into
 * the app. On a government service for children that is the wrong last line of
 * defence.
 *
 * English only, like the rest of the chrome. P10-002 (there is no i18n system
 * at all) is the owner's open decision; these strings are written as keys-in-
 * waiting rather than pretending the problem is solved here.
 */

function Surface({
	title,
	children,
}: {
	title: string;
	children: React.ReactNode;
}) {
	return (
		// `role="alert"` is deliberately NOT used. These mount as the whole view,
		// so there is nothing to interrupt -- an alert would be announced over the
		// page it already is. A heading and a landmark is what a screen reader
		// needs to find its way here.
		<main className="route-state">
			<div className="route-state__orb" aria-hidden="true" />
			<h1 className="route-state__title">{title}</h1>
			{children}
		</main>
	);
}

/** An unknown address. */
export function RouteNotFound() {
	return (
		<Surface title="That page does not exist">
			<p className="route-state__body">
				The link may be old, or the address may have a typo in it.
			</p>
			<Link to="/" className="route-state__action">
				Start a new chat
			</Link>
		</Surface>
	);
}

/**
 * A loader threw.
 *
 * The error itself is not rendered. It is a server message or a stack, written
 * for whoever wrote the code and not for a child reading it — and on a product
 * handling children's data it is also the wrong thing to put on a screen that
 * might be shared or screenshotted. It goes to the console, where the person
 * who can act on it will look.
 */
export function RouteError({ error }: { error: Error }) {
	if (typeof console !== "undefined") console.error(error);
	return (
		<Surface title="Something went wrong">
			<p className="route-state__body">
				This page could not be loaded. Trying again often works.
			</p>
			<div className="route-state__actions">
				{/* A real reload, not a router navigation: whatever failed may have
				    left state behind that a soft retry would meet again. */}
				<button
					type="button"
					className="route-state__action"
					onClick={() => window.location.reload()}
				>
					Try again
				</button>
				<Link to="/" className="route-state__action route-state__action--quiet">
					Start a new chat
				</Link>
			</div>
		</Surface>
	);
}

/**
 * A navigation that is taking long enough to be worth acknowledging.
 *
 * Paired with `defaultPendingMs` in `router.tsx`, so a fast navigation never
 * reaches it — a spinner that flashes for 80ms is worse than no spinner. It is
 * deliberately quiet: the transitions in this app are between views of the same
 * conversation, and a loud interstitial would read as more of a change than
 * actually happened.
 */
export function RoutePending() {
	return (
		<div className="route-state route-state--pending">
			<div className="route-state__orb route-state__orb--pulse" aria-hidden="true" />
			<p className="sr-only" role="status">
				Loading.
			</p>
		</div>
	);
}
