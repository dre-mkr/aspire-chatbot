/**
 * The words the four games share, in one place.
 *
 * They had four vocabularies for the same four ideas. The teaching block was
 * "What it means in ASPIRE terms" in word scramble, "What this means" in true
 * or false, "Why" in Millionaire and "What it means" in Hangman. The escape
 * hatch was "Skip this word", "Not sure — show me the answer", nothing at all,
 * and "Show me the word". A child who plays two of them meets two products.
 *
 * What each game still owns is its own name, its own count line, and the
 * sentence it says about its own move — "Same letters, different order" is
 * about a scramble and belongs to it. Everything below is about ASPIRE.
 */
export const GAME_COPY = {
	/** The teaching block above every explanation. */
	meaning: "What it means",
	/** The teaching block on the summary screen, across the whole set. */
	together: "What ties them together",
	/**
	 * The way out of an item nobody can answer.
	 *
	 * "Not sure — show me the answer" is the kinder sentence and it is twelve
	 * characters too long: in the word scramble it shares a row with a clue
	 * button, a shuffle button and Check it, and it pushed Check it onto a
	 * second line. This says the same thing without implying the reader failed.
	 */
	skip: "Show me the answer",
	/** The way out of the game. */
	leave: "Leave game",
	close: "Close",
	/** Moving on. */
	next: "Next",
	last: "See them all",
	/** The way back to the conversation from a finished set. */
	exit: "Back to chat",
	exitNote: "Ask me to go deeper on any of these whenever you want.",
	/** When a call fails. Names the problem; the button beside it names the way out. */
	failed: "That did not go through.",
	retry: "Try again",
} as const;
