import { useEffect, useState } from "react";

/**
 * The first-visit opening: a short branded moment, and nothing else.
 *
 * It used to ask who was reading as well, which is how this app ended up
 * putting the same question twice on one screen — this panel and
 * `GuideChooser` both opened on a first visit, stacked, with different copy
 * and different words for the same five guides. `GuideChooser` is the better
 * of the two and is now the only one that asks; this keeps the opening it
 * never had and hands over when the opening is done.
 *
 * Two requirements pull against each other and both are met here. It must not
 * slow the assistant down — so the app renders behind this from the first frame
 * and nothing waits on it — and a returning reader must never see it again, so
 * the flag is read from storage in a mount effect rather than during render.
 * That is the same rule every other stored preference in this app follows:
 * `window` does not exist during SSR, and a `useState` initialiser that reaches
 * for it produces a hydration mismatch instead of a value.
 *
 * The consequence worth knowing: a first-time reader sees the opening one frame
 * late rather than immediately. That is the correct trade — the alternative is
 * every returning reader seeing a flash of it.
 */

const KEY = "aspire.opening.v1";

/**
 * What this used to write, back when it also asked who was reading.
 *
 * Read only. `guideAsked` reads it too, and takes it to mean the question has
 * been answered — so writing it here as well would tell that check the question
 * had been answered the moment the opening finished, and the chooser would
 * never open. Hence the separate key above: one flag per thing it means.
 */
const LEGACY_KEY = "aspire.intro.v1";

/** ~1.4s in total: long enough to read four words, short enough not to be a gate. */
const SPLASH_MS = 1400;

function seen(): boolean {
	try {
		return (
			window.localStorage.getItem(KEY) === "1" ||
			window.localStorage.getItem(LEGACY_KEY) === "1"
		);
	} catch {
		// Private browsing. Treat it as seen rather than showing it on every load.
		return true;
	}
}

function remember() {
	try {
		window.localStorage.setItem(KEY, "1");
	} catch {
		// Nothing to do. It runs once more next time at worst.
	}
}

type Phase = "checking" | "splash" | "done";

export function FirstRun({
	/**
	 * Called once the opening is over — immediately for a returning reader, who
	 * never sees it. Whatever comes next on this screen waits for this rather
	 * than opening on top of the splash.
	 */
	onDone,
}: {
	onDone?: () => void;
}) {
	const [phase, setPhase] = useState<Phase>("checking");

	useEffect(() => {
		if (seen()) {
			setPhase("done");
			return;
		}
		// Somebody who has asked for less motion gets none of the show.
		const still = window.matchMedia?.(
			"(prefers-reduced-motion: reduce)",
		)?.matches;
		if (still) {
			remember();
			setPhase("done");
			return;
		}
		setPhase("splash");
	}, []);

	// The opening advances on its own, or on any key or pointer press.
	useEffect(() => {
		if (phase !== "splash") return;
		const skip = () => {
			remember();
			setPhase("done");
		};
		const timer = setTimeout(skip, SPLASH_MS);
		window.addEventListener("keydown", skip, { once: true });
		window.addEventListener("pointerdown", skip, { once: true });
		return () => {
			clearTimeout(timer);
			window.removeEventListener("keydown", skip);
			window.removeEventListener("pointerdown", skip);
		};
	}, [phase]);

	// Fires for the returning reader too, so nothing downstream waits on a
	// splash that is never going to run.
	useEffect(() => {
		if (phase === "done") onDone?.();
	}, [phase, onDone]);

	if (phase !== "splash") return null;

	return (
		<div className="intro" aria-hidden="true">
			<div className="intro__mark">
				<img src="/brand/aspire-mark.png" alt="" width={72} height={72} />
			</div>
			<p className="intro__word">Welcome to ASPIRE AI</p>
		</div>
	);
}
