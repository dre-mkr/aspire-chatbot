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
		title: "Is my child eligible?",
		blurb: "Who qualifies, and from what age.",
		question: "Is my child eligible for ASPIRE?",
		icon: "ph-duotone ph-user",
	},
	{
		title: "How do I register?",
		blurb: "Where to go and what to bring.",
		question: "How do I register my child for ASPIRE?",
		icon: "ph-duotone ph-file-text",
	},
	{
		title: "What will they learn?",
		blurb: "The material, split by age.",
		question: "What will my child learn through ASPIRE?",
		icon: "ph-duotone ph-books",
	},
	{
		title: "Watch the films",
		blurb: "The two stories your child is shown.",
		panel: "videos",
		icon: "ph-duotone ph-play-circle",
	},
	{
		title: "Try a challenge yourself",
		blurb: "The same quiz the children play.",
		question: "I'd like to play a game.",
		icon: "ph-duotone ph-game-controller",
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
		title: "What is not built yet?",
		blurb: "The gaps, named plainly.",
		question: "What parts of ASPIRE are planned but not built yet?",
		icon: "ph-duotone ph-file-text",
	},
	{
		title: "Watch the films",
		blurb: "Judge the material yourself.",
		panel: "videos",
		icon: "ph-duotone ph-play-circle",
	},
	{
		title: "Try a challenge yourself",
		blurb: "The same quiz your students play.",
		question: "I'd like to play a game.",
		icon: "ph-duotone ph-game-controller",
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
 * How the reader is addressed on the empty thread.
 *
 * "future builder" is the client's line and it is written for a child. Skye,
 * Kaleb and Zion get it. Imani is a parent with four minutes and Azuri is a
 * teacher deciding whether to use this with a class -- calling either of them a
 * future builder reads as a product that has not noticed who is talking, which
 * is the exact failure the six voices exist to avoid.
 */
function greetingFor(
	persona: string | null | undefined,
	band: string | null | undefined,
): { line: string; emoji: string } {
	const key = (persona ?? "").trim().toLowerCase();
	if (key === "aurora") {
		return { line: "Hi there — glad you came.", emoji: "\u{1F44B}" };
	}
	if (key === "nova") {
		return { line: "Hi there — have a look around.", emoji: "\u{1F44B}" };
	}
	// stella, kaleb, orion and guest: the child and teen voices, and the one
	// that has not been told who is reading.
	void band;
	return { line: "Hi there, future builder!", emoji: "\u{1F680}" };
}

export function ChatWelcome({
	persona,
	ageBand,
	onAsk,
	onOpenVideos,
}: {
	persona: string | null | undefined;
	ageBand?: string | null;
	onAsk: (question: string) => void;
	onOpenVideos?: () => void;
}) {
	const cards = cardsFor(persona);
	const greeting = greetingFor(persona, ageBand);

	return (
		<div className="welcome">
			<div className="welcome__hero">
				{/* THE MARK, NOT THE GUIDE'S FACE.
				 *
				 * The guide's face is already on every answer below and on the
				 * composer chip. Repeating it a third time in the same viewport
				 * says nothing new -- and this block is the moment the reader
				 * meets ASPIRE, not the moment they meet Skye. The A does that
				 * job; the guide introduces themselves in their own first reply.
				 */}
				<img
					className="welcome__mark"
					src="/brand/aspire-mark.png"
					alt=""
					width={40}
					height={40}
					aria-hidden="true"
				/>
				<div>
					{/* Set in the display face the landing hero uses, because this is
					 * the same sentence one surface later -- a reader who arrives
					 * here from "Where will your money take you!" should recognise
					 * the voice.
					 *
					 * The greeting is BAND-AWARE. "future builder" is written for a
					 * child; it would read as faintly ridiculous to a teacher
					 * evaluating the material or a parent with four minutes, so the
					 * adult voices get an address of their own. */}
					<h2 className="welcome__greeting">
						{greeting.line} <span aria-hidden="true">{greeting.emoji}</span>
					</h2>
					<p className="welcome__tagline">
						Ask. Play. Explore. Build your money future.
					</p>
					<p className="welcome__sub">
						Welcome to ASPIRE AI. What would you like to <em>explore</em> or{" "}
						<em>learn</em> today?
					</p>
				</div>
			</div>

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
