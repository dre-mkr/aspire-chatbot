/** Whether this browser has been asked who is reading. */

const STORAGE_KEY = "aspire.guide-chosen.v1";

/**
 * The key the removed in-page persona step wrote.
 *
 * That step asked this same question, so a browser carrying it has already been
 * asked and must not be asked again. Nothing writes it any more — the opening
 * that used to share it has its own key now (`FirstRun`), which is what keeps
 * "has seen the opening" from being mistaken for "has answered the question".
 */
const LEGACY_KEY = "aspire.intro.v1";

function canStore() {
	// Imported during SSR, where there is no window at all.
	return typeof window !== "undefined" && !!window.localStorage;
}

/**
 * A preference, not a transcript.
 *
 * Kept per-browser rather than per-account on purpose: it records that the
 * question has been put, and putting it twice to the same person on the same
 * device is the annoyance worth avoiding. Nothing here is private, so unlike
 * `aspire.conversations.v1` it does not need clearing when an identity ends.
 */
export function guideAsked(): boolean {
	if (!canStore()) return true; // Never block the app on storage being absent.
	try {
		return (
			window.localStorage.getItem(STORAGE_KEY) === "1" ||
			window.localStorage.getItem(LEGACY_KEY) === "1"
		);
	} catch {
		return true;
	}
}

export function rememberGuideAsked() {
	if (!canStore()) return;
	try {
		window.localStorage.setItem(STORAGE_KEY, "1");
	} catch {
		// A quota or a private window must not break the chooser.
	}
}
