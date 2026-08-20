/**
 * One table for what a game IS, replacing four places that each knew two games.
 *
 * Before this there was a two-way ternary in `stream.ts` picking the prompt
 * kind, another in `Transcript.tsx` picking the component, a two-entry lookup in
 * `ChatScreen.tsx` mapping directive names to engine names, and a two-entry
 * `GAME_TITLES`. Every one of them fell through to word scramble for anything
 * it did not recognise — which is why `millionaire`, already named in the
 * directive union and in the intent regex with no implementation behind it,
 * rendered as a scramble and then 422'd.
 *
 * A game added here and nowhere else still will not render; but a game MISSED
 * here now shows as unknown rather than silently becoming a different game.
 */

/** What the server's `game` directive may say. */
export type GameName = "scramble" | "true_false" | "millionaire" | "hangman";

/** How the engine spells the same game. */
export type EngineGameType =
	| "word_scramble"
	| "true_false"
	| "millionaire"
	| "hangman";

/** How an item is put to the player; picks the component. */
export type GamePromptKind = "scramble" | "statement" | "quiz" | "hangman";

interface GameKind {
	engine: EngineGameType;
	prompt: GamePromptKind;
	/** What the rail calls a conversation that opened with this game. */
	titles: { en: string; es: string; fr: string };
}

const GAMES: Record<GameName, GameKind> = {
	scramble: {
		engine: "word_scramble",
		prompt: "scramble",
		titles: {
			en: "Word scramble practice",
			es: "Práctica de palabras revueltas",
			fr: "Entraînement de mots mêlés",
		},
	},
	true_false: {
		engine: "true_false",
		prompt: "statement",
		titles: {
			en: "True or false round",
			es: "Ronda de verdadero o falso",
			fr: "Tour de vrai ou faux",
		},
	},
	millionaire: {
		engine: "millionaire",
		prompt: "quiz",
		titles: {
			en: "Millionaire round",
			es: "Ronda de millonario",
			fr: "Tour du millionnaire",
		},
	},
	hangman: {
		engine: "hangman",
		prompt: "hangman",
		titles: {
			en: "Hangman round",
			es: "Ronda del ahorcado",
			fr: "Tour du pendu",
		},
	},
};

/** The engine's name for a directive's game, or the name itself if unknown. */
export function engineGameType(name: string): string {
	return GAMES[name as GameName]?.engine ?? name;
}

/** Which component renders this game, from the directive's name. */
export function promptKindFor(name: string): GamePromptKind {
	// `scramble` rather than a throw: an unknown game from a newer server should
	// degrade to a card, not to a blank turn. What it must NOT do is pretend to
	// be a specific other game, which is why every known one is listed above.
	return GAMES[name as GameName]?.prompt ?? "scramble";
}

/** What to call a conversation that opened with this game. */
export function gameTitleFor(
	engineType: string,
	language: string,
): string | null {
	const entry = Object.values(GAMES).find((g) => g.engine === engineType);
	if (!entry) return null;
	return entry.titles[language as keyof GameKind["titles"]] ?? entry.titles.en;
}

/** Human-readable, for a card heading. */
export function displayNameFor(name: string): string {
	if (name === "millionaire") return "Who Wants to Be a Millionaire?";
	return name.replace(/_/g, " ");
}
