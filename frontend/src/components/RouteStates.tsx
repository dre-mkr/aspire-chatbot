import { Link } from "@tanstack/react-router";

/** What a route shows when it cannot show what was asked for. */

function Surface({
	title,
	children,
}: {
	title: string;
	children: React.ReactNode;
}) {
	return (
		// `role="alert"` is deliberately NOT used.
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

/** A loader threw. */
export function RouteError({ error }: { error: Error }) {
	if (typeof console !== "undefined") console.error(error);
	return (
		<Surface title="Something went wrong">
			<p className="route-state__body">
				This page could not be loaded. Trying again often works.
			</p>
			<div className="route-state__actions">
				{/* A real reload: a soft retry would keep whatever state broke. */}
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

/** A navigation that is taking long enough to be worth acknowledging. */
export function RoutePending() {
	return (
		<div className="route-state route-state--pending">
			<div
				className="route-state__orb route-state__orb--pulse"
				aria-hidden="true"
			/>
			{/* `<output>` carries `role="status"` implicitly, with less markup. */}
			<output className="sr-only">Loading.</output>
		</div>
	);
}
