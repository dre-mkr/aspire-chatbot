/**
 * The name a reader knows the assistant by, which is not the persona key.
 *
 * Mirrors `backend/app/prompting/personas/names.py`. The rule it implements is
 * stated in `global_rules.py`:
 *
 *     "You are called ASPIRE AI; if a persona below gives you a name, that is
 *      the name the reader knows you by."
 *
 * So "ASPIRE AI" is what the system is called, and the persona's name is what
 * the reader is greeted by. A welcome that says "I'm ASPIRE AI" to somebody who
 * chose Skye is six voices wearing one hat.
 *
 * `stella` is the reason this takes a band. It is one key and two names -- Skye
 * at 5-8, Kaleb at 9-12 -- and the persona alone cannot tell you which.
 *
 * Kept deliberately small and dumb: a lookup, mirrored from the server, that
 * fails to the system name rather than inventing one.
 */

/** Whole-persona labels. Mirrors `NAMES`. */
const NAMES: Record<string, string> = {
	stella: "Skye",
	kaleb: "Kaleb",
	orion: "Zion",
	aurora: "Imani",
	nova: "Azuri",
	guest: "Guest",
	// Pre-rename sessions still carry the old key; the server's `_RENAMED` seam
	// maps it, and a token minted before the rename outlives the deploy.
	everyone: "Guest",
};

/** Labels that belong to one band rather than to the whole persona. Mirrors `BY_BAND`. */
// Empty: Kaleb is `NAMES.kaleb` now, not a band of Stella's. Mirrors the
// server's `BY_BAND`, which emptied for the same reason. Kept, not deleted --
// a genuine two-voice persona would need it again.
const BY_BAND: Record<string, string> = {};

/** What the assistant is called when no persona has given it a name. */
export const SYSTEM_NAME = "ASPIRE AI";

export function displayName(
	persona: string | null | undefined,
	ageBand?: string | null,
): string {
	const key = (persona ?? "").trim().toLowerCase();
	const band = (ageBand ?? "").trim();
	return BY_BAND[`${key}:${band}`] ?? NAMES[key] ?? SYSTEM_NAME;
}
