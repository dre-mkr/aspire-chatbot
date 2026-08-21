/** The five ASPIRE personas, as the client needs to know them. */

export type PersonaId =
	| "stella"
	| "orion"
	| "aurora"
	| "nova"
	| "guest";

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
		id: "guest",
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


/**
 * The six guides a reader actually meets, which is not the same as the five keys.
 *
 * `stella` is one persona carrying two voices -- Skye at 5-8, Kaleb at 9-12 --
 * with two cards already written for it (`stella.5-8.md`, `stella.9-12.md`).
 * The picker used to collapse them into one row reading "Skye & Kaleb", so a
 * twelve-year-old could not ask for Kaleb by name even though his card exists.
 *
 * No migration is needed to separate them: the cards are there, and a guide is
 * a persona plus a band. This list is what a picker should render; `PERSONAS`
 * stays as it was for everything that reasons about keys.
 */
/** The bands a guide can answer at. Mirrors `AGE_BANDS` on the service. */
export type AgeBand = "5-8" | "9-12" | "13-15" | "16-18" | "adult";

export interface Guide {
	/** Stable id for this row. Not a persona key. */
	guideId: string;
	persona: PersonaId;
	/** The band this voice answers at, where the persona carries more than one. */
	band?: AgeBand;
	name: string;
	audience: string;
	blurb: string;
}

export const GUIDES: ReadonlyArray<Guide> = [
	{
		guideId: "skye",
		persona: "stella",
		band: "5-8",
		name: "Skye",
		audience: "Ages 5–8",
		blurb: "Gentle and unhurried, in pictures rather than numbers.",
	},
	{
		guideId: "kaleb",
		persona: "stella",
		band: "9-12",
		name: "Kaleb",
		audience: "Ages 9–12",
		blurb: "The older cousin who tells you the truth, and shows the workings.",
	},
	{
		guideId: "zion",
		persona: "orion",
		name: "Zion",
		audience: "Ages 13–18",
		blurb: "Fuller explanations, sourced, and the games that go with them.",
	},
	{
		guideId: "imani",
		persona: "aurora",
		name: "Imani",
		audience: "Parents & guardians",
		blurb: "Straight answers about the programme, in four minutes.",
	},
	{
		guideId: "azuri",
		persona: "nova",
		name: "Azuri",
		audience: "Teachers & educators",
		blurb: "Every figure with its source, and what does not exist yet.",
	},
	{
		guideId: "guest",
		persona: "guest",
		name: "Guest",
		audience: "General",
		blurb: "Answers before it knows who is reading. The default.",
	},
];

/** Which guide a persona-and-band pair resolves to, for showing what is selected. */
export function guideFor(
	persona: PersonaId | null,
	band?: AgeBand | null,
): Guide | null {
	if (!persona) return null;
	const rows = GUIDES.filter((g) => g.persona === persona);
	if (rows.length === 1) return rows[0];
	return rows.find((g) => g.band === band) ?? rows[0] ?? null;
}
