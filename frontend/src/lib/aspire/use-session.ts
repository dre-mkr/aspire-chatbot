import { useEffect, useState } from "react";
import { renewSessionIfStale } from "./auth";
import {
	currentSession,
	ensureSession,
	type Session,
	subscribeToSession,
} from "./session";

/** Who is signed in, and whether that is known yet. */
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
		// `storage` only fires in OTHER tabs, so the local writes come through the subscription above and this covers t…
		window.addEventListener("storage", sync);

		// An identity already in hand resolves immediately; otherwise the answer arrives with the anonymous session.
		const existing = currentSession();
		if (existing) {
			setSession(existing);
			setResolved(true);
			// Checked once on arrival and then hourly.
			renewSessionIfStale();
		} else {
			void ensureSession()
				.then((fresh) => {
					if (!live) return;
					setSession(fresh);
				})
				.finally(() => {
					// Resolved even on failure.
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
