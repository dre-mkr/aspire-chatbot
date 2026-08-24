/**
 * The app's own words, in the three languages the product ships.
 *
 * WHAT THIS IS FOR. The EN/ES/FR selector changed the ANSWER and nothing else,
 * because every string in the interface was written in English at the point it
 * is rendered. A reader who switched to Spanish got a Spanish answer, Spanish
 * follow-up chips and a Spanish source panel sitting under an English heading
 * reading "Where this came from" -- which is the one part of the reply the
 * product wrote itself.
 *
 * WHAT IT IS NOT. Not an i18n framework, and deliberately not: there was none
 * here, and adding one is a decision about 28 components and about 144 strings,
 * not something to slip in beside a bug fix. This covers the strings attached
 * to an ANSWER -- the source panel, the action row -- because those sit inside
 * the bubble and read as broken next to translated prose. The navigation and
 * the settings are still English, and still want doing.
 *
 * WHERE THE LANGUAGE COMES FROM. The same preferences the voice layer reads, so
 * there is one answer to "what language is this reader in" rather than two that
 * can disagree. No provider and no prop-drilling through the tree.
 */

export type Locale = "en" | "es" | "fr";

const PREFS_KEY = "aspire.voice.prefs.v1";

/** Every phrase this module can say, keyed by what it means. */
const COPY = {
	sources: {
		en: "Where this came from",
		es: "De dónde viene esto",
		fr: "D'où cela vient",
	},
	play: { en: "Play", es: "Escuchar", fr: "Écouter" },
	playing: { en: "Playing", es: "Reproduciendo", fr: "Lecture" },
	paused: { en: "Paused", es: "En pausa", fr: "En pause" },
	copy: { en: "Copy", es: "Copiar", fr: "Copier" },
	copied: { en: "Copied", es: "Copiado", fr: "Copié" },
	simpler: { en: "Simpler", es: "Más simple", fr: "Plus simple" },
	askAgain: { en: "Ask again", es: "Preguntar otra vez", fr: "Redemander" },
	tryAgain: { en: "Try again", es: "Intentar de nuevo", fr: "Réessayer" },
} as const;

export type Phrase = keyof typeof COPY;

/**
 * The reader's language, or English.
 *
 * Reads storage on every call rather than caching. It is a JSON parse of one
 * small object against a render that is already doing more than that, and a
 * cache here would go stale the moment the selector changed.
 */
export function currentLocale(): Locale {
	if (typeof window === "undefined") return "en";
	try {
		const raw = window.localStorage.getItem(PREFS_KEY);
		if (!raw) return "en";
		const parsed = JSON.parse(raw) as { language?: string };
		return (["en", "es", "fr"] as const).includes(parsed.language as Locale)
			? (parsed.language as Locale)
			: "en";
	} catch {
		return "en";
	}
}

/**
 * One phrase, in the reader's language.
 *
 * Falls back to English rather than to the key: a missing translation should
 * read as a sentence somebody understands, never as `askAgain`.
 */
export function say(phrase: Phrase, locale: Locale = currentLocale()): string {
	return COPY[phrase][locale] ?? COPY[phrase].en;
}
