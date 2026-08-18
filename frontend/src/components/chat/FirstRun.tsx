import { useCallback, useEffect, useState } from "react";
import { PERSONAS, type PersonaId } from "#/lib/aspire/personas";

/**
 * The first-visit sequence: a short branded opening, then "who is here?".
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

const KEY = "aspire.intro.v1";

/** ~1.4s in total: long enough to read four words, short enough not to be a gate. */
const SPLASH_MS = 1400;

function seen(): boolean {
	try {
		return window.localStorage.getItem(KEY) === "1";
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

type Phase = "checking" | "splash" | "persona" | "done";

export function FirstRun({
	onChoosePersona,
}: {
	onChoosePersona: (persona: PersonaId) => void;
}) {
	const [phase, setPhase] = useState<Phase>("checking");

	useEffect(() => {
		if (seen()) {
			setPhase("done");
			return;
		}
		// Somebody who has asked for less motion gets the choice, not the show.
		const still = window.matchMedia?.(
			"(prefers-reduced-motion: reduce)",
		)?.matches;
		setPhase(still ? "persona" : "splash");
	}, []);

	// The opening advances on its own, or on any key or pointer press.
	useEffect(() => {
		if (phase !== "splash") return;
		const skip = () => setPhase("persona");
		const timer = setTimeout(skip, SPLASH_MS);
		window.addEventListener("keydown", skip, { once: true });
		window.addEventListener("pointerdown", skip, { once: true });
		return () => {
			clearTimeout(timer);
			window.removeEventListener("keydown", skip);
			window.removeEventListener("pointerdown", skip);
		};
	}, [phase]);

	// Stable, because the Escape effect below depends on it and an identity that
	// changed every render would re-arm the listener on every render.
	const finish = useCallback(() => {
		remember();
		setPhase("done");
	}, []);

	// Escape leaves the persona step without choosing, like any other dialog.
	useEffect(() => {
		if (phase !== "persona") return;
		const onKey = (event: KeyboardEvent) => {
			if (event.key !== "Escape") return;
			event.stopPropagation();
			finish();
		};
		window.addEventListener("keydown", onKey, true);
		return () => window.removeEventListener("keydown", onKey, true);
	}, [phase, finish]);

	function choose(persona: PersonaId) {
		onChoosePersona(persona);
		finish();
	}

	if (phase === "checking" || phase === "done") return null;

	if (phase === "splash") {
		return (
			<div className="intro" aria-hidden="true">
				<div className="intro__mark">
					<img src="/brand/aspire-mark.png" alt="" width={72} height={72} />
				</div>
				<p className="intro__word">Welcome to ASPIRE AI</p>
			</div>
		);
	}

	return (
		<div className="intro intro--ask">
			<div
				className="intro__panel"
				role="dialog"
				aria-modal="true"
				aria-labelledby="intro-title"
			>
				<h2 className="intro__title" id="intro-title">
					Who are you using ASPIRE AI as?
				</h2>
				<p className="intro__sub">
					This changes how ASPIRE AI talks to you — the words it uses, how much
					it explains, and how long an answer is. You can change it whenever you
					like.
				</p>

				<div className="intro__options">
					{PERSONAS.map((persona) => (
						<button
							key={persona.id}
							type="button"
							className="intro__option"
							onClick={() => choose(persona.id)}
						>
							<span className="intro__option-name">{persona.name}</span>
							<span className="intro__option-audience">{persona.audience}</span>
							<span className="intro__option-blurb">{persona.blurb}</span>
						</button>
					))}
				</div>

				<button type="button" className="intro__skip" onClick={finish}>
					Skip for now
				</button>
			</div>
		</div>
	);
}
