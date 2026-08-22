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

/**
 * THE ASPIRE PERSONALISATION LADDER.
 *
 * The governing rule, and the reason this file reads the way it does:
 *
 *     ASPIRE may always personalise DOWNWARD to what it knows.
 *     It must never personalise UPWARD by guessing.
 *
 * The levels, and what each is licensed to say:
 *
 *   L0  unknown           "Hi there."
 *   L1  audience known    "if you're supporting a young person..."
 *   L2  role known        "as a parent...", "as a teacher..."
 *   L3  relationship      "your daughter", "your grandson", "your students"
 *   L4  context           "your six-year-old", "your Form 3 class"
 *   L5  goal              "you're working out whether she is eligible"
 *
 * THIS FUNCTION IS PINNED AT L1 and cannot go higher, because a welcome fires
 * before the reader has said anything. Choosing "Parents & Guardians" says the
 * reader belongs somewhere in that audience. It does NOT say parent -- they may
 * be a grandmother, an aunt, a foster carer, a guardian, or someone asking on
 * behalf of a friend. Choosing "Teachers & Educators" does not say classroom
 * teacher: principal, facilitator, counsellor and youth worker all live there.
 *
 * So the conditional matters. "If you're supporting a young person" is true of
 * every one of them and asserts nothing. "You're building their future" reads
 * warmer and is an L3 claim about a relationship nobody has stated -- it was
 * here until 22 Aug and it was wrong.
 *
 * L2 and above belong to the conversation, where the reader supplies the fact:
 * "my daughter is six" licenses "your daughter", and not one word before it.
 *
 * The shape at every level is the same seven beats:
 *   WELCOME -> ORIENT -> INVITE -> DISCOVER -> MIRROR -> IMPACT -> GUIDE
 * A welcome owns the first three. The rest are the conversation's.
 */
function welcomeFor(
	persona: string | null | undefined,
	priorConversations = 0,
): {
	/** Set plain, in the display face. */
	lead: string;
	/** Set in the italic gradient, exactly as "take you!" is on the landing. */
	accent: string;
	emoji: string;
	line: string;
} {
	const returning = priorConversations > 0;
	switch ((persona ?? "").trim().toLowerCase()) {
		// ── the adult audiences: L1, and the conditional is load-bearing ──
		case "aurora":
			return {
				lead: returning ? "Welcome " : "Hi there. Welcome to ",
				accent: returning ? "back." : "Imani.",
				emoji: "\u{1F331}",
				line: returning
					? "Where would you like to pick up?"
					: "If you\u2019re supporting a young person through ASPIRE, I can help with the programme, their learning, and what comes next. What can I help you with today?",
			};
		case "nova":
			return {
				lead: returning ? "Welcome " : "Hi there. Welcome to ",
				accent: returning ? "back." : "Azuri.",
				emoji: "\u{1F4DA}",
				line: returning
					? "What would be useful today?"
					: "If you\u2019re helping young people learn, I can give you accurate, sourced information and practical ASPIRE support. What would be useful today?",
			};

		// ── the child and teen bands: the age IS known, so it may be used ──
		case "stella":
			return {
				lead: returning ? "Welcome back, " : "Hi there, ",
				accent: returning ? "explorer!" : "little explorer!",
				emoji: "\u2728",
				line: returning
					? "What should we find out today?"
					: "There are lots of things about money we can discover together. What should we explore today?",
			};
		case "kaleb":
			return {
				lead: returning ? "Back for " : "Hey \u2014 ready to ",
				accent: returning ? "more?" : "figure something out?",
				emoji: "\u{1F680}",
				line: returning
					? "What are we working out this time?"
					: "Money, ASPIRE, saving, investing \u2014 whatever you\u2019re trying to understand. What do you want to work out?",
			};
		case "orion":
			return {
				lead: returning ? "Welcome " : "Hi. What do you need to ",
				accent: returning ? "back." : "get clear on?",
				emoji: "\u2728",
				line: "I can help with ASPIRE, money questions, planning, and the facts behind the numbers.",
			};

		// ── L0: Guest knows nothing safe about anybody ──
		default:
			return {
				lead: returning ? "Welcome " : "Hi there. Welcome to ",
				accent: returning ? "back." : "ASPIRE AI.",
				emoji: "\u2728",
				line: "What would you like to explore or learn today?",
			};
	}
}

export function ChatWelcome({
	persona,
	priorConversations = 0,
	onAsk,
	onOpenVideos,
}: {
	persona: string | null | undefined;
	/** How many conversations this reader already has. Zero on a first visit. */
	priorConversations?: number;
	onAsk: (question: string) => void;
	onOpenVideos?: () => void;
}) {
	const cards = cardsFor(persona);
	const welcome = welcomeFor(persona, priorConversations);

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
					<span className="welcome-tagline__ask">Ask.</span>{" "}
					<span className="welcome-tagline__play">Play.</span>{" "}
					<span className="welcome-tagline__explore">Explore.</span> Build your
					money future.
				</p>

				{/* Interface copy, not a chat message -- so no bubble and no orb
				 * beside it. The second sentence changes per guide; the placement
				 * never does. */}
				{/* No hardcoded greeting in front of this any more. The headline
				 * does the welcoming now, in each guide's own words, and prefixing
				 * "Welcome to ASPIRE AI." to Imani's line said it twice. */}
				<p className="welcome-copy">{welcome.line}</p>
			</section>

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
		</div>
	);
}
