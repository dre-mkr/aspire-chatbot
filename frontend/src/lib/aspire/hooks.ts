/**
 * THE ASPIRE HOOK TABLE — every guide's opening line, in every language.
 *
 * See `docs/HOOK_SPINE.md` for the rule this table exists to obey. In short:
 *
 *     ASPIRE may always personalise DOWNWARD to what it knows.
 *     It must never personalise UPWARD by guessing.
 *
 * A hook fires before the reader has said anything, so it is pinned at LEVEL 1
 * of the personalisation ladder: the audience is known, the relationship is not.
 * Choosing "Parents & guardians" does not make someone a parent -- they may be a
 * grandmother, an aunt, a foster carer, or asking on behalf of a friend. Choosing
 * "Teachers & educators" does not make someone a classroom teacher.
 *
 * Which is why every adult line here is CONDITIONAL. "If you're supporting a
 * young person" is true of all of them and asserts nothing. "You're building
 * their future" reads warmer and quietly asserts a child.
 *
 * The guide's own NAME is the one specific thing a hook may always use, because
 * it is a fact about the guide rather than a claim about the reader. It carries
 * the accent styling for the same reason.
 */

export type HookLanguage = "en" | "es" | "fr";

export interface Hook {
	/** Set plain, in the display face. */
	lead: string;
	/** Set in the italic gradient. Always the guide's name. */
	accent: string;
	emoji: string;
	line: string;
}

interface HookPair {
	first: Hook;
	returning: Hook;
}

/**
 * GRAMMATICAL GENDER IS PART OF THE LADDER, and this is not a translation
 * quibble.
 *
 * Spanish «bienvenido» / «bienvenida» agrees with the person being welcomed, so
 * a literal "Welcome!" would assign the reader a gender ASPIRE does not know.
 * That is personalising upward by guessing, in grammar rather than in content,
 * and the rule does not care which. So Spanish opens «¡Hola! Soy …», which is
 * warm, idiomatic and neutral.
 *
 * French «Bienvenue» agrees with nothing, so French keeps the literal form.
 *
 * The second axis is address. French uses «tu» for the children's and teen
 * bands and «vous» for the adult guides; Spanish uses «tú» throughout, which is
 * the Caribbean register. Azuri could take «usted» if the client would rather
 * be formal with professionals -- that is a decision, not an oversight.
 */
const HOOKS: Record<HookLanguage, Record<string, HookPair>> = {
	en: {
		stella: {
			first: {
				lead: "Welcome! I'm ",
				accent: "Skye.",
				emoji: "✨",
				line: "There are lots of things about money we can discover together. What should we explore today?",
			},
			returning: {
				lead: "Welcome back! It's ",
				accent: "Skye.",
				emoji: "✨",
				line: "What should we find out today?",
			},
		},
		kaleb: {
			first: {
				lead: "Welcome! I'm ",
				accent: "Kaleb.",
				emoji: "\u{1F680}",
				line: "Money, ASPIRE, saving, investing — whatever you're trying to understand. What do you want to work out?",
			},
			returning: {
				lead: "Welcome back! It's ",
				accent: "Kaleb.",
				emoji: "\u{1F680}",
				line: "What are we working out this time?",
			},
		},
		orion: {
			first: {
				lead: "Welcome! I'm ",
				accent: "Zion.",
				emoji: "✨",
				line: "I can help with ASPIRE, money questions, planning, and the facts behind the numbers. What do you need to get clear on?",
			},
			returning: {
				lead: "Welcome back! It's ",
				accent: "Zion.",
				emoji: "✨",
				line: "What do you need to get clear on today?",
			},
		},
		aurora: {
			first: {
				lead: "Welcome! I'm ",
				accent: "Imani.",
				emoji: "\u{1F331}",
				line: "If you're supporting a young person through ASPIRE, I can help you understand the programme, their learning, and what comes next. What can I help you with today?",
			},
			returning: {
				lead: "Welcome back! It's ",
				accent: "Imani.",
				emoji: "\u{1F331}",
				line: "Where would you like to pick up?",
			},
		},
		nova: {
			first: {
				lead: "Welcome! I'm ",
				accent: "Azuri.",
				emoji: "\u{1F4DA}",
				line: "If you're helping young people learn, I can give you accurate, sourced information and practical ASPIRE support. What would be useful today?",
			},
			returning: {
				lead: "Welcome back! It's ",
				accent: "Azuri.",
				emoji: "\u{1F4DA}",
				line: "What would be useful today?",
			},
		},
		guest: {
			first: {
				lead: "Welcome! I'm ",
				accent: "ASPIRE AI.",
				emoji: "✨",
				line: "What would you like to explore or learn today?",
			},
			returning: {
				lead: "Welcome back! It's ",
				accent: "ASPIRE AI.",
				emoji: "✨",
				line: "What would you like to explore today?",
			},
		},
	},

	es: {
		stella: {
			first: {
				lead: "¡Hola! Soy ",
				accent: "Skye.",
				emoji: "✨",
				line: "Hay muchas cosas sobre el dinero que podemos descubrir juntos. ¿Qué exploramos hoy?",
			},
			returning: {
				lead: "¡Hola otra vez! Soy ",
				accent: "Skye.",
				emoji: "✨",
				line: "¿Qué descubrimos hoy?",
			},
		},
		kaleb: {
			first: {
				lead: "¡Hola! Soy ",
				accent: "Kaleb.",
				emoji: "\u{1F680}",
				line: "Dinero, ASPIRE, ahorrar, invertir — lo que quieras entender. ¿Qué quieres resolver?",
			},
			returning: {
				lead: "¡Hola otra vez! Soy ",
				accent: "Kaleb.",
				emoji: "\u{1F680}",
				line: "¿Qué resolvemos esta vez?",
			},
		},
		orion: {
			first: {
				lead: "Hola. Soy ",
				accent: "Zion.",
				emoji: "✨",
				line: "Puedo ayudarte con ASPIRE, preguntas de dinero, planificación y los datos detrás de las cifras. ¿Qué necesitas aclarar?",
			},
			returning: {
				lead: "Hola de nuevo. Soy ",
				accent: "Zion.",
				emoji: "✨",
				line: "¿Qué necesitas aclarar hoy?",
			},
		},
		aurora: {
			first: {
				lead: "¡Hola! Soy ",
				accent: "Imani.",
				emoji: "\u{1F331}",
				line: "Si estás apoyando a una persona joven a través de ASPIRE, puedo ayudarte a entender el programa, su aprendizaje y lo que sigue. ¿En qué te puedo ayudar hoy?",
			},
			returning: {
				lead: "¡Hola otra vez! Soy ",
				accent: "Imani.",
				emoji: "\u{1F331}",
				line: "¿Por dónde quieres continuar?",
			},
		},
		nova: {
			first: {
				lead: "Hola. Soy ",
				accent: "Azuri.",
				emoji: "\u{1F4DA}",
				line: "Si estás ayudando a jóvenes a aprender, puedo darte información precisa y con fuentes, y apoyo práctico sobre ASPIRE. ¿Qué te sería útil hoy?",
			},
			returning: {
				lead: "Hola de nuevo. Soy ",
				accent: "Azuri.",
				emoji: "\u{1F4DA}",
				line: "¿Qué te sería útil hoy?",
			},
		},
		guest: {
			first: {
				lead: "¡Hola! Soy ",
				accent: "ASPIRE AI.",
				emoji: "✨",
				line: "¿Qué te gustaría explorar o aprender hoy?",
			},
			returning: {
				lead: "¡Hola otra vez! Soy ",
				accent: "ASPIRE AI.",
				emoji: "✨",
				line: "¿Qué te gustaría explorar hoy?",
			},
		},
	},

	fr: {
		stella: {
			first: {
				lead: "Bienvenue ! Je suis ",
				accent: "Skye.",
				emoji: "✨",
				line: "Il y a plein de choses à découvrir ensemble sur l'argent. Qu'est-ce qu'on explore aujourd'hui ?",
			},
			returning: {
				lead: "Te revoilà ! Je suis ",
				accent: "Skye.",
				emoji: "✨",
				line: "Qu'est-ce qu'on découvre aujourd'hui ?",
			},
		},
		kaleb: {
			first: {
				lead: "Bienvenue ! Je suis ",
				accent: "Kaleb.",
				emoji: "\u{1F680}",
				line: "L'argent, ASPIRE, l'épargne, les placements — tout ce que tu veux comprendre. Qu'est-ce qu'on démêle ?",
			},
			returning: {
				lead: "Te revoilà ! Je suis ",
				accent: "Kaleb.",
				emoji: "\u{1F680}",
				line: "On démêle quoi cette fois ?",
			},
		},
		orion: {
			first: {
				lead: "Bonjour. Je suis ",
				accent: "Zion.",
				emoji: "✨",
				line: "Je peux t'aider sur ASPIRE, les questions d'argent, la planification et les chiffres et leurs sources. Qu'est-ce que tu veux tirer au clair ?",
			},
			returning: {
				lead: "Rebonjour. Je suis ",
				accent: "Zion.",
				emoji: "✨",
				line: "Qu'est-ce que tu veux tirer au clair aujourd'hui ?",
			},
		},
		aurora: {
			first: {
				lead: "Bienvenue ! Je suis ",
				accent: "Imani.",
				emoji: "\u{1F331}",
				line: "Si vous accompagnez un ou une jeune dans ASPIRE, je peux vous aider à comprendre le programme, ses apprentissages et la suite. Que puis-je faire pour vous aujourd'hui ?",
			},
			returning: {
				lead: "Bon retour ! Je suis ",
				accent: "Imani.",
				emoji: "\u{1F331}",
				line: "Par où souhaitez-vous reprendre ?",
			},
		},
		nova: {
			first: {
				lead: "Bienvenue ! Je suis ",
				accent: "Azuri.",
				emoji: "\u{1F4DA}",
				line: "Si vous aidez des jeunes à apprendre, je peux vous fournir des informations exactes et sourcées, ainsi qu'un appui concret sur ASPIRE. Qu'est-ce qui vous serait utile aujourd'hui ?",
			},
			returning: {
				lead: "Bon retour ! Je suis ",
				accent: "Azuri.",
				emoji: "\u{1F4DA}",
				line: "Qu'est-ce qui vous serait utile aujourd'hui ?",
			},
		},
		guest: {
			first: {
				lead: "Bienvenue ! Je suis ",
				accent: "ASPIRE AI.",
				emoji: "✨",
				line: "Que souhaitez-vous explorer ou apprendre aujourd'hui ?",
			},
			returning: {
				lead: "Bon retour ! Je suis ",
				accent: "ASPIRE AI.",
				emoji: "✨",
				line: "Que souhaitez-vous explorer aujourd'hui ?",
			},
		},
	},
};

/**
 * The reader's given name, ONLY when the account actually holds one.
 *
 * THE LADDER, APPLIED TO NAMES. A display name is not a first name; it is
 * whatever a person typed into a box, and splitting it on whitespace and
 * greeting the first token is a guess. Real values this has to survive:
 *
 *     "T. Onu"                   -> "Welcome back, T.!"        an initial
 *     "tellyonu"                 -> "Welcome back, tellyonu!"  an email prefix
 *     "MINISTRY OF SOCIAL DEV…"  -> "Welcome back, MINISTRY!"  an organisation
 *
 * Each of those is the product claiming to know somebody it does not, which is
 * exactly what `docs/HOOK_SPINE.md` forbids -- and a greeting is the worst
 * place to be wrong, because it is the first thing read and it is addressed to
 * them personally.
 *
 * So the token has to look like a name a person would answer to. Anything else
 * returns null, the neutral "Welcome back!" stands, and nothing is lost: the
 * greeting was warm before the name was ever added.
 */
export function readerGivenName(
	displayName: string | null | undefined,
): string | null {
	const first = (displayName ?? "").trim().split(/\s+/)[0] ?? "";
	if (first.length < 2 || first.length > 20) return null;
	// An initial. "T." is how a name is abbreviated, not how it is said aloud.
	if (first.endsWith(".")) return null;
	// An address or a handle, not a name.
	if (/[@_\d]/.test(first)) return null;
	// Shouting, or an acronym: an organisation account rather than a person.
	if (first === first.toUpperCase() && first.length > 3) return null;
	// Letters, apostrophes and hyphens only -- O'Brien and Anne-Marie are names.
	if (!/^[\p{L}][\p{L}'\u2019-]*$/u.test(first)) return null;
	return first;
}

/**
 * The hook for this guide, in this language.
 *
 * Falls back to English rather than to nothing, and to Guest rather than to
 * English's first row: a missing translation should read as untranslated, never
 * as the wrong guide talking.
 */
export function hookFor(
	persona: string | null | undefined,
	language: HookLanguage = "en",
	priorConversations = 0,
	/**
	 * The reader's first name, when the account knows it.
	 *
	 * Used ONLY on the returning line, and only when it is actually known --
	 * this is the ladder again. A name is the strongest possible signal that
	 * the product remembers you, and inventing one, or guessing at a display
	 * name that is really an email prefix, is worse than the neutral greeting.
	 */
	name: string | null = null,
): Hook {
	const key = (persona ?? "").trim().toLowerCase() || "guest";
	const table = HOOKS[language] ?? HOOKS.en;
	const pair = table[key] ?? HOOKS.en[key] ?? table.guest ?? HOOKS.en.guest;
	if (priorConversations <= 0) return pair.first;

	const back = pair.returning;
	if (!name) return back;
	// The name joins the GREETING clause, not the guide's introduction:
	//
	//   "Welcome back! It's "   -> "Welcome back, Telly! It's "
	//   "Hola de nuevo. Soy "   -> "Hola de nuevo, Telly. Soy "
	//   "Bon retour ! Je suis " -> "Bon retour, Telly ! Je suis "
	//
	// Inserting at the FIRST sentence-ending punctuation is what makes that work
	// in all three at once, and it puts the name before French's space-before-!
	// rather than after it. Appending to the end of the lead instead produced
	// "Welcome back! It's, Telly Azuri." -- correct code, nonsense sentence.
	//
	// A lead with no terminal punctuation keeps the neutral greeting: Kaleb's
	// "Back for " carries its question mark in the accent, and a name wedged in
	// by force would read worse than no name at all.
	const named = back.lead.replace(/^(.*?)(\s*[.!?])/, `$1, ${name}$2`);
	return { ...back, lead: named };
}

/**
 * The tagline, per language.
 *
 * Brand copy rather than persona copy, so it sits outside the guide table: all
 * six guides say the same three words. They are three separate fields because
 * each is coloured individually and splitting a translated sentence on
 * punctuation would break the first time a language punctuated differently.
 *
 * French takes «vous» here even though Skye and Kaleb use «tu» in their own
 * lines: this is the product speaking, not the guide.
 */
export const TAGLINES: Record<
	HookLanguage,
	{ ask: string; play: string; explore: string; rest: string }
> = {
	en: {
		ask: "Ask.",
		play: "Play.",
		explore: "Explore.",
		rest: "Build your money future.",
	},
	es: {
		ask: "Pregunta.",
		play: "Juega.",
		explore: "Explora.",
		rest: "Construye tu futuro financiero.",
	},
	fr: {
		ask: "Demandez.",
		play: "Jouez.",
		explore: "Explorez.",
		rest: "Construisez votre avenir financier.",
	},
};

/** The languages a hook exists in, for the switcher. */
export const HOOK_LANGUAGES: ReadonlyArray<{
	id: HookLanguage;
	label: string;
	/** What a speaker of that language calls it. */
	native: string;
}> = [
	{ id: "en", label: "EN", native: "English" },
	{ id: "es", label: "ES", native: "Español" },
	{ id: "fr", label: "FR", native: "Français" },
];
