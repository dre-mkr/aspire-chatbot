import { useEffect, useState } from "react";
import { renewSessionIfStale } from "./auth";
import {
	currentSession,
	ensureSession,
	type Session,
	subscribeToSession,
} from "./session";

/**
 * Who is signed in, and whether that is known yet.
 *
 * `resolved` is the whole point of this hook. On first paint the answer is not
 * available: the token lives in storage the server has not seen, and during SSR
 * there is no storage at all. A control that renders "Sign in" and then swaps
 * to an avatar a moment later is the auth version of the completion flash —
 * something changing what it says after you have begun reading it. So callers
 * hold a neutral slot until `resolved` is true, and only then commit.
 *
 * `session` is null once resolved for somebody who has no identity at all,
 * which is a real state rather than an error: a first-time visitor is nobody
 * until they ask something, and the chat works regardless.
 *
 * Subscribed rather than read once, so a sign-in completed in another tab
 * reaches this one instead of leaving it rendering a stale signed-out state
 * until something happens to re-render it.
 */
export function useSession(): { session: Session | null; resolved: boolean } {
	const [session, setSession] = useState<Session | null>(() =>
		typeof window === "undefined" ? null : currentSession(),
	);
	const [resolved, setResolved] = useState(false);

	useEffect(() => {
		let live = true;

		const sync = () => {
			if (live) setSession(currentSession());
		};

		const stop = subscribeToSession(sync);
		// `storage` only fires in OTHER tabs, so the local writes come through
		// the subscription above and this covers the cross-tab case.
		window.addEventListener("storage", sync);

		// An identity already in hand resolves immediately; otherwise the answer
		// arrives with the anonymous session. Either way the slot commits once.
		const existing = currentSession();
		if (existing) {
			setSession(existing);
			setResolved(true);
			// Checked once on arrival and then hourly. Renewal happens beside
			// whatever else is going on and never blocks it; see
			// `renewSessionIfStale`.
			renewSessionIfStale();
		} else {
			void ensureSession()
				.then((fresh) => {
					if (!live) return;
					setSession(fresh);
				})
				.finally(() => {
					// Resolved even on failure. "We could not establish who you are"
					// still settles the question, and leaving the slot blank for ever
					// because the network is down would be worse than showing the
					// signed-out state it would have shown anyway.
					if (live) setResolved(true);
				});
		}

		const hourly = window.setInterval(renewSessionIfStale, 60 * 60 * 1000);

		return () => {
			live = false;
			stop();
			window.clearInterval(hourly);
			window.removeEventListener("storage", sync);
		};
	}, []);

	return { session, resolved };
}
