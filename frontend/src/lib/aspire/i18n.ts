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
	pledgeOffer: {
		en: "A pledge, if you want it",
		es: "Un compromiso, si lo quieres",
		fr: "Un engagement, si tu veux",
	},
	pledgeMine: { en: "My pledge", es: "Mi compromiso", fr: "Mon engagement" },
	pledgeSealed: { en: "Pledged", es: "Comprometido", fr: "Engagé" },
	towards: { en: "towards", es: "para", fr: "pour" },
	navStories: { en: "Stories", es: "Cuentos", fr: "Histoires" },
	navLearn: { en: "Learn", es: "Aprender", fr: "Apprendre" },
	navGames: { en: "Games", es: "Juegos", fr: "Jeux" },
	navJourney: { en: "My Journey", es: "Mi camino", fr: "Mon parcours" },
	navParents: {
		en: "For Parents & Guardians",
		es: "Para madres, padres y tutores",
		fr: "Pour les parents et tuteurs",
	},
	navEducators: {
		en: "For Educators",
		es: "Para docentes",
		fr: "Pour les enseignants",
	},
	navHowTo: { en: "How to use", es: "Cómo usarlo", fr: "Mode d'emploi" },
	navVideos: { en: "Videos", es: "Vídeos", fr: "Vidéos" },
	seedStory: {
		en: "Can you tell me a story?",
		es: "¿Me cuentas un cuento?",
		fr: "Raconte-moi une histoire.",
	},
	seedLearn: {
		en: "Teach me about saving.",
		es: "Enséñame sobre el ahorro.",
		fr: "Apprends-moi à épargner.",
	},
	seedGame: {
		en: "I'd like to play a game.",
		es: "Quiero jugar un juego.",
		fr: "Je veux jouer à un jeu.",
	},
	play: { en: "Play", es: "Escuchar", fr: "Écouter" },
	playing: { en: "Playing", es: "Reproduciendo", fr: "Lecture" },
	paused: { en: "Paused", es: "En pausa", fr: "En pause" },
	copy: { en: "Copy", es: "Copiar", fr: "Copier" },
	copied: { en: "Copied", es: "Copiado", fr: "Copié" },
	simpler: { en: "Simpler", es: "Más simple", fr: "Plus simple" },
	askAgain: { en: "Ask again", es: "Preguntar otra vez", fr: "Redemander" },
	tryAgain: { en: "Try again", es: "Intentar de nuevo", fr: "Réessayer" },

	// The composer.
	askPlaceholder: {
		en: "Ask me anything, or hold Space to talk",
		es: "Pregúntame lo que quieras, o mantén Espacio para hablar",
		fr: "Demande-moi ce que tu veux, ou maintiens Espace pour parler",
	},
	askPlaceholderTap: {
		en: "Ask me anything, or tap the mic to talk",
		es: "Pregúntame lo que quieras, o toca el micrófono para hablar",
		fr: "Demande-moi ce que tu veux, ou touche le micro pour parler",
	},
	askPlain: {
		en: "Ask me anything...",
		es: "Pregúntame lo que quieras...",
		fr: "Demande-moi ce que tu veux...",
	},
	speakNow: {
		en: "Speak now — your words appear here",
		es: "Habla ahora — tus palabras aparecen aquí",
		fr: "Parle maintenant — tes mots apparaissent ici",
	},
	transcribing: {
		en: "Transcribing…",
		es: "Transcribiendo…",
		fr: "Transcription…",
	},
	explainSimply: {
		en: "Explain it simply",
		es: "Explícalo de forma sencilla",
		fr: "Explique-le simplement",
	},

	// The chat shell.
	newChat: { en: "New chat", es: "Nuevo chat", fr: "Nouvelle discussion" },
	history: { en: "History", es: "Historial", fr: "Historique" },
	today: { en: "Today", es: "Hoy", fr: "Aujourd'hui" },
	videos: { en: "Videos", es: "Videos", fr: "Vidéos" },
	stories: { en: "Stories", es: "Cuentos", fr: "Histoires" },
	learn: { en: "Learn", es: "Aprender", fr: "Apprendre" },
	games: { en: "Games", es: "Juegos", fr: "Jeux" },
	myJourney: { en: "My Journey", es: "Mi camino", fr: "Mon parcours" },
	forParents: {
		en: "For Parents & Guardians",
		es: "Para madres, padres y tutores",
		fr: "Pour les parents et tuteurs",
	},
	forEducators: {
		en: "For Educators",
		es: "Para docentes",
		fr: "Pour les enseignants",
	},
	howToUse: { en: "How to use", es: "Cómo usarlo", fr: "Comment l'utiliser" },
	notSignedIn: {
		en: "Not signed in",
		es: "Sin sesión iniciada",
		fr: "Non connecté",
	},
	signInToKeep: {
		en: "Sign in to keep your chats",
		es: "Inicia sesión para guardar tus chats",
		fr: "Connecte-toi pour garder tes discussions",
	},
	canMakeMistakes: {
		en: "ASPIRE AI can make mistakes.",
		es: "ASPIRE AI puede cometer errores.",
		fr: "ASPIRE AI peut se tromper.",
	},
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
