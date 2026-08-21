import React, { useState } from 'react';
import { useNavigate } from "@tanstack/react-router";
import { Brandmark } from './Brandmark';
import { HistoryView } from './HistoryView';
import { JourneyView } from './JourneyView';
import { StoriesView } from './StoriesView';
import { ParentsView } from './ParentsView';
import { EducatorsView } from './EducatorsView';
import { AboutView } from './AboutView';
import { stageFirstTurn } from "#/lib/aspire/handoff";
import type { PersonaId } from "#/lib/aspire/personas";

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

type ViewState = 'landing' | 'chat' | 'history' | 'journey' | 'stories' | 'parents' | 'educators' | 'about';
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
type GuideId = 'skye' | 'kaleb' | 'zion' | 'imani' | 'azuri';

/** Label to key. `skye` and `kaleb` are one key; the band decides the voice. */
const GUIDE_TO_PERSONA: Record<GuideId, PersonaId> = {
	skye: 'stella',
	kaleb: 'stella',
	zion: 'orion',
	imani: 'aurora',
	azuri: 'nova',
};

interface LandingScreenProps {
	onStartConversation?: (message: string) => void;
}

const PERSONAS = [
	{ id: 'skye', name: 'Skye', icon: '🦋', color: 'bg-[#c22f99]' },
	{ id: 'kaleb', name: 'Kaleb', icon: '🚀', color: 'bg-[#3b82f6]' },
	{ id: 'zion', name: 'Zion', icon: '🎧', color: 'bg-[#fed141]' },
	{ id: 'imani', name: 'Imani', icon: '📚', color: 'bg-[#482977]' },
	{ id: 'azuri', name: 'Azuri', icon: '👩🏾‍🏫', color: 'bg-[#10b981]' },
] as const;

export function LandingScreen({ onStartConversation }: LandingScreenProps) {
	const navigate = useNavigate();
	const [draft, setDraft] = useState("");
	const [activeView, setActiveView] = useState<ViewState>('landing');
	const [selectedPersona, setSelectedPersona] = useState<GuideId | null>(null);

	const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
		if (e.key === "Enter" && draft.trim()) {
			startConversation(draft);
		}
	};

	const startConversation = (message: string, persona?: PersonaId | null) => {
		if (onStartConversation) {
			onStartConversation(message);
		} else {
			const threadId = crypto.randomUUID();
			stageFirstTurn({
				threadId,
				question: message,
				simple: false,
				language: "en"
			});
			// The guide rides the address, which is where the chat reads it from
			// (`validateAnswerSearch`). Until now `selectedPersona` was set by the
			// dropdown and then dropped on the floor: choosing a guide on this page
			// changed nothing at all about who answered.
			const chosen =
				persona ?? (selectedPersona ? GUIDE_TO_PERSONA[selectedPersona] : null);
			navigate({
				to: "/chat/$chatId",
				params: { chatId: threadId },
				...(chosen ? { search: { persona: chosen } } : {}),
			});
		}
	};

	if (activeView === 'history') {
		return <HistoryView onBack={() => setActiveView('landing')} onSelectChat={(id) => navigate({ to: "/chat/$chatId", params: { chatId: id } })} />;
	}

	if (activeView === 'journey') {
		return <JourneyView onBack={() => setActiveView('landing')} />;
	}

	if (activeView === 'parents') return <ParentsView onBack={() => setActiveView('landing')} />;
	if (activeView === 'educators') return <EducatorsView onBack={() => setActiveView('landing')} />;
	if (activeView === 'about') return <AboutView onBack={() => setActiveView('landing')} />;

	if (activeView === 'stories') {
		return <StoriesView onBack={() => setActiveView('landing')} />;
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
		<div className="relative h-dvh overflow-y-auto overflow-x-hidden bg-white flex flex-col font-sans selection:bg-[#c22f99]/20 text-[#1A103C]">

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
			<div className="fixed inset-0 pointer-events-none z-0 overflow-hidden bg-[#F4F0FA]">
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
						filter: 'saturate(1.0) brightness(1.0)'
					}}
				></div>
			</div>

			{/* Elegant Header */}
			<header className="relative z-10 w-full max-w-[90rem] mx-auto px-4 sm:px-8 pt-6 pb-4 flex items-center justify-between">
				<div className="flex items-center gap-8">
					<Brandmark variant="header" />
					<nav className="hidden md:flex items-center gap-6 text-sm font-semibold">
						<button type="button" onClick={() => setActiveView('stories')} className="text-[#c22f99] hover:text-[#8a1c6a] transition-colors font-bold cursor-pointer">Explore</button>
						<button type="button" onClick={() => setActiveView('journey')} className="text-[#1A103C]/70 hover:text-[#1A103C] transition-colors cursor-pointer">Journey</button>
						<button type="button" onClick={() => setActiveView('parents')} className="text-[#1A103C]/70 hover:text-[#1A103C] transition-colors font-bold cursor-pointer">For Parents</button>
						<button type="button" onClick={() => setActiveView('educators')} className="text-[#1A103C]/70 hover:text-[#1A103C] transition-colors font-bold cursor-pointer">For Educators</button>
						<button type="button" onClick={() => setActiveView('about')} className="text-[#1A103C]/70 hover:text-[#1A103C] transition-colors font-bold cursor-pointer">About ASPIRE</button>
					</nav>
				</div>
				<div className="flex items-center gap-4">
					<button type="button" onClick={() => navigate({ to: "/signin" })} className="hidden sm:block text-sm font-semibold text-[#1A103C]/70 hover:text-[#1A103C] transition-colors px-4 py-2 cursor-pointer">
						Sign in
					</button>
					<button type="button" onClick={() => setActiveView('history')} aria-label="View learning history" className="w-10 h-10 rounded-full border border-[#482977]/20 flex items-center justify-center text-[#482977] bg-white hover:bg-[#F8E7F0] hover:text-[#c22f99] hover:border-[#c22f99]/30 transition-all shadow-sm cursor-pointer">
						<i className="ph-duotone ph-magic-wand text-lg"></i>
					</button>
				</div>
			</header>

			{/* Main Content */}
			<main className="relative z-10 flex-1 w-full max-w-[90rem] mx-auto px-4 sm:px-8 flex flex-col justify-center">
				
				{/* Hero Section */}
				<div className="max-w-4xl mb-5 relative z-10">
					<h1 className="text-5xl md:text-6xl lg:text-[4.75rem] font-display font-medium text-[#1A103C] leading-[1.05] mb-2 tracking-tight drop-shadow-sm">
						Where will your<br />money <span className="italic text-transparent bg-clip-text bg-gradient-to-r from-[#c22f99] via-[#482977] to-[#1A103C] pr-2">take you!</span>
					</h1>
					<p className="text-lg md:text-xl text-[#482977] font-medium mb-4 tracking-wide">
						Ask. Play. Explore. Build your money future.
					</p>

					{/* Search / Ask Input */}
					<div className="relative bg-white/80 backdrop-blur-2xl border border-[#482977]/20 rounded-[1.5rem] p-4 flex flex-col shadow-[0_15px_40px_rgba(72,41,119,0.1)] ring-1 ring-white hover:ring-[#c22f99]/20 transition-all duration-500 max-w-2xl">
						<input
							type="text"
							value={draft}
							onChange={(e) => setDraft(e.target.value)}
							onKeyDown={handleKeyDown}
							placeholder="Ask me anything about money or ASPIRE..."
							className="bg-transparent text-lg text-[#1A103C] placeholder-[#1A103C]/40 focus:outline-none py-2 px-2 w-full mb-3 font-medium"
						/>
						
						<div className="flex items-end justify-between border-t border-[#482977]/10 pt-3 px-1">
							<div className="flex flex-col">
								<span className="text-[9px] font-bold uppercase tracking-wider text-[#482977]/60 mb-1 ml-[28px]">Choose your guide</span>
								<div className="flex items-center gap-2">
									<i className="ph-duotone ph-user text-[#482977]/60 text-lg"></i>
									<select 
										value={selectedPersona || ""} 
										onChange={(e) => setSelectedPersona(e.target.value as GuideId)}
										className="appearance-none bg-transparent border-none text-sm font-semibold text-[#482977] outline-none cursor-pointer hover:text-[#c22f99] transition-colors"
									>
										<option value="" className="bg-white">Guest</option>
										{PERSONAS.map(p => (
											<option key={p.id} value={p.id} className="bg-white text-[#1A103C]">{p.name}</option>
										))}
									</select>
									<i className="ph-bold ph-caret-down text-[#482977]/40 text-xs -ml-1"></i>
								</div>
							</div>
							
							<div className="flex items-center gap-2">
								<button 
									type="button"
									aria-label="Voice input"
									className="w-10 h-10 rounded-full flex items-center justify-center transition-colors bg-[#F8E7F0]/50 text-[#c22f99] hover:bg-[#F8E7F0] ring-1 ring-[#c22f99]/20 cursor-pointer"
								>
									<i className="ph-bold ph-microphone text-lg"></i>
								</button>
								<button 
									type="button"
									onClick={() => startConversation(draft)}
									disabled={!draft.trim()}
									aria-label="Send message"
									className="w-10 h-10 rounded-full bg-gradient-to-r from-[#c22f99] to-[#8a1c6a] flex items-center justify-center text-white shadow-md disabled:opacity-50 disabled:cursor-not-allowed hover:shadow-[0_4px_15px_rgba(194,47,153,0.4)] transition-all cursor-pointer"
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
						className="hidden lg:flex text-left absolute top-0 right-0 lg:translate-x-12 xl:translate-x-24 bg-white/90 backdrop-blur-2xl border border-[#482977]/20 rounded-2xl p-4 flex-col gap-1 shadow-[0_20px_50px_rgba(72,41,119,0.15)] animate-float-slow z-20 hover:scale-105 transition-transform cursor-pointer group w-64" 
						onClick={() => setActiveView("journey")}
					>
						<div className="text-[#1A103C] text-sm font-bold mb-1">You're on your way!</div>
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
							<div className="flex items-center gap-2 border-t border-[#482977]/10 pt-2 mt-1 w-full">
								{/* amber-700, not #fed141: the brand gold is 1.46:1 on white and fails AA.
								  * It stays gold on the dark cards, where it measures 12:1. */}
								<i className="ph-fill ph-coin text-[#b45309] text-sm drop-shadow-sm"></i>
								<span className="text-xs text-[#482977] font-bold">{COIN_LABEL}</span>
								<span className="text-xs text-[#1A103C] font-black ml-auto">{coinBalance}</span>
							</div>
						)}
					</button>
					)}
				</div>

				{/* Cards Grid - Restored to Deep Brand Colors */}
				<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-5 relative z-10">
					
					{/* Ask ASPIRE Card */}
					<button type="button" onClick={() => startConversation("Hello ASPIRE, I am ready to explore the financial and learning ecosystem in St. Kitts and Nevis.")} className="group relative overflow-hidden rounded-3xl bg-gradient-to-br from-[#231548] to-[#100727] shadow-xl border border-[#482977]/50 p-5 text-left transition-all duration-500 hover:-translate-y-1 hover:shadow-[0_15px_30px_rgba(194,47,153,0.3)] hover:border-[#c22f99] flex flex-row items-center justify-between h-32 cursor-pointer">
						<div className="flex flex-col justify-between h-full z-10 w-[60%]">
							<div>
								<div className="flex items-center gap-2 mb-1">
									<h3 className="text-xl font-display font-semibold text-white">Ask ASPIRE</h3>
									<span className="bg-[#c22f99] text-white text-[9px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wider">New</span>
								</div>
								<p className="text-[#c22f99] font-medium text-xs mb-1 drop-shadow-md">Your AI Guide</p>
								<p className="text-white/70 text-xs leading-snug line-clamp-2">Get smart answers to your money questions.</p>
							</div>
							<div className="mt-2 w-7 h-7 rounded-full border border-white/20 flex items-center justify-center group-hover:bg-white/10 transition-colors text-white">
								<i className="ph-bold ph-caret-right text-xs"></i>
							</div>
						</div>
						<div className="absolute right-0 top-0 bottom-0 w-[40%] bg-gradient-to-l from-[#c22f99]/20 to-transparent"></div>
						<div className="relative z-10 w-[40%] flex justify-end">
							<i className="ph-duotone ph-robot text-[4rem] text-white/90 group-hover:scale-110 group-hover:-translate-y-1 transition-transform duration-500 drop-shadow-[0_0_20px_rgba(194,47,153,0.6)]"></i>
						</div>
					</button>

					{/* Play Card */}
					<button type="button" onClick={() => startConversation("Start the ASPIRE savings challenge to help me manage my 1,000 XCD youth grant.")} className="group relative overflow-hidden rounded-3xl bg-gradient-to-br from-[#231548] to-[#100727] shadow-xl border border-[#482977]/50 p-5 text-left transition-all duration-500 hover:-translate-y-1 hover:shadow-[0_15px_30px_rgba(59,130,246,0.3)] hover:border-[#3b82f6] flex flex-row items-center justify-between h-32 cursor-pointer">
						<div className="flex flex-col justify-between h-full z-10 w-[60%]">
							<div>
								<h3 className="text-xl font-display font-semibold text-white mb-1">Play</h3>
								<p className="text-[#3b82f6] font-medium text-xs mb-1 drop-shadow-md">Today's Challenge</p>
								<p className="text-white/70 text-xs leading-snug line-clamp-2">Learn by doing. Earn coins and level up!</p>
							</div>
							<div className="mt-2 w-7 h-7 rounded-full border border-white/20 flex items-center justify-center group-hover:bg-white/10 transition-colors text-white">
								<i className="ph-bold ph-caret-right text-xs"></i>
							</div>
						</div>
						<div className="absolute right-0 top-0 bottom-0 w-[40%] bg-gradient-to-l from-[#3b82f6]/20 to-transparent"></div>
						<div className="relative z-10 w-[40%] flex justify-end items-center">
							<i className="ph-duotone ph-game-controller text-[4rem] text-blue-300 group-hover:scale-110 group-hover:-translate-y-1 transition-transform duration-500 drop-shadow-[0_0_20px_rgba(59,130,246,0.6)]"></i>
							<i className="ph-fill ph-coin text-2xl text-[#fed141] absolute -bottom-1 -left-2 animate-bounce drop-shadow-lg"></i>
						</div>
					</button>

					{/* Explore Card */}
					<button type="button" onClick={() => setActiveView("stories")} className="group relative overflow-hidden rounded-3xl bg-gradient-to-br from-[#231548] to-[#100727] shadow-xl border border-[#482977]/50 p-5 text-left transition-all duration-500 hover:-translate-y-1 hover:shadow-[0_15px_30px_rgba(244,63,94,0.3)] hover:border-[#f43f5e] flex flex-row items-center justify-between h-32 cursor-pointer">
						<div className="flex flex-col justify-between h-full z-10 w-[60%]">
							<div>
								<h3 className="text-xl font-display font-semibold text-white mb-1">Explore</h3>
								<p className="text-[#f43f5e] font-medium text-xs mb-1 drop-shadow-md">Miracle Mountain</p>
								<p className="text-white/70 text-xs leading-snug line-clamp-2">Listen to a story or watch an adventure.</p>
							</div>
							<div className="mt-2 w-7 h-7 rounded-full border border-white/20 flex items-center justify-center group-hover:bg-white/10 transition-colors text-white">
								<i className="ph-bold ph-caret-right text-xs"></i>
							</div>
						</div>
						<div className="absolute right-0 top-0 bottom-0 w-[40%] bg-gradient-to-l from-[#f43f5e]/20 to-transparent"></div>
						<div className="relative z-10 w-[40%] flex justify-end">
							<i className="ph-duotone ph-play-circle text-[4rem] text-rose-300 group-hover:scale-110 group-hover:-translate-y-1 transition-transform duration-500 drop-shadow-[0_0_20px_rgba(244,63,94,0.6)]"></i>
							<i className="ph-fill ph-sparkle text-xl text-[#fed141] absolute top-0 right-0 animate-pulse drop-shadow-lg"></i>
						</div>
					</button>

					{/* My Journey Card */}
					<button type="button" onClick={() => setActiveView("journey")} className="group relative overflow-hidden rounded-3xl bg-gradient-to-br from-[#231548] to-[#100727] shadow-xl border border-[#482977]/50 p-5 text-left transition-all duration-500 hover:-translate-y-1 hover:shadow-[0_15px_30px_rgba(254,209,65,0.3)] hover:border-[#fed141] flex flex-row items-center justify-between h-32 cursor-pointer">
						<div className="flex flex-col justify-between h-full z-10 w-[60%]">
							<div>
								<h3 className="text-xl font-display font-semibold text-white mb-1">My Journey</h3>
								<p className="text-[#fed141] font-medium text-xs mb-2 drop-shadow-md">Your progress path</p>
								{/* "3 Badges" and "7 Lessons" were here, hardcoded, and shown to
								  * every visitor including the ones who had never opened a
								  * lesson. Same defect as the footer statistics: a per-reader
								  * number that is the same for every reader is not a number.
								  * The card is a way in, so it says what is behind it. */}
								<p className="text-[10px] font-medium text-white/70">
									Badges and lessons, once you begin.
								</p>
							</div>
							<div className="mt-2 w-7 h-7 rounded-full border border-white/20 flex items-center justify-center group-hover:bg-white/10 transition-colors text-white">
								<i className="ph-bold ph-caret-right text-xs"></i>
							</div>
						</div>
						<div className="absolute right-0 top-0 bottom-0 w-[40%] bg-gradient-to-l from-[#fed141]/10 to-transparent"></div>
						<div className="relative z-10 w-[40%] flex justify-end items-center">
							<div className="w-[4rem] h-[4rem] rounded-full border-[4px] border-[#1A103C] border-t-[#fed141] border-r-[#fed141] flex items-center justify-center relative group-hover:rotate-45 transition-transform duration-700 shadow-lg bg-[#231548]">
								<i className="ph-fill ph-star text-[2rem] text-[#fed141] group-hover:-rotate-45 transition-transform duration-700 drop-shadow-[0_0_15px_rgba(254,209,65,0.6)]"></i>
							</div>
						</div>
					</button>
				</div>

				{/* `pb-10`: this row sat flush against the footer, so the guides card
				    and the Saint Kitts and Nevis line touched with nothing between
				    them. A closing line deserves its own air. */}
				<div className="grid grid-cols-1 lg:grid-cols-12 gap-6 relative z-10 pb-4">
					{/* Try something quick */}
					<div className="lg:col-span-7">
						<h3 className="text-base font-semibold text-[#1A103C] mb-3 flex items-center gap-2">
							<i className="ph-bold ph-lightning text-[#c22f99]"></i> Try something quick
						</h3>
						<div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
							<button type="button" onClick={() => startConversation('What exactly is the ASPIRE program in St. Kitts and Nevis?')} className="bg-white/90 backdrop-blur-xl border border-[#482977]/20 rounded-[1.25rem] p-3 flex flex-col items-start gap-2 hover:bg-white hover:border-[#c22f99]/50 transition-all group shadow-sm hover:shadow-md cursor-pointer">
								<div className="w-8 h-8 rounded-full bg-fuchsia-50 flex items-center justify-center text-[#c22f99]">
									<i className="ph-duotone ph-graduation-cap text-lg"></i>
								</div>
								<div className="text-left mt-1">
									<div className="text-sm font-bold text-[#1A103C] leading-tight mb-1">What is ASPIRE?</div>
									<div className="text-[10px] font-medium text-[#482977]/70 leading-tight">Learn the basics</div>
								</div>
							</button>
							<button type="button" onClick={() => startConversation('How can you get the Grant Money?')} className="bg-white/90 backdrop-blur-xl border border-[#482977]/20 rounded-[1.25rem] p-3 flex flex-col items-start gap-2 hover:bg-white hover:border-[#fed141]/50 transition-all group shadow-sm hover:shadow-md cursor-pointer">
								<div className="w-8 h-8 rounded-full bg-amber-50 flex items-center justify-center text-amber-500">
									<i className="ph-duotone ph-coins text-lg"></i>
								</div>
								<div className="text-left mt-1">
									<div className="text-sm font-bold text-[#1A103C] leading-tight mb-1">Grant Money</div>
									<div className="text-[10px] font-medium text-[#482977]/70 leading-tight">Learn about the ASPIRE grant</div>
								</div>
							</button>
							<button type="button" onClick={() => startConversation('Help me build wealth in St. Kitts and Nevis.')} className="bg-white/90 backdrop-blur-xl border border-[#482977]/20 rounded-[1.25rem] p-3 flex flex-col items-start gap-2 hover:bg-white hover:border-[#482977]/50 transition-all group shadow-sm hover:shadow-md cursor-pointer">
								<div className="w-8 h-8 rounded-full bg-indigo-50 flex items-center justify-center text-[#482977]">
									<i className="ph-duotone ph-chart-line-up text-lg"></i>
								</div>
								<div className="text-left mt-1">
									<div className="text-sm font-bold text-[#1A103C] leading-tight mb-1">SKN Wealth Builder</div>
									<div className="text-[10px] font-medium text-[#482977]/70 leading-tight">Build your future</div>
								</div>
							</button>
						</div>
					</div>

					{/* Meet your guides */}
					<div className="lg:col-span-5">
						<h3 className="text-base font-semibold text-[#1A103C] mb-3 flex items-center gap-2">
							<i className="ph-bold ph-users text-blue-500"></i> Meet your guides
						</h3>
						{/* Buttons, not decoration.
						  *
						  * These were `div`s carrying `cursor-pointer` and no handler:
						  * they looked clickable, did nothing, and no keyboard could
						  * reach them at all. Each one now opens a conversation with
						  * that guide answering.
						  *
						  * Skye and Kaleb are one persona key. `stella` is Skye at 5-8
						  * and Kaleb at 9-12, and the band comes from the session, not
						  * from the address -- so a signed-out reader picking Kaleb gets
						  * `stella`, and the server decides which voice that is. The
						  * alternative is asking a child their age on a landing page.
						  *
						  * `justify-center` so five circles sit balanced in the card
						  * rather than crowding the left edge.
						  */}
						<div className="bg-white/80 backdrop-blur-xl border border-[#482977]/20 rounded-[1.5rem] p-4 flex flex-wrap justify-center gap-4 shadow-sm">
							{[
								{ name: 'Skye', persona: 'stella' as PersonaId, who: 'ages 5 to 8', color: 'from-[#c22f99] to-pink-500', icon: 'ph-butterfly' },
								{ name: 'Kaleb', persona: 'stella' as PersonaId, who: 'ages 9 to 12', color: 'from-blue-500 to-cyan-500', icon: 'ph-rocket' },
								{ name: 'Zion', persona: 'orion' as PersonaId, who: 'ages 13 to 18', color: 'from-[#fed141] to-amber-500', icon: 'ph-headphones' },
								{ name: 'Imani', persona: 'aurora' as PersonaId, who: 'parents and guardians', color: 'from-[#482977] to-indigo-500', icon: 'ph-book-open' },
								{ name: 'Azuri', persona: 'nova' as PersonaId, who: 'teachers', color: 'from-emerald-500 to-teal-500', icon: 'ph-chalkboard-teacher' },
							].map(guide => (
								<button
									key={guide.name}
									type="button"
									onClick={() => startConversation("Hi! What can you help me with?", guide.persona)}
									aria-label={`Talk to ${guide.name}, for ${guide.who}`}
									className="flex flex-col items-center gap-2 flex-shrink-0 group rounded-2xl p-1 cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#c22f99]"
								>
									<span className={`w-14 h-14 rounded-full bg-gradient-to-br ${guide.color} p-[2px] shadow-sm group-hover:scale-110 transition-transform block`}>
										<span className="w-full h-full bg-[#1A103C] rounded-full border-[1.5px] border-[#1A103C] flex items-center justify-center relative overflow-hidden">
											<span className={`absolute inset-0 bg-gradient-to-br ${guide.color} opacity-20`}></span>
											<i className={`ph-duotone ${guide.icon} text-xl text-white drop-shadow-sm`} aria-hidden="true"></i>
										</span>
									</span>
									<span className="text-[11px] font-bold text-[#1A103C]">{guide.name}</span>
								</button>
							))}
						</div>
					</div>
				</div>
			</main>
			
			{/* Institutional Footer */}
			<footer className="relative z-10 w-full border-t border-[#482977]/10 bg-white/90 backdrop-blur-xl mt-auto">
				<div className="max-w-[90rem] mx-auto px-4 sm:px-8 py-3 flex flex-wrap gap-6 items-center justify-between">
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
						<div className="w-10 h-10 rounded-full bg-rose-50 flex items-center justify-center">
							<i className="ph-duotone ph-heart text-xl text-rose-500"></i>
						</div>
						<div>
							<div className="text-sm text-[#482977]/70 font-semibold">For a stronger Saint Kitts & Nevis</div>
							<div className="text-[#1A103C] font-bold">Our future. Our choice. 🇰🇳</div>
						</div>
					</div>
				</div>
			</footer>
		</div>
	);
}
