/** The five ASPIRE personas, as the client needs to know them. */

export type PersonaId =
	| "stella"
	| "orion"
	| "aurora"
	| "nova"
	| "everyone";

export interface Persona {
	id: PersonaId;
	/** The name the assistant answers to. */
	name: string;
	/** Who it is for. The line people actually choose by. */
	audience: string;
	/** One sentence on what changes. Shown under the name in the menu. */
	blurb: string;
}

/** Ordered youngest to oldest, then the two adult roles, then the default. */
export const PERSONAS: ReadonlyArray<Persona> = [
	{
		id: "stella",
		name: "Skye & Kaleb",
		audience: "Ages 5–12",
		blurb: "Skye answers 5 to 8; Kaleb answers 9 to 12, in his own voice.",
	},
	{
		id: "orion",
		name: "Zion",
		audience: "Ages 13–18",
		blurb: "Fuller explanations, and the games that go with them.",
	},
	{
		id: "aurora",
		name: "Imani",
		audience: "Parents & guardians",
		blurb: "Straight answers about the programme, without the activities.",
	},
	{
		id: "nova",
		name: "Azuri",
		audience: "Teachers & educators",
		blurb: "Clear, factual explanations you can teach from.",
	},
	{
		id: "everyone",
		name: "Guest",
		audience: "General",
		blurb: "Balanced answers for a mixed audience. The default.",
	},
] as const;

const BY_ID = new Map(PERSONAS.map((persona) => [persona.id, persona]));

/** Narrows anything to a persona id, or `null`. */
export function asPersonaId(value: unknown): PersonaId | null {
	return typeof value === "string" && BY_ID.has(value as PersonaId)
		? (value as PersonaId)
		: null;
}

export function personaById(id: PersonaId | null): Persona | null {
	return id ? (BY_ID.get(id) ?? null) : null;
}
