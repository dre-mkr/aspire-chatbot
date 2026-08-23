/** The six ASPIRE personas, as the client needs to know them. */

export type PersonaId =
	| "stella"
	| "kaleb"
	| "orion"
	| "aurora"
	| "nova"
	| "guest";

/**
 * A persona key and the name it answers to, and nothing else.
 *
 * It also carried `audience` and `blurb`, which duplicated `GUIDES` and had
 * drifted from it on three of the six rows — so the answer to "what does Imani
 * do?" depended on which table a surface happened to read. Nothing reads these
 * from here any more; `GUIDES` is where a guide is described.
 */
export interface Persona {
	id: PersonaId;
	/** The name the assistant answers to. */
	name: string;
}

/** Ordered youngest to oldest, then the two adult roles, then the default. */
export const PERSONAS: ReadonlyArray<Persona> = [
	{
		id: "stella",
		name: "Skye",
	},
	{
		// A key of his own, not a band of Stella's. He used to share `stella`
		// and appear here as half of "Skye & Kaleb · Ages 5–12", which is a row
		// no reader ever chose -- they chose a person. The server splits them
		// now, so this list can too.
		id: "kaleb",
		name: "Kaleb",
	},
	{
		id: "orion",
		name: "Zion",
	},
	{
		id: "aurora",
		name: "Imani",
	},
	{
		id: "nova",
		name: "Azuri",
	},
	{
		id: "guest",
		name: "Guest",
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
	/** Who it is for, in full: "Parents & guardians". */
	audience: string;
	/**
	 * The same thing, short enough for a chip.
	 *
	 * "Parents & guardians" and "Teachers & educators" are twice the length of
	 * the three age ranges, and they were what forced the guide row's label down
	 * to 8.5px so they would fit. The full form is still what a screen reader
	 * hears and what the composer menu prints; this is for the chip.
	 */
	pill: string;
	/** One sentence on what changes. The composer menu and the help panel. */
	blurb: string;
	/**
	 * The same promise, pitched at a family choosing rather than at a menu.
	 *
	 * Kept as its own field, next to `blurb`, rather than in the chooser: the
	 * two used to live in different files and had drifted into saying different
	 * things about the same guide. Side by side they can be read together.
	 */
	chooserBlurb: string;
	/** Shown on hover and focus in the guide row. */
	hint: string;
	/** Spoken instead of the label, so a tap says what it does and who it is for. */
	spoken: string;
	/** The colour this guide is remembered by: the avatar ring. */
	colour: string;
	/**
	 * The chip, tinted from the ring — and measured against it.
	 *
	 * Four of the five inks were the ring colour itself, which is chosen to
	 * read against WHITE at avatar size, not against a 10% tint at 10px:
	 * Zion's gold measured 2.71:1 on its own chip, Kaleb's blue 3.48:1, Skye's
	 * 3.80:1, Azuri's 3.76:1. The chip is the thing that answers "which one is
	 * mine?" before a reader knows any of the names, so four fifths of it was
	 * unreadable. The fills are unchanged; only the inks moved, and every pair
	 * now clears 5:1.
	 */
	pillBg: string;
	pillFg: string;
}

/**
 * ONE TABLE. There were five.
 *
 * `PERSONAS` carried a name, an audience and a blurb; `GUIDES` carried the same
 * three and disagreed with it on three of the six blurbs. `GuideSelector` kept
 * four more maps of its own — ring colour, chip colours, hover hint, spoken
 * label. `LandingScreen` kept a sixth copy of the ring colours. And
 * `GuideChooser` kept a list that predated the Skye/Kaleb split entirely: it
 * offered four guides where the rest of the product offers five, and told a
 * reader Skye was for "Ages 5–12" while the row beside it said 5–8 and gave
 * 9–12 to Kaleb. An eleven-year-old choosing in the chooser and an
 * eleven-year-old choosing on the landing page got different guides.
 *
 * Everything a surface needs to render a guide is here, once.
 */
export const GUIDES: ReadonlyArray<Guide> = [
	{
		guideId: "skye",
		persona: "stella",
		band: "5-8",
		name: "Skye",
		audience: "Ages 5–8",
		pill: "Ages 5–8",
		blurb: "Gentle and unhurried, in pictures rather than numbers.",
		chooserBlurb: "Simple words, short answers and easy explanations.",
		hint: "Simple, gentle explanations and playful learning.",
		spoken: "Choose Skye, the ASPIRE guide for ages 5 to 8",
		colour: "#c22f99",
		pillBg: "#fce5f3",
		pillFg: "#ab1f71",
	},
	{
		guideId: "kaleb",
		persona: "kaleb",
		band: "9-12",
		name: "Kaleb",
		audience: "Ages 9–12",
		pill: "Ages 9–12",
		blurb: "The older cousin who tells you the truth, and shows the workings.",
		chooserBlurb: "Straight answers, real money words and challenges.",
		hint: "Straight answers, real money words and challenges.",
		spoken: "Choose Kaleb, the ASPIRE guide for ages 9 to 12",
		colour: "#2f7fe9",
		pillBg: "#e8f2ff",
		pillFg: "#1a5fbf",
	},
	{
		guideId: "zion",
		persona: "orion",
		name: "Zion",
		audience: "Ages 13–18",
		pill: "Ages 13–18",
		blurb: "Fuller explanations, sourced, and the games that go with them.",
		chooserBlurb: "Fuller explanations, games, challenges and activities.",
		hint: "Direct, practical and sourced guidance.",
		spoken: "Choose Zion, the ASPIRE guide for ages 13 to 18",
		colour: "#c88710",
		pillBg: "#fff1d5",
		pillFg: "#8a5a00",
	},
	{
		guideId: "imani",
		persona: "aurora",
		name: "Imani",
		audience: "Parents & guardians",
		pill: "Parents",
		blurb: "Straight answers about the programme, without the activities.",
		chooserBlurb:
			"Practical answers about the programme and your child's learning.",
		hint: "Clear answers and next steps for families.",
		spoken: "Choose Imani, the ASPIRE guide for parents and guardians",
		colour: "#5c3aae",
		pillBg: "#eee6ff",
		pillFg: "#6435b6",
	},
	{
		guideId: "azuri",
		persona: "nova",
		name: "Azuri",
		audience: "Teachers & educators",
		pill: "Teachers",
		blurb: "Every figure with its source, and what does not exist yet.",
		chooserBlurb:
			"Clear explanations and teaching support you can use with learners.",
		hint: "Precise, sourced support for educators.",
		spoken: "Choose Azuri, the ASPIRE guide for teachers and educators",
		colour: "#098b76",
		pillBg: "#ddf7f1",
		pillFg: "#076654",
	},
	{
		guideId: "guest",
		persona: "guest",
		name: "Guest",
		audience: "General",
		pill: "General",
		blurb: "Answers before it knows who is reading. The default.",
		chooserBlurb: "Balanced answers for a mixed audience.",
		hint: "Balanced answers for a mixed audience.",
		spoken: "Continue as a guest",
		colour: "#6b42a1",
		pillBg: "#eee6ff",
		pillFg: "#6435b6",
	},
];

/** The five a reader chooses between. Guest is the state before choosing. */
export const CHOOSABLE_GUIDES = GUIDES.filter((g) => g.guideId !== "guest");

/** By guide id, for the surfaces that hold one. */
export function guideById(guideId: string | null): Guide | null {
	if (!guideId) return null;
	return GUIDES.find((g) => g.guideId === guideId) ?? null;
}

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
