import { useNavigate } from "@tanstack/react-router";
import type React from "react";
import { useEffect, useRef, useState } from "react";
import { AccountControl } from "#/components/auth/AccountControl";
import {
	markFreshThread,
	stageFirstTurn,
	stageVoiceStart,
} from "#/lib/aspire/handoff";
import { currentLocale, say, useLocale } from "#/lib/aspire/i18n";
import { type AgeBand, GUIDES, type PersonaId } from "#/lib/aspire/personas";
import { useSession } from "#/lib/aspire/use-session";
import {
	preferredGuide,
	rememberGuide,
	workspaceDestination,
} from "#/lib/aspire/workspace";
import { AboutView } from "./AboutView";
import { Brandmark } from "./Brandmark";
import { EducatorsView } from "./EducatorsView";
import { GalleryView } from "./GalleryView";
import { GuideSelector } from "./GuideSelector";
import { HistoryView } from "./HistoryView";
import { JourneyView } from "./JourneyView";
import { ParentsView } from "./ParentsView";
import { StoriesView } from "./StoriesView";

/** What the reward is called, which is not settled.
 *
 * "Magic Coins" here, "Hero Bucks" and "Super Saver Bucks" on the Grade 1
 * classroom chart. Three names for one thing is how a child ends up believing
 * they are three things. Named once, in one place, so the decision is one edit
 * when it is made.
 */
const COIN_LABEL = "Magic Coins";

/** The reader's balance, or null when there is nobody signed in to have one.
 *
 * Null on purpose. It was `142` -- a literal, shown to every visitor, including
 * the ones who had never earned a coin.
 */
const coinBalance: number | null = null;

type ViewState =
	| "landing"
	| "chat"
	| "history"
	| "journey"
	| "stories"
	| "parents"
	| "educators"
	| "gallery"
	| "about";
/**
 * The names on the guide picker, which are LABELS and not persona keys.
 *
 * This was called `PersonaId` and it shadowed the real one in
 * `lib/aspire/personas.ts`, where the ids are `stella`, `orion`, `aurora`,
 * `nova` and `guest`. Two incompatible definitions of the same idea, and the
 * label version won on this page -- which is part of why the picker never did
 * anything: nothing downstream understood the word "skye".
 *
 * Renamed to what it is, and mapped to the keys once, here.
 */
type GuideId = "skye" | "kaleb" | "zion" | "imani" | "azuri";

/** Label to key. `skye` and `kaleb` are one key; the band decides the voice. */
const GUIDE_TO_PERSONA: Record<GuideId, PersonaId> = {
	skye: "stella",
	kaleb: "kaleb",
	zion: "orion",
	imani: "aurora",
	azuri: "nova",
};

/**
 * Label to band, for the two labels a persona key cannot tell apart.
 *
 * Only `skye` and `kaleb` need a row. The other three are the only guide on
 * their key, so the server's own default for that persona is already right and
 * naming a band here would be three more values to keep in step for nothing.
 *
 * Without this, tapping Kaleb sent `?persona=stella` and no band, the server
 * fell back to `stella`'s default of `5-8`, and the reader who asked for Kaleb
 * was answered by Skye -- with Skye's name on the composer chip.
 */
const GUIDE_TO_BAND: Partial<Record<GuideId, AgeBand>> = {
	skye: "5-8",
	kaleb: "9-12",
};

/**
 * The four ways into the product, as a table rather than as four hand-built
 * cards that had drifted apart from one another.
 *
 * Every field that used to vary arbitrarily — the accent colour, the icon
 * glow, the hover shadow, whether the caret circle was there — is gone. What
 * is left is what actually differs between them: the words, the icon and where
 * the tap goes.
 */
interface WayIn {
	title: string;
	/** One line on what is behind it. */
	dek: string;
	blurb: string;
	/** Phosphor, all four at the same weight. */
	icon: string;
	badge?: string;
	go: (nav: {
		startConversation: (message: string) => void;
		setActiveView: (view: ViewState) => void;
	}) => void;
}

const WAYS_IN: ReadonlyArray<WayIn> = [
	{
		title: "Ask ASPIRE",
		dek: "Your AI guide",
		blurb: "Get smart answers to your money questions.",
		icon: "ph-duotone ph-chat-teardrop-dots",
		badge: "New",
		go: ({ startConversation }) =>
			startConversation(
				"Hello ASPIRE, I am ready to explore the financial and learning ecosystem in St. Kitts and Nevis.",
			),
	},
	{
		title: "Play",
		dek: "Today's challenge",
		blurb: "Learn by doing, and earn coins as you go.",
		icon: "ph-duotone ph-game-controller",
		go: ({ startConversation }) =>
			startConversation(
				"Start the ASPIRE savings challenge to help me manage my 1,000 XCD youth grant.",
			),
	},
	{
		title: "Explore",
		dek: "Miracle Mountain",
		blurb: "Listen to a story or watch an adventure.",
		icon: "ph-duotone ph-play-circle",
		go: ({ setActiveView }) => setActiveView("stories"),
	},
	{
		title: "My Journey",
		dek: "Your progress path",
		blurb: "Badges and lessons, once you begin.",
		icon: "ph-duotone ph-medal",
		go: ({ setActiveView }) => setActiveView("journey"),
	},
];

/** The header nav, in the order the sections are meant to be met. */
const NAV: ReadonlyArray<{
	view: ViewState;
	labelKey: Parameters<typeof say>[0];
}> = [
	{ view: "stories", labelKey: "landExplore" },
	{ view: "journey", labelKey: "landJourney" },
	{ view: "gallery", labelKey: "landGallery" },
	{ view: "parents", labelKey: "landParents" },
	{ view: "educators", labelKey: "landEducators" },
	{ view: "about", labelKey: "landAbout" },
];

/** The three shortest ways to a first answer. */
const QUICK_ASKS: ReadonlyArray<{
	title: string;
	caption: string;
	icon: string;
	question: string;
}> = [
	{
		title: "What is ASPIRE?",
		caption: "Learn the basics",
		icon: "ph-duotone ph-graduation-cap",
		question: "What exactly is the ASPIRE programme in St. Kitts and Nevis?",
	},
	{
		title: "Grant money",
		caption: "How to get the ASPIRE grant",
		icon: "ph-duotone ph-coins",
		question: "How do I get the ASPIRE grant money?",
	},
	{
		title: "SKN Wealth Builder",
		caption: "Build your future",
		icon: "ph-duotone ph-chart-line-up",
		question: "Help me build wealth in St. Kitts and Nevis.",
	},
];

interface LandingScreenProps {
	onStartConversation?: (message: string) => void;
}

export function LandingScreen({ onStartConversation }: LandingScreenProps) {
	// Re-render when the reader changes language: `say` reads storage,
	// and storage changing is not something React can see on its own.
	useLocale();
	const navigate = useNavigate();
	const [draft, setDraft] = useState("");
	const [activeView, setActiveView] = useState<ViewState>("landing");
	const [selectedPersona, setSelectedPersona] = useState<GuideId | null>(null);
	/** The phone menu. Closed is the only state the markup ships in. */
	const [menuOpen, setMenuOpen] = useState(false);
	const menuRef = useRef<HTMLElement>(null);
	const menuButtonRef = useRef<HTMLButtonElement>(null);

	/* Escape closes it and focus goes back to the button that opened it —
	   the same contract `ViewLauncher` and `GuideChooser` keep. */
	useEffect(() => {
		if (!menuOpen) return;
		const onKey = (event: KeyboardEvent) => {
			if (event.key !== "Escape") return;
			setMenuOpen(false);
			menuButtonRef.current?.focus();
		};
		window.addEventListener("keydown", onKey);
		// The first item, so a keyboard reader lands inside rather than after it.
		menuRef.current?.querySelector("button")?.focus();
		return () => window.removeEventListener("keydown", onKey);
	}, [menuOpen]);

	/**
	 * Who is signed in, from the same store the chat rail reads.
	 *
	 * `resolved` is why the header does not flash: it is false until the session
	 * question has been answered, and answering it is a network call on a cold
	 * arrival.
	 */
	const { session, resolved } = useSession();
	const signedIn = session?.accountType === "registered";

	/** Their guide, if the account or this device remembers one. */
	const rememberedGuide = preferredGuide(session);
	const rememberedName = GUIDES.find(
		(guide) => guide.guideId === rememberedGuide,
	)?.name;
	const continueLabel = rememberedName
		? `Continue with ${rememberedName}`
		: "Open ASPIRE AI";

	/** Back into the workspace: their last conversation, with their guide. */
	const openWorkspace = () => {
		const { chatId, search } = workspaceDestination(session);
		navigate({ to: "/chat/$chatId", params: { chatId }, search });
	};

	/** The chosen guide's row, for the face beside the name. Null means Guest. */
	const selected = selectedPersona
		? (GUIDES.find((g) => g.guideId === selectedPersona) ?? null)
		: null;

	const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
		if (e.key === "Enter" && draft.trim()) {
			startConversation(draft);
		}
	};

	const startConversation = (
		/**
		 * The reader's own first question, or null to open the guide with nothing
		 * staged.
		 *
		 * NULL IS THE FIX FOR A LIVE DEFECT. Choosing a guide used to stage
		 * "Hi! What can you help me with?" as the opening turn. With no
		 * conversation behind it that phrase classifies as an INTENT, the
		 * eligibility flow claims it, and the form then latches: every later
		 * message is read as an answer to the slot it is waiting on. Observed on
		 * production 22 Aug -- "who are you" returned the guardian probe again,
		 * and "how do I register my child" was read as a parish name. A five-year
		 * -old who picked Skye was asked how they were related to the child.
		 *
		 * The same phrase typed as a SECOND message answers normally, which is
		 * what says it is the opening-turn position and not the words.
		 *
		 * So a guide card now opens the conversation and lets the guide speak
		 * first. Zion already introduces himself properly when nothing hijacks
		 * the turn.
		 */
		message: string | null,
		persona?: PersonaId | null,
		band?: AgeBand | null,
	) => {
		if (onStartConversation) {
			if (message) onStartConversation(message);
		} else {
			const threadId = crypto.randomUUID();
			// No message means the guide opens the conversation, and the chat page
			// has to be told this address is new rather than unreachable.
			if (!message) markFreshThread(threadId);
			if (message) {
				stageFirstTurn({
					threadId,
					question: message,
					simple: false,
					// The reader's stored choice, not a hardcoded "en". The landing
					// has no selector of its own, so somebody who picked French in
					// the chat and came back here had their first turn staged as
					// English -- they typed "Bonjour" and were answered "Hello!".
					language: currentLocale(),
				});
			}
			// The guide rides the address, which is where the chat reads it from
			// (`validateAnswerSearch`). Until now `selectedPersona` was set by the
			// dropdown and then dropped on the floor: choosing a guide on this page
			// changed nothing at all about who answered.
			const chosen =
				persona ?? (selectedPersona ? GUIDE_TO_PERSONA[selectedPersona] : null);
			// The band rides along for the same reason the persona does, and it is
			// Still sent though Kaleb has his own key: it pins the band for a
			// persona that could otherwise take the server's default, and it is
			// what the old `stella` sessions are read back through.
			const chosenBand =
				band ?? (selectedPersona ? GUIDE_TO_BAND[selectedPersona] : null);
			navigate({
				to: "/chat/$chatId",
				params: { chatId: threadId },
				...(chosen
					? {
							search: {
								persona: chosen,
								...(chosenBand ? { band: chosenBand } : {}),
							},
						}
					: {}),
			});
		}
	};

	/**
	 * The microphone: open a conversation with nothing in it and the mic live.
	 *
	 * No question is staged, because there is not one yet — the reader is about
	 * to speak it. The chosen guide still rides the address, exactly as it does
	 * for a typed question, so asking out loud and asking in writing reach the
	 * same guide.
	 */
	const startByVoice = () => {
		const threadId = crypto.randomUUID();
		stageVoiceStart(threadId);
		/* A DEFECT THAT ONLY EXISTS IN THE MERGE. This arrival stages no
		 * question -- the reader is about to speak it -- which is exactly the
		 * shape `isFreshThread` was added to recognise. Without the mark the
		 * chat page falls through to `fetchConversation`, 404s on a thread the
		 * server has never been told about, and bounces the reader back to the
		 * landing before the microphone ever opens. `adoptThread` never runs
		 * either, so the composer would silently refuse every later turn. */
		markFreshThread(threadId);
		const chosen = selectedPersona ? GUIDE_TO_PERSONA[selectedPersona] : null;
		const chosenBand = selectedPersona ? GUIDE_TO_BAND[selectedPersona] : null;
		navigate({
			to: "/chat/$chatId",
			params: { chatId: threadId },
			...(chosen
				? {
						search: {
							persona: chosen,
							...(chosenBand ? { band: chosenBand } : {}),
						},
					}
				: {}),
		});
	};

	if (activeView === "history") {
		return (
			<HistoryView
				onBack={() => setActiveView("landing")}
				onSelectChat={(id) =>
					navigate({ to: "/chat/$chatId", params: { chatId: id } })
				}
			/>
		);
	}

	if (activeView === "journey") {
		return (
			<JourneyView
				onBack={() => setActiveView("landing")}
				onSignIn={() => navigate({ to: "/signin" })}
			/>
		);
	}

	if (activeView === "parents")
		return <ParentsView onBack={() => setActiveView("landing")} />;
	if (activeView === "educators")
		return <EducatorsView onBack={() => setActiveView("landing")} />;
	if (activeView === "gallery")
		return <GalleryView onBack={() => setActiveView("landing")} />;
	if (activeView === "about")
		return <AboutView onBack={() => setActiveView("landing")} />;

	if (activeView === "stories") {
		return <StoriesView onBack={() => setActiveView("landing")} />;
	}

	/*
	 * The page owns its scroll, and that is a fix rather than a preference.
	 *
	 * `body` carries the chat shell's `overflow: hidden`, and `GuideChooser` --
	 * which mounts inside `FirstRun`, on the chat page -- sets it again on a
	 * first visit. Either way the landing inherited a `body` it could not
	 * scroll, and the last 83px of it, which is the Saint Kitts and Nevis line,
	 * could not be reached by hand.
	 *
	 * Owning the scroll makes this page independent of whatever the shell has
	 * done to `body`. The artwork behind is `fixed`, so it still covers.
	 */
	return (
		<div className="relative h-dvh overflow-y-auto overflow-x-hidden bg-white flex flex-col font-sans selection:bg-magenta/20 text-ink">
			{/* Scenic Background Layers */}
			{/* The ground behind the artwork, and it is pale on purpose.
			 *
			 * It was `#1A103C`, the deep plum. Fully hidden while the image loads
			 * fine -- and the moment it does not, that is near-black body text on
			 * a near-black ground. A fallback should fail readable. */}
			{/* `fixed`, not `absolute`.
			 *
			 * Absolutely positioned, this layer was only ever as tall as the page
			 * element. On a large screen -- or any time the content came up short
			 * of the window -- the browser painted `body` below it, and `body` is
			 * the chat app's deep plum. A band of it sat under the footer.
			 *
			 * Fixed to the viewport, the artwork covers whatever the window is,
			 * the plum can never show, and the scene holds still while the page
			 * scrolls over it. */}
			<div className="fixed inset-0 pointer-events-none z-0 overflow-hidden bg-plum/5">
				<div
					className="absolute inset-0"
					style={{
						background: `
							linear-gradient(
								to bottom,
								rgba(255,255,255,0.22) 0%,
								rgba(255,255,255,0.55) 38%,
								rgba(255,255,255,0.78) 68%,
								rgba(255,255,255,0.88) 100%
							),
							image-set(
								url('/images/hero-bg.webp') type('image/webp'),
								url('/images/hero-bg.jpg') type('image/jpeg')
							) center center / cover no-repeat
						`,
						filter: "saturate(1.0) brightness(1.0)",
					}}
				></div>
			</div>

			{/* Elegant Header */}
			{/* z-20, NOT z-10. The header and `<main>` below are siblings, and while
			    both sat at z-10 the tie broke on document order -- so the hero
			    painted over the header. The account menu is `z-40` INSIDE this
			    header's stacking context, which meant it could never rise above
			    the hero however high it climbed: `elementFromPoint` over the
			    "Sign out" row returned the h1, and the click went to the heading.
			    A header is above the page it heads. */}
			<header className="landing-head relative z-20 w-full px-4 sm:px-8 pt-6 pb-4 flex items-center justify-between">
				<div className="flex items-center gap-8">
					<Brandmark variant="header" />
					{/* One nav, one weight.
					 *
					 * "Explore" was magenta and bold, "Journey" was ink/70 and NOT
					 * bold, and the other three were ink/70 AND bold — three
					 * treatments across five peers, with the magenta one reading as
					 * the current page on a page it is not. */}
					<nav className="hidden md:flex items-center gap-6 text-sm font-semibold">
						{NAV.map((item) => (
							<button
								key={item.view}
								type="button"
								onClick={() => setActiveView(item.view)}
								className="text-ink/70 hover:text-magenta transition-colors cursor-pointer rounded focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-magenta"
							>
								{say(item.labelKey)}
							</button>
						))}
					</nav>
				</div>
				{/* `gap-3`, not `gap-4`: this row carries one more control than it
				    did — the phone menu button — and four of them at 44px need the
				    tighter gutter to clear the wordmark at 390px. */}
				<div className="flex items-center gap-3">
					{/* AUTHENTICATION STATE, not a hardcoded invitation.
					 *
					 * This said "Sign in" unconditionally, so a reader who had just
					 * signed in was told, in the top right of the first page they
					 * landed on, that they had not. `AccountControl` reads the same
					 * session store the chat rail does -- one source, both surfaces.
					 *
					 * Nothing renders until `resolved`, because the alternative is the
					 * flash: "Sign in" paints, the session resolves a tick later, and
					 * the control swaps under the reader's eyes. */}
					{!resolved ? (
						// Holds the row's height so the header does not jump. 44px,
						// which is what the controls that replace it measure.
						<div aria-hidden="true" className="w-[92px] h-11" />
					) : signedIn ? (
						<>
							{/* THE WAY BACK IN. Without this the only route from the
							 * landing page to your own workspace was to pick a guide
							 * card again -- which is onboarding, and a returning
							 * reader has already done it. */}
							<button
								type="button"
								onClick={openWorkspace}
								className="hidden sm:inline-flex items-center gap-2 min-h-11 rounded-full bg-plum px-5 text-sm font-semibold text-white hover:bg-plum-deep transition-colors cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-magenta"
							>
								{continueLabel}
								<i className="ph-bold ph-arrow-right" aria-hidden="true" />
							</button>
							<AccountControl variant="corner" />
						</>
					) : (
						<button
							type="button"
							onClick={() => navigate({ to: "/signin" })}
							className="hidden sm:block text-sm font-semibold text-ink/70 hover:text-ink transition-colors px-4 py-2 cursor-pointer"
						>
							Sign in
						</button>
					)}
					<button
						type="button"
						onClick={() => setActiveView("history")}
						aria-label="View learning history"
						className="w-11 h-11 rounded-full border border-[var(--control-line)] flex items-center justify-center text-plum bg-white hover:bg-magenta/10 hover:text-magenta hover:border-magenta transition-colors cursor-pointer"
					>
						<i
							className="ph-duotone ph-magic-wand text-lg"
							aria-hidden="true"
						></i>
					</button>

					{/* THE PHONE HAD NO NAVIGATION AT ALL.
					 *
					 * The nav is `hidden md:flex` and Sign in is `hidden sm:block`, and
					 * nothing replaced either below those widths — no menu button, no
					 * drawer, no duplicate link anywhere on the page. So on a phone,
					 * Explore, Journey, For Parents, For Educators, About ASPIRE and
					 * Sign in were all unreachable. Two of those six are the pages
					 * written for the adults, on a government service where the phone
					 * is the majority case. */}
					<button
						ref={menuButtonRef}
						type="button"
						className="md:hidden w-11 h-11 rounded-full border border-[var(--control-line)] flex items-center justify-center text-plum bg-white hover:bg-magenta/10 hover:text-magenta hover:border-magenta transition-colors cursor-pointer"
						aria-expanded={menuOpen}
						aria-controls="landing-menu"
						aria-label={menuOpen ? "Close menu" : "Open menu"}
						onClick={() => setMenuOpen((open) => !open)}
					>
						<i
							className={`ph-bold ${menuOpen ? "ph-x" : "ph-list"} text-xl`}
							aria-hidden="true"
						></i>
					</button>
				</div>
			</header>

			{menuOpen ? (
				<>
					{/* A scrim, so a tap anywhere else closes it — and so the page
					    behind reads as unavailable while it is open. */}
					<button
						type="button"
						className="md:hidden fixed inset-0 z-20 bg-ink/25 cursor-default"
						aria-label="Close menu"
						onClick={() => setMenuOpen(false)}
					/>
					<nav
						id="landing-menu"
						ref={menuRef}
						className="md:hidden fixed left-3 right-3 top-[86px] z-30 rounded-2xl border border-[var(--control-line)] bg-white shadow-[0_24px_60px_-12px_rgb(30_10_55/0.35)] p-2 flex flex-col"
					>
						{NAV.map((item) => (
							<button
								key={item.view}
								type="button"
								onClick={() => {
									setMenuOpen(false);
									setActiveView(item.view);
								}}
								className="min-h-11 px-4 rounded-xl text-left text-base font-semibold text-ink hover:bg-plum/5 transition-colors cursor-pointer"
							>
								{say(item.labelKey)}
							</button>
						))}
						<span className="h-px bg-plum/10 my-2 mx-4" aria-hidden="true" />
						<button
							type="button"
							onClick={() => {
								setMenuOpen(false);
								navigate({ to: "/signin" });
							}}
							className="min-h-11 px-4 rounded-xl text-left text-base font-semibold text-plum hover:bg-plum/5 transition-colors cursor-pointer"
						>
							Sign in
						</button>
					</nav>
				</>
			) : null}

			{/* Main Content */}
			<main className="relative z-10 flex-1 w-full px-4 sm:px-8 flex flex-col justify-center">
				{/* Hero Section */}
				<div className="max-w-4xl mb-5 relative z-10 landing-hero">
					{/* It is a question, so it ends in a question mark.
					 *
					 * The exclamation was doing the work the sentence already does, and
					 * the emphasis span under it was a three-stop gradient — magenta to
					 * plum to ink — which is the one treatment that reads as generated
					 * no matter how good the type is. The italic serif in one brand
					 * colour says the same thing and stays readable when the gradient's
					 * dark end lands over the dark end of the photograph behind it. */}
					<h1 className="text-5xl md:text-6xl lg:text-[4.75rem] font-display font-medium text-ink leading-[1.05] mb-2 tracking-tight drop-shadow-sm">
						Where will your
						<br />
						money <span className="italic text-magenta">take you?</span>
					</h1>
					<p className="text-lg md:text-xl text-plum font-medium mb-4 tracking-wide">
						Ask. Play. Explore. Build your money future.
					</p>

					{/* Search / Ask Input
					 *
					 * Elevation is declared once. This carried a border, a wide soft
					 * shadow AND a white `ring-1` — three edges on one box, which is
					 * what makes a card look pasted onto the page rather than resting
					 * on it. The border and the shadow stay; the ring is gone. */}
					<div className="relative bg-white/85 backdrop-blur-2xl border border-[var(--control-line)] rounded-2xl p-4 flex flex-col shadow-[0_15px_40px_rgb(72_41_119/0.1)] transition-colors duration-300 hover:border-magenta max-w-2xl">
						<input
							type="text"
							value={draft}
							onChange={(e) => setDraft(e.target.value)}
							onKeyDown={handleKeyDown}
							aria-label="Ask a question about money or ASPIRE"
							placeholder="Ask me anything about money or ASPIRE..."
							className="bg-transparent text-lg text-ink placeholder-quiet focus:outline-none py-2 px-2 w-full mb-3 font-medium"
						/>

						<div className="flex items-end justify-between border-t border-plum/10 pt-3 px-1">
							<div className="flex flex-col">
								{/* The uppercase "CHOOSE YOUR GUIDE" that sat here was a kicker
								 * — 9px, letterspaced, and hand-indented `ml-[28px]` to line
								 * up with a control it was not attached to. A label on a
								 * `select` is the same information with none of the costume,
								 * and it reaches a screen reader, which the span never did.
								 * The visible name of the guide is the label the eye needs. */}
								{/* THE OPTIONS WERE THE WRONG IDS, and the dropdown quietly
								 * chose nobody for four of the five guides.
								 *
								 * It was populated from `PERSONAS`, whose ids are persona
								 * KEYS -- `stella`, `orion`, `aurora`, `nova` -- and the
								 * result was stored as a `GuideId`, which is `skye`, `zion`,
								 * `imani`, `azuri`. Only `kaleb` spells the same in both, so
								 * only Kaleb worked: every other choice put a key into
								 * `GUIDE_TO_PERSONA`, missed, and started the conversation
								 * with no persona at all. An `as GuideId` cast was holding
								 * the two apart.
								 *
								 * Driven from `GUIDES` now, which carries the guide id, the
								 * persona key and the band together -- and which the row
								 * below already uses, so the two controls on this page
								 * cannot disagree about who Skye is.
								 *
								 * Guest also appeared twice: once as the empty option and
								 * again from `PERSONAS`, which gained a `guest` row when it
								 * gained Kaleb. `GUIDES` is filtered to the five, so the
								 * empty option is the only Guest.
								 */}
								<div className="flex items-center gap-2">
									{selected ? (
										<span
											className="w-7 h-7 rounded-full bg-cover bg-top shrink-0 ring-2"
											style={
												{
													backgroundImage: `image-set(url("/guides/${selected.guideId}.webp") type("image/webp"), url("/guides/${selected.guideId}.png") type("image/png"))`,
													// The ring the guide is remembered by, read off the
													// guide itself — this was a sixth copy of the five
													// colours, and it had drifted: Kaleb was #3B82F6 here
													// and #2F7FE9 in the row below.
													"--tw-ring-color": selected.colour,
												} as React.CSSProperties
											}
											aria-hidden="true"
										/>
									) : (
										<i className="ph-duotone ph-user text-plum/60 text-lg"></i>
									)}
									<select
										aria-label="Choose your guide"
										value={selectedPersona || ""}
										onChange={(e) => {
											const chosen = (e.target.value || null) as GuideId | null;
											setSelectedPersona(chosen);
											rememberGuide(chosen);
										}}
										className="appearance-none bg-transparent border-none text-sm font-semibold text-plum outline-none cursor-pointer hover:text-magenta transition-colors"
									>
										<option value="" className="bg-white">
											Guest
										</option>
										{GUIDES.filter((g) => g.guideId !== "guest").map((g) => (
											<option
												key={g.guideId}
												value={g.guideId}
												className="bg-white text-ink"
											>
												{g.name} &middot; {g.audience}
											</option>
										))}
									</select>
									<i className="ph-bold ph-caret-down text-plum/40 text-xs -ml-1"></i>
								</div>
							</div>

							<div className="flex items-center gap-2">
								{/* This had no `onClick`. It was drawn, labelled "Voice input",
								 * and did nothing at all — on the front door of a service
								 * built for five-year-olds, where the microphone is the way
								 * in for a reader who cannot yet type. It opens a
								 * conversation with the mic live now; see `stageVoiceStart`. */}
								<button
									type="button"
									onClick={startByVoice}
									aria-label="Ask out loud"
									title="Ask out loud"
									className="w-11 h-11 rounded-full flex items-center justify-center transition-colors bg-magenta/5 text-magenta hover:bg-magenta/10 border border-magenta/25 cursor-pointer"
								>
									<i className="ph-bold ph-microphone text-lg"></i>
								</button>
								{/* Solid, not a gradient. The two-stop fill and the coloured
								 * halo on hover were the only place on this page where a
								 * control was painted differently from every control in the
								 * app it opens. */}
								<button
									type="button"
									onClick={() => startConversation(draft)}
									disabled={!draft.trim()}
									aria-label="Send message"
									className="w-11 h-11 rounded-full bg-magenta flex items-center justify-center text-white shadow-sm disabled:opacity-40 disabled:cursor-not-allowed hover:bg-magenta-deep transition-colors cursor-pointer"
								>
									<i className="ph-bold ph-paper-plane-right text-base"></i>
								</button>
							</div>
						</div>
					</div>

					{/* Floating progress widget, and only when there is progress.
					 *
					 * With the invented level and XP gone this rendered as a white box
					 * containing one cheerful line and nothing else -- worse than the
					 * fabricated version, because at least that looked deliberate.
					 * It returns the moment there is a real balance to put in it. */}
					{coinBalance !== null && (
						<button
							type="button"
							className="hidden lg:flex text-left absolute top-0 right-0 lg:translate-x-12 xl:translate-x-24 bg-white/90 backdrop-blur-2xl border border-plum/20 rounded-2xl p-4 flex-col gap-1 shadow-[0_20px_50px_rgba(72,41,119,0.15)] animate-float-slow z-20 hover:scale-105 transition-transform cursor-pointer group w-64"
							onClick={() => setActiveView("journey")}
						>
							<div className="text-ink text-sm font-bold mb-1">
								You're on your way!
							</div>
							{/* The progress bar and "720 / 1,000 XP" were literals, and a bar
							 * was the wrong shape for the number anyway: a balance is earned
							 * AND SPENT, so spending would run it backwards and read as a
							 * punishment for using what you earned. A bar only ever goes up.
							 *
							 * So this is one figure, not a bar. The honest source is the
							 * cumulative earned total; it is not wired here because the
							 * landing page is answered before anyone has signed in.
							 * `coinBalance` stays null until there is a session to read,
							 * and the row simply does not render.
							 */}
							{coinBalance !== null && (
								<div className="flex items-center gap-2 border-t border-plum/10 pt-2 mt-1 w-full">
									{/* amber-700, not #fed141: the brand gold is 1.46:1 on white and fails AA.
									 * It stays gold on the dark cards, where it measures 12:1. */}
									<i className="ph-fill ph-coin text-gold-ink text-sm drop-shadow-sm"></i>
									<span className="text-xs text-plum font-bold">
										{COIN_LABEL}
									</span>
									<span className="text-xs text-ink font-black ml-auto">
										{coinBalance}
									</span>
								</div>
							)}
						</button>
					)}
				</div>

				{/* The four ways in.
				 *
				 * They were four cards on one dark ground wearing four unrelated
				 * accents — magenta, then Tailwind's blue-500, then rose-500, then
				 * the brand gold. Two of those four are not ASPIRE colours at all,
				 * and a row where every tile picks its own hue is the surest sign a
				 * layout was assembled rather than designed. Each also carried a
				 * zero-offset coloured halo (`drop-shadow-[0_0_20px_...]`), a lift on
				 * the card AND a lift on the icon inside it, and a 28px caret circle
				 * that looked like a button on a card that was already a button.
				 *
				 * One accent now, and the icon is what tells them apart — which is
				 * the job an icon is for. The dark ground stays: it is the one place
				 * this page turns the contrast up, and it is what makes the row read
				 * as the way in rather than as more page.
				 */}
				<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-5 relative z-10 landing-cards">
					{WAYS_IN.map((way) => (
						<button
							key={way.title}
							type="button"
							onClick={() => way.go({ startConversation, setActiveView })}
							className="group relative overflow-hidden rounded-2xl bg-gradient-to-br from-[var(--surface-night)] to-[var(--surface-night-deep)] border border-plum/50 p-5 text-left transition-colors duration-300 hover:border-magenta flex flex-row items-center justify-between gap-3 h-32 cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-magenta-light"
						>
							<div className="flex flex-col justify-center h-full z-10 min-w-0 flex-1">
								<div className="flex items-center gap-2 mb-1">
									<h3 className="text-xl font-display font-semibold text-white">
										{way.title}
									</h3>
									{way.badge ? (
										<span className="bg-magenta text-white text-[10px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wider">
											{way.badge}
										</span>
									) : null}
								</div>
								<p className="text-magenta-light font-medium text-xs mb-1">
									{way.dek}
								</p>
								<p className="text-white/70 text-xs leading-snug line-clamp-2">
									{way.blurb}
								</p>
							</div>
							<i
								className={`${way.icon} text-[3.5rem] text-white/85 shrink-0 transition-transform duration-300 group-hover:-translate-y-0.5`}
								aria-hidden="true"
							></i>
						</button>
					))}
				</div>

				{/* `pb-10`: this row sat flush against the footer, so the guides card
				    and the Saint Kitts and Nevis line touched with nothing between
				    them. A closing line deserves its own air. */}
				<div className="grid grid-cols-1 lg:grid-cols-12 gap-6 relative z-10 pb-4 landing-lower">
					{/* Three quick questions, in one treatment.
					 *
					 * The chips carried three icon wells in three unrelated Tailwind
					 * greys-of-a-hue — `bg-fuchsia-50`, `bg-amber-50`, `bg-indigo-50` —
					 * with three different icon colours and three different hover
					 * borders, none of which meant anything. Their captions were 10px,
					 * under the floor at which small type stays readable. */}
					<div className="lg:col-span-7">
						<h3 className="text-base font-semibold text-ink mb-3">
							Try something quick
						</h3>
						<div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
							{QUICK_ASKS.map((ask) => (
								<button
									key={ask.title}
									type="button"
									onClick={() => startConversation(ask.question)}
									className="bg-white/90 backdrop-blur-xl border border-[var(--control-line)] rounded-2xl p-3 flex flex-col items-start gap-2 hover:border-magenta transition-colors cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-magenta"
								>
									<div className="w-11 h-11 rounded-xl bg-plum/5 flex items-center justify-center text-plum">
										<i
											className={`${ask.icon} text-2xl`}
											aria-hidden="true"
										></i>
									</div>
									<div className="text-left mt-1">
										<div className="text-sm font-bold text-ink leading-tight mb-0.5">
											{ask.title}
										</div>
										<div className="text-xs font-medium text-slate leading-tight">
											{ask.caption}
										</div>
									</div>
								</button>
							))}
						</div>
					</div>

					{/* Meet your guides.
					 *
					 * Was five 56px icon circles with a phosphor glyph each -- a
					 * butterfly for Skye, a rocket for Kaleb. Illustrated guides exist
					 * now, so the face does the work the glyph was standing in for, and
					 * the audience pill above it answers "which one is mine?" before the
					 * reader has to know who any of them are.
					 *
					 * `compact` rather than the designed `hero` size: this page holds
					 * itself to one viewport with no scroll, and the row it replaces was
					 * 124px tall with nothing spare. See `.guide-selector--compact`.
					 */}
					<div className="lg:col-span-5">
						<GuideSelector
							size="compact"
							selected={selectedPersona}
							onChoose={(choice) => {
								setSelectedPersona(choice.guideId as GuideId);
								// Survives the navigation, the refresh, and the trip through
								// sign-up: a visitor who picks Kaleb and then creates an
								// account must not be handed Guest on the other side.
								rememberGuide(choice.guideId);
								// No staged question: see `startConversation`.
								startConversation(null, choice.persona, choice.band ?? null);
							}}
						/>
					</div>
				</div>
			</main>

			{/* Institutional Footer */}
			<footer className="relative z-10 w-full border-t border-plum/10 bg-white/90 backdrop-blur-xl mt-auto">
				<div className="w-full px-4 sm:px-8 py-3 flex flex-wrap gap-6 items-center justify-between">
					{/* THREE STATISTICS WERE HERE, AND NONE OF THEM WERE TRUE.
					 *
					 * "4,200+ young learners", "18,745 lessons completed" and
					 * "2.1M+ Magic Coins earned" were literals written during a
					 * design pass. On a Government of St Kitts and Nevis service
					 * those are published claims about programme adoption, and
					 * anyone may quote them back.
					 *
					 * Deleted rather than zeroed: a placeholder number is still a
					 * number a reader believes. The band is left in place so real
					 * counts can be dropped in when there is an endpoint to serve
					 * them.
					 */}

					<div className="flex items-center gap-4">
						{/* Rose-50 and rose-500 were the only rose on the site. */}
						<div className="w-10 h-10 rounded-full bg-magenta/10 flex items-center justify-center shrink-0">
							<i
								className="ph-duotone ph-heart text-xl text-magenta"
								aria-hidden="true"
							></i>
						</div>
						<div>
							<div className="text-sm text-slate font-semibold">
								For a stronger Saint Kitts &amp; Nevis
							</div>
							{/* The flag emoji that closed this line does not exist on
							 * Windows or on most desktop browsers: the regional-indicator
							 * pair falls back to the letters, so the tagline shipped
							 * reading "Our choice. KN". A national flag is not something to
							 * leave to font coverage. */}
							<div className="text-ink font-bold">Our future. Our choice.</div>
						</div>
					</div>

					{/* WHO RUNS THIS, AND HOW TO REACH A PERSON.
					 *
					 * The footer carried a tagline and nothing else -- no owning
					 * body, no contact, no way off the bot. On a Government of St
					 * Kitts and Nevis service that is the one thing a footer cannot
					 * leave out, and it matters most for the reader the assistant
					 * has just declined to answer.
					 *
					 * Every value here is the one the backend already publishes --
					 * `config.aspire_contact_*` and the Ministry line the persona
					 * cards give verbatim. Nothing is typed in fresh: an invented
					 * government phone number is worse than no phone number.
					 *
					 * Kept to the same single row so the page still measures 900px
					 * in a 900px viewport. The row was `justify-between` with one
					 * child, so this costs width that was already empty, not height.
					 */}
					<div className="flex flex-col gap-0.5 text-right text-[11px] leading-snug text-slate">
						<div className="font-semibold text-ink">
							A programme of the Government of St Kitts &amp; Nevis &middot;
							Ministry of Social Development and Gender Affairs
						</div>
						<div>
							<a
								className="underline underline-offset-2 hover:text-magenta"
								href="tel:+18694671275"
							>
								(869) 467-1275
							</a>{" "}
							&middot;{" "}
							<a
								className="underline underline-offset-2 hover:text-magenta"
								href="tel:+18696675566"
							>
								+1 (869) 667-5566
							</a>{" "}
							&middot;{" "}
							<a
								className="underline underline-offset-2 hover:text-magenta"
								href="mailto:aspire@gov.kn"
							>
								aspire@gov.kn
							</a>{" "}
							&middot; The Cable Office, Cayon Street, Basseterre &middot;
							Mon&ndash;Fri 9&ndash;3
						</div>
					</div>
				</div>
			</footer>
		</div>
	);
}
