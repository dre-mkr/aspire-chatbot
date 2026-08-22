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

/** For the readers who may be offered games and films. */
const YOUNG: ReadonlyArray<WelcomeCard> = [
	{
		title: "What is ASPIRE?",
		blurb: "Learn how ASPIRE helps you build money skills for life.",
		question: "What is ASPIRE?",
		icon: "ph-duotone ph-graduation-cap",
	},
	{
		title: "Play a 2-minute challenge",
		blurb: "Quick challenges to learn and earn coins.",
		question: "I'd like to play a game.",
		icon: "ph-duotone ph-game-controller",
	},
	{
		title: "Tell me a story",
		blurb: "Island tales that teach money lessons.",
		question: "Can I watch a story?",
		icon: "ph-duotone ph-book-open-text",
	},
	{
		title: "How does saving work?",
		blurb: "The idea behind putting money away.",
		question: "How does saving work?",
		icon: "ph-duotone ph-piggy-bank",
	},
];

/** Imani's readers arrive with a question, not for an activity. */
const GUARDIAN: ReadonlyArray<WelcomeCard> = [
	{
		title: "What is ASPIRE?",
		blurb: "The programme, and who runs it.",
		question: "What is ASPIRE?",
		icon: "ph-duotone ph-graduation-cap",
	},
	{
		title: "Who is eligible?",
		blurb: "Who qualifies, and from what age.",
		question: "Who is eligible for ASPIRE?",
		icon: "ph-duotone ph-user",
	},
	{
		title: "How do I register?",
		blurb: "Where to go and what to bring.",
		question: "How do I register a young person for ASPIRE?",
		icon: "ph-duotone ph-file-text",
	},
	{
		title: "What will they learn?",
		blurb: "The material, split by age.",
		question: "What will young people learn through ASPIRE?",
		icon: "ph-duotone ph-books",
	},
];

/** Azuri's readers are evaluating, not learning. */
const EDUCATOR: ReadonlyArray<WelcomeCard> = [
	{
		title: "What is ASPIRE?",
		blurb: "The programme, and who runs it.",
		question: "What is ASPIRE?",
		icon: "ph-duotone ph-graduation-cap",
	},
	{
		title: "What exists, at what level?",
		blurb: "The material as it stands today.",
		question: "What ASPIRE material exists, and at what levels?",
		icon: "ph-duotone ph-books",
	},
	{
		title: "Where are the figures from?",
		blurb: "Every number, with its source.",
		question: "Where do the ASPIRE figures come from? Please include sources.",
		icon: "ph-duotone ph-chart-line-up",
	},
	{
		/* Taken from Azuri's own card, not invented: her EVALUATING branch is
		   written against this exact question -- `IF he is EVALUATING ("can I use
		   this with Form 3") -> state the pitch level, describe the material
		   honestly, and name the gap BEFORE he finds it`. So the chip lands on a
		   route she is built for, in local school vocabulary.

		   Two earlier drafts were wrong. "What is not built yet?" asked about the
		   product's build status rather than about ASPIRE. "Running it as a
		   lesson" was worse: her red line 2 forbids claiming to be a curriculum
		   or a scheme of work, so that chip primed the one answer she must
		   refuse. A chip that invites a refusal is a broken chip. */
		title: "Can I use this with Form 3?",
		blurb: "The pitch level, and the gaps.",
		question: "Can I use ASPIRE with a Form 3 class?",
		icon: "ph-duotone ph-file-text",
	},
];

export function cardsFor(
	persona: string | null | undefined,
): ReadonlyArray<WelcomeCard> {
	const key = (persona ?? "").trim().toLowerCase();
	if (key === "aurora") return GUARDIAN;
	if (key === "nova") return EDUCATOR;
	// Everything else, including no persona at all, gets the young set. Nothing
	// in it can fail for any reader now, so an unknown key costs nothing.
	return YOUNG;
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
	onAsk,
	onOpenVideos,
	showCards = true,
}: {
	persona: string | null | undefined;
	/** How many conversations this reader already has. Zero on a first visit. */
	/** Which language the hook is spoken in. English until told otherwise. */
	language?: HookLanguage;
	priorConversations?: number;
	onAsk: (question: string) => void;
	onOpenVideos?: () => void;
	/**
	 * Whether to offer the four chips.
	 *
	 * The HOOK and the CHIPS have different lifetimes, which is the thing this
	 * separates. The hook is the guide saying hello -- beats one to three of the
	 * spine, RECOGNISE / ORIENT / INVITE -- and it belongs at the top of the
	 * conversation whether or not the reader arrived with something to say.
	 * The chips are an invitation to start, so once the reader has started they
	 * are furniture in the way of the answer.
	 *
	 * Before this split the whole block was gated on `messages.length === 0`,
	 * and a reader who chose Imani and typed "hi" on the landing never saw her
	 * greet them at all: staging the turn made the thread non-empty before the
	 * chat first painted. Only the guide cards, which stage nothing, ever showed
	 * a hook.
	 */
	showCards?: boolean;
}) {
	const cards = cardsFor(persona);
	const welcome = hookFor(persona, language, priorConversations);
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
				 * `font-display font-medium` in #1A103C with the emphatic half in
				 * the italic pink-to-indigo gradient, exactly as "take you!" is set
				 * on "Where will your money take you!". The two headlines are the
				 * reader's first and second impression of the same product, and
				 * they should look like it. */}
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
				 * "Welcome to ASPIRE AI." to Imani's line said it twice. */}
				<p className="welcome-copy">{welcome.line}</p>
			</section>

			{showCards ? (
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
