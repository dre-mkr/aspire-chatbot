/**
 * What a conversation looks like before anybody has said anything.
 *
 * There was no empty state at all: a new thread rendered a bare transcript, so
 * the reader met a blank room and a text box. This is the room saying hello.
 *
 * THE GREETING IS THE PERSONA'S, NOT THE SYSTEM'S. `global_rules.py` settles
 * it -- "You are called ASPIRE AI; if a persona below gives you a name, that is
 * the name the reader knows you by." A reader who chose Skye is greeted by
 * Skye. Hardcoding "I'm ASPIRE AI" would be one bot wearing six hats.
 *
 * EVERY CARD HERE WORKS FOR EVERY READER. That is the whole rule, and it cost
 * a backend change to make true rather than a gate to fake.
 *
 * Games used to RAISE `PersonaNotEligible` for Imani and Azuri, so a challenge
 * card shown to them was a button that could not work. `PLAYING_PERSONAS` now
 * covers every persona, and `_CONTENT_BANK` serves the adult voices the 13-18
 * material, since neither has authored sets of its own. Restraint about
 * OFFERING moved into the persona cards, which can say "never raise this
 * unprompted" -- a different thing from "you may not have this".
 *
 * Videos need a different route for adults, and this is not a gate either.
 * `catalog.py`: "Both can still reach every video from the Videos panel, which
 * is browsing rather than being offered something unasked." `for_persona`
 * governs what the assistant OFFERS mid-answer; `/api/videos` is deliberately
 * unfiltered. So asking "can I watch a story?" as a parent runs through the
 * offer path and comes back declined, while the panel serves them fine --
 * which is why the adult card OPENS THE PANEL rather than asking. Same films,
 * honest route, and nothing that can fail.
 *
 * Every card seeds a conversation rather than opening a page. `stageFirstTurn`
 * already does this from the landing screen; this is the same mechanism one
 * surface further in.
 */
import { type HookLanguage, hookFor, TAGLINES } from "#/lib/aspire/hooks";

export interface WelcomeCard {
	/** What the reader taps. */
	title: string;
	/** One line under it. */
	blurb: string;
	/**
	 * The question this sends. Absent when the card opens a panel instead --
	 * which is how an adult reaches the films, since asking for one routes
	 * through `for_persona` and comes back declined.
	 */
	question?: string;
	/** Opens a browsing surface rather than starting a turn. */
	panel?: "videos";
	icon: string;
}

/**
 * The starter cards, in one table across three languages.
 *
 * THEY WERE ENGLISH LITERALS, and the reader could see it: a Spanish
 * conversation opened with "Hola. Soy Azuri." over four cards reading "What
 * exists, at what level?" and "Can I use this with Form 3?". Reported from the
 * live site, 26 Aug.
 *
 * The shape is the one `hooks.ts` already chose, and for the reason its own
 * comment gives: a per-persona switch was fine for one language and would have
 * become three near-identical switches for three. `icon` and `panel` are not
 * language, so they are written once per card and shared.
 *
 * `question` is translated too, not just the label. It is the text actually
 * sent, and sending English from a Spanish screen makes the reader's own
 * language look like a skin over an English product.
 */
type CardSet = "young" | "guardian" | "educator";

const ICONS: Record<
	CardSet,
	ReadonlyArray<Pick<WelcomeCard, "icon" | "panel">>
> = {
	young: [
		{ icon: "ph-duotone ph-graduation-cap" },
		{ icon: "ph-duotone ph-game-controller" },
		{ icon: "ph-duotone ph-book-open-text" },
		{ icon: "ph-duotone ph-piggy-bank" },
	],
	guardian: [
		{ icon: "ph-duotone ph-graduation-cap" },
		{ icon: "ph-duotone ph-user" },
		{ icon: "ph-duotone ph-file-text" },
		{ icon: "ph-duotone ph-books" },
	],
	educator: [
		{ icon: "ph-duotone ph-graduation-cap" },
		{ icon: "ph-duotone ph-books" },
		{ icon: "ph-duotone ph-chart-line-up" },
		{ icon: "ph-duotone ph-file-text" },
	],
};

type CardCopy = { title: string; blurb: string; question: string };

const COPY: Record<HookLanguage, Record<CardSet, ReadonlyArray<CardCopy>>> = {
	en: {
		young: [
			{
				title: "What is ASPIRE?",
				blurb: "Learn how ASPIRE helps you build money skills for life.",
				question: "What is ASPIRE?",
			},
			{
				title: "Play a 2-minute challenge",
				blurb: "Quick challenges to learn and earn coins.",
				question: "I'd like to play a game.",
			},
			{
				title: "Tell me a story",
				blurb: "Island tales that teach money lessons.",
				question: "Can I watch a story?",
			},
			{
				title: "How does saving work?",
				blurb: "The idea behind putting money away.",
				question: "How does saving work?",
			},
		],
		guardian: [
			{
				title: "What is ASPIRE?",
				blurb: "The programme, in one answer.",
				question: "What is ASPIRE?",
			},
			{
				title: "Who is eligible?",
				blurb: "Who qualifies, and from what age.",
				question: "Who is eligible for ASPIRE?",
			},
			{
				title: "How do I register?",
				blurb: "Where to go and what to bring.",
				question: "How do I register a young person for ASPIRE?",
			},
			{
				title: "What will they learn?",
				blurb: "The material, split by age.",
				question: "What will young people learn through ASPIRE?",
			},
		],
		/* The fourth educator card is taken from Azuri's own persona card, not
		   invented: her EVALUATING branch is written against this exact question
		   -- `IF he is EVALUATING ("can I use this with Form 3") -> state the
		   pitch level, describe the material honestly, and name the gap BEFORE
		   he finds it`. A chip that invites a refusal is a broken chip, so the
		   Spanish and French versions keep the same intent in local school
		   vocabulary rather than translating "Form 3" literally. */
		educator: [
			{
				title: "What is ASPIRE?",
				blurb: "The programme, and who runs it.",
				question: "What is ASPIRE?",
			},
			{
				title: "What exists, at what level?",
				blurb: "The material as it stands today.",
				question: "What ASPIRE material exists, and at what levels?",
			},
			{
				title: "Where are the figures from?",
				blurb: "Every number, with its source.",
				question:
					"Where do the ASPIRE figures come from? Please include sources.",
			},
			{
				title: "Can I use this with Form 3?",
				blurb: "The pitch level, and the gaps.",
				question: "Can I use ASPIRE with a Form 3 class?",
			},
		],
	},
	es: {
		young: [
			{
				title: "¿Qué es ASPIRE?",
				blurb: "Descubre cómo ASPIRE te ayuda a manejar tu dinero.",
				question: "¿Qué es ASPIRE?",
			},
			{
				title: "Reto de 2 minutos",
				blurb: "Retos rápidos para aprender y ganar monedas.",
				question: "Quiero jugar un juego.",
			},
			{
				title: "Cuéntame un cuento",
				blurb: "Cuentos isleños que enseñan sobre el dinero.",
				question: "¿Puedo ver un cuento?",
			},
			{
				title: "¿Cómo funciona ahorrar?",
				blurb: "La idea de guardar dinero para después.",
				question: "¿Cómo funciona ahorrar?",
			},
		],
		guardian: [
			{
				title: "¿Qué es ASPIRE?",
				blurb: "El programa, en una respuesta.",
				question: "¿Qué es ASPIRE?",
			},
			{
				title: "¿Quién puede participar?",
				blurb: "Quién califica y desde qué edad.",
				question: "¿Quién puede participar en ASPIRE?",
			},
			{
				title: "¿Cómo lo inscribo?",
				blurb: "A dónde ir y qué llevar.",
				question: "¿Cómo inscribo a un joven en ASPIRE?",
			},
			{
				title: "¿Qué van a aprender?",
				blurb: "El material, por edades.",
				question: "¿Qué aprenderán los jóvenes con ASPIRE?",
			},
		],
		educator: [
			{
				title: "¿Qué es ASPIRE?",
				blurb: "El programa y quién lo dirige.",
				question: "¿Qué es ASPIRE?",
			},
			{
				title: "¿Qué hay y para qué nivel?",
				blurb: "El material tal como está hoy.",
				question: "¿Qué material de ASPIRE existe y para qué niveles?",
			},
			{
				title: "¿De dónde salen las cifras?",
				blurb: "Cada número, con su fuente.",
				question:
					"¿De dónde vienen las cifras de ASPIRE? Incluye las fuentes, por favor.",
			},
			{
				title: "¿Sirve para mi clase?",
				blurb: "El nivel y lo que falta.",
				question: "¿Puedo usar ASPIRE con una clase de Form 3?",
			},
		],
	},
	fr: {
		young: [
			{
				title: "C'est quoi ASPIRE ?",
				blurb: "Découvre comment ASPIRE t'aide avec ton argent.",
				question: "C'est quoi ASPIRE ?",
			},
			{
				title: "Défi de 2 minutes",
				blurb: "Des défis rapides pour apprendre et gagner des pièces.",
				question: "Je veux jouer à un jeu.",
			},
			{
				title: "Raconte-moi une histoire",
				blurb: "Des histoires des îles qui parlent d'argent.",
				question: "Je peux avoir une histoire ?",
			},
			{
				title: "Comment fonctionne l'épargne ?",
				blurb: "L'idée de mettre de l'argent de côté.",
				question: "Comment fonctionne l'épargne ?",
			},
		],
		guardian: [
			{
				title: "C'est quoi ASPIRE ?",
				blurb: "Le programme, en une réponse.",
				question: "C'est quoi ASPIRE ?",
			},
			{
				title: "Qui peut participer ?",
				blurb: "Qui remplit les conditions, et à partir de quel âge.",
				question: "Qui peut participer à ASPIRE ?",
			},
			{
				title: "Comment l'inscrire ?",
				blurb: "Où aller et quoi apporter.",
				question: "Comment inscrire un jeune à ASPIRE ?",
			},
			{
				title: "Qu'est-ce qu'ils apprennent ?",
				blurb: "Le contenu, par tranche d'âge.",
				question: "Qu'apprendront les jeunes avec ASPIRE ?",
			},
		],
		educator: [
			{
				title: "C'est quoi ASPIRE ?",
				blurb: "Le programme, et qui le dirige.",
				question: "C'est quoi ASPIRE ?",
			},
			{
				title: "Quel contenu, quel niveau ?",
				blurb: "Le matériel tel qu'il est aujourd'hui.",
				question: "Quel matériel ASPIRE existe, et pour quels niveaux ?",
			},
			{
				title: "D'où viennent les chiffres ?",
				blurb: "Chaque chiffre, avec sa source.",
				question:
					"D'où viennent les chiffres d'ASPIRE ? Merci d'indiquer les sources.",
			},
			{
				title: "Utilisable dans ma classe ?",
				blurb: "Le niveau visé, et les manques.",
				question: "Puis-je utiliser ASPIRE avec une classe de Form 3 ?",
			},
		],
	},
};

function build(
	set: CardSet,
	language: HookLanguage,
): ReadonlyArray<WelcomeCard> {
	const copy = COPY[language]?.[set] ?? COPY.en[set];
	return copy.map((card, index) => ({ ...card, ...ICONS[set][index] }));
}

export function cardsFor(
	persona: string | null | undefined,
	language: HookLanguage = "en",
): ReadonlyArray<WelcomeCard> {
	const key = (persona ?? "").trim().toLowerCase();
	if (key === "aurora") return build("guardian", language);
	if (key === "nova") return build("educator", language);
	// Everything else, including no persona at all, gets the young set. Nothing
	// in it can fail for any reader now, so an unknown key costs nothing.
	return build("young", language);
}

/* The hooks themselves moved to `lib/aspire/hooks.ts`, where they sit in one
 * table across English, Spanish and French. They were here as a switch over
 * personas, which was fine for one language and would have become three
 * near-identical switches for three. The ladder that governs them, and the
 * reason every adult line is conditional, is documented there and in
 * `docs/HOOK_SPINE.md`. */

export function ChatWelcome({
	persona,
	language = "en",
	priorConversations = 0,
	readerName = null,
	onAsk,
	onOpenVideos,
	showOnboarding = true,
}: {
	persona: string | null | undefined;
	/** How many conversations this reader already has. Zero on a first visit. */
	/** Which language the hook is spoken in. English until told otherwise. */
	language?: HookLanguage;
	priorConversations?: number;
	/** The signed-in reader's first name, when the account knows it. */
	readerName?: string | null;
	onAsk: (question: string) => void;
	onOpenVideos?: () => void;
	/**
	 * Whether the onboarding content is still doing its job.
	 *
	 * THE PAGE DOES NOT CHANGE STATE. There is one desktop conversation layout,
	 * and what happens on the reader's first action is progressive content
	 * COLLAPSE inside it -- not a switch to a second layout.
	 *
	 * What stays, always: the avatar, the title and the tagline. That is the
	 * guide's identity and the product's promise, and neither stops being true
	 * once a question has been asked.
	 *
	 * What goes, once the reader has started: the supporting paragraph and the
	 * four chips. Both exist to answer "what is this and what do I do here",
	 * and the reader who has just asked something has answered that themselves.
	 * The freed space goes to the transcript, which is what they actually came
	 * to read.
	 *
	 * Gating both on one flag rather than two, because they collapse together
	 * and always will: they are the same beat of the spine (ORIENT and INVITE),
	 * and a version where the paragraph lingered without the chips would read
	 * as the page having failed to finish tidying up.
	 */
	showOnboarding?: boolean;
}) {
	const cards = cardsFor(persona, language);
	const welcome = hookFor(persona, language, priorConversations, readerName);
	const tagline = TAGLINES[language] ?? TAGLINES.en;

	return (
		<div className="welcome">
			<section className="welcome-zone">
				{/* THE ORB IS ASPIRE ITSELF, and the guide's face replaces it once one
				 * is chosen -- spec section 17, and the same `.orb` element does both:
				 * `--orb-face` carries the guide's portrait, and Guest has none, so
				 * Guest keeps the purple sphere with its gold star. One element, no
				 * branch, and the two are never shown together.
				 *
				 * Above the headline rather than beside it, so it reads as a guide
				 * hovering over the introduction rather than a bullet point. */}
				<div className="welcome-zone__orb orb" aria-hidden="true" />

				{/* THE SAME TREATMENT AS THE LANDING HEADLINE, and deliberately so:
				 * `font-display font-medium` in the ink token with the emphatic
				 * half italic in one flat brand colour, exactly as "take you?" is
				 * set on "Where will your money take you?". The two headlines are
				 * the reader's first and second impression of the same product,
				 * and they should look like it -- which is why the gradient came
				 * off both together. */}
				<h1 className="welcome-title font-display font-medium tracking-tight">
					{welcome.lead}
					<span className="welcome-title__accent">{welcome.accent}</span>{" "}
					<span aria-hidden="true">{welcome.emoji}</span>
				</h1>

				{/* Three words carry brand colour and the rest does not. Colouring
				 * every word turns a tagline into a rainbow. */}
				<p className="welcome-tagline">
					<span className="welcome-tagline__ask">{tagline.ask}</span>{" "}
					<span className="welcome-tagline__play">{tagline.play}</span>{" "}
					<span className="welcome-tagline__explore">{tagline.explore}</span>{" "}
					{tagline.rest}
				</p>

				{/* Interface copy, not a chat message -- so no bubble and no orb
				 * beside it. The second sentence changes per guide; the placement
				 * never does. */}
				{/* No hardcoded greeting in front of this any more. The headline
				 * does the welcoming now, in each guide's own words, and prefixing
				 * "Welcome to ASPIRE AI." to Imani's line said it twice.
				 *
				 * Collapses with the chips: it orients a reader who has not started
				 * and repeats itself to one who has. */}
				{showOnboarding ? <p className="welcome-copy">{welcome.line}</p> : null}
			</section>

			{showOnboarding ? (
				<ul className="welcome__cards">
					{cards.map((card) => (
						<li key={card.title}>
							<button
								type="button"
								className="welcome__card"
								onClick={() =>
									card.panel === "videos"
										? onOpenVideos?.()
										: card.question && onAsk(card.question)
								}
							>
								<i className={card.icon} aria-hidden="true" />
								<span className="welcome__card-title">{card.title}</span>
								<span className="welcome__card-blurb">{card.blurb}</span>
							</button>
						</li>
					))}
				</ul>
			) : null}
		</div>
	);
}
