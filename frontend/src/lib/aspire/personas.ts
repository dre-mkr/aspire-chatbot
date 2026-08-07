/**
 * The four ASPIRE personas, as the client needs to know them.
 *
 * The backend has supported these all along — a system prompt per persona, a
 * per-persona ElevenLabs voice at three languages each, and `persona_bands` on
 * every game item deciding which questions a given audience is served. None of
 * it was reachable: `AspireChat` accepted a `persona` prop, was called in
 * exactly one place with no props, and so sent `null` on every request for
 * every user. Every child got the same undifferentiated assistant, in a product
 * whose premise is age-appropriate help for ages 5 to 18.
 *
 * The ids are the wire contract and must match `Persona` in
 * `backend/app/games/models.py` and `backend/app/voice/registry.py`.
 *
 * `null` stays meaningful and stays the default. The backend treats an unknown
 * persona as permissive rather than as any particular one — see the engine's
 * note on `PLAYING_PERSONAS` — so "not chosen" is a real state and not a
 * missing value to be defaulted away.
 */

export type PersonaId = "stella" | "orion" | "aurora" | "nova";

export interface Persona {
	id: PersonaId;
	/** The name the assistant answers to. */
	name: string;
	/** Who it is for. The line people actually choose by. */
	audience: string;
	/** One sentence on what changes. Shown under the name in the menu. */
	blurb: string;
}

/**
 * Ordered youngest to oldest, then the two adult roles.
 *
 * That order is the choosing order: this is picked by a person locating
 * themselves, and age is what they locate themselves by first.
 *
 * ## The age ranges are the access matrix's, not marketing's (P15-017)
 *
 * These read "Ages 5–12" and "Ages 13–18" because that is what
 * `backend/app/graph/access.py` actually grants: Stella is granted at 5-8 and
 * 9-12, Orion at 13-15 and 16-18. They used to say "5–9" and "10–18", which
 * described a product that does not exist — `allowed_agents("orion", "9-12", …)`
 * returns `[]`, a hard 403.
 *
 * Stella used to cover every band, including `adult`. She no longer does, and
 * this line did not have to change for it: "Ages 5–12" was already what the
 * menu promised and is now what the matrix grants. An adult who picks Stella is
 * refused by `account._narrowing` and kept on their derived persona, which is
 * the outcome that lets a parent still reach registration — being narrowed INTO
 * Stella was how they used to lose it.
 *
 * That mismatch already cost the 9-12 band the whole product once: the backend's
 * default-persona table had been built from this copy rather than from the
 * matrix, so every ten-to-twelve-year-old was issued an Orion token the matrix
 * denies and `guard` halted the turn. The table was resolved towards the matrix,
 * because the matrix is the security control and this is a line in a menu.
 *
 * So this line follows the matrix, and the two must be changed together. An
 * eleven-year-old choosing Orion here is refused server-side by `_narrowing`
 * and left on Stella — no longer a lockout, but still a menu offering something
 * it cannot deliver.
 */
export const PERSONAS: ReadonlyArray<Persona> = [
	{
		id: "stella",
		name: "Stella",
		audience: "Ages 5–12",
		blurb: "Short answers, simple words, and a slower reading voice.",
	},
	{
		id: "orion",
		name: "Orion",
		audience: "Ages 13–18",
		blurb: "Fuller explanations, and the games that go with them.",
	},
	{
		id: "aurora",
		name: "Aurora",
		audience: "Parents & guardians",
		blurb: "Straight answers about the programme, without the activities.",
	},
	{
		id: "nova",
		name: "Nova",
		audience: "Teachers & educators",
		blurb: "Clear, factual explanations you can teach from.",
	},
] as const;

const BY_ID = new Map(PERSONAS.map((persona) => [persona.id, persona]));

/**
 * Narrows anything to a persona id, or `null`.
 *
 * Used on the URL search param, which is user-editable and therefore untrusted:
 * `?persona=nonsense` must land on "not chosen" rather than being sent to the
 * service as a persona it has never heard of.
 */
export function asPersonaId(value: unknown): PersonaId | null {
	return typeof value === "string" && BY_ID.has(value as PersonaId)
		? (value as PersonaId)
		: null;
}

export function personaById(id: PersonaId | null): Persona | null {
	return id ? (BY_ID.get(id) ?? null) : null;
}
