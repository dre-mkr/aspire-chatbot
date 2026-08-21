import { ViewHeader } from "./ViewHeader";
export function JourneyView({ onBack }: { onBack: () => void }) {
	return (
		<div className="flex flex-col min-h-screen bg-[#0B051D] text-white">
			<ViewHeader onBack={onBack} tone="dark" />
			<main className="flex-1 flex flex-col items-center justify-center p-8 text-center max-w-2xl mx-auto">
				<div className="w-24 h-24 rounded-full bg-gradient-to-br from-[#fed141] to-amber-600 flex items-center justify-center mb-8 shadow-[0_0_40px_rgba(254,209,65,0.4)]">
					<i className="ph-fill ph-medal text-5xl text-white"></i>
				</div>
				<h1 className="text-4xl font-display font-medium text-white mb-4">Your Financial Journey</h1>
				<p className="text-xl text-white/70 mb-12">
					Track your progress as you master new money skills, earn badges, and build your future in St. Kitts and Nevis.
				</p>
				
				<div className="w-full bg-white/5 rounded-3xl border border-white/10 p-8 text-left">
					{/* A LEVEL, AN XP TOTAL AND A 72%-FULL BAR WERE HERE, ALL LITERALS.
					  *
					  * Every visitor saw the same "Level 3 - Explorer, 720 / 1,000 XP",
					  * including the ones who had never answered a question. A progress
					  * display that is identical for a returning learner and a stranger
					  * is not a progress display.
					  *
					  * There is no signed-in reader on this page, so there is no progress
					  * to show. It says so instead of inventing one. Real progress is
					  * mastered concepts over `lessons_for_band(band)`, which needs a
					  * session -- so it belongs behind sign-in, not here.
					  */}
					<div className="mb-10">
						<h3 className="text-2xl font-bold text-white">Your progress lives with your account</h3>
						<p className="text-white/50 mt-1">
							Sign in and your badges, lessons and coins follow you here.
						</p>
					</div>

					{/* Below is the shape of the course, not anybody's place in it. */}
					<h4 className="font-semibold text-white/80 mb-6 uppercase tracking-wider text-sm">What you will learn</h4>
					<div className="relative">
						<div className="absolute top-5 left-6 right-6 h-1 bg-white/10 -z-10"></div>
						
						<div className="flex justify-between">
							<div className="flex flex-col items-center gap-3">
								<div className="w-12 h-12 rounded-full bg-white/10 text-white/60 border-2 border-white/20 flex items-center justify-center text-xl">
									<i className="ph-bold ph-book-open"></i>
								</div>
								<span className="text-xs font-medium text-white">Basics</span>
							</div>
							<div className="flex flex-col items-center gap-3">
								<div className="w-12 h-12 rounded-full bg-white/10 text-white/60 border-2 border-white/20 flex items-center justify-center text-xl">
									<i className="ph-bold ph-book-open"></i>
								</div>
								<span className="text-xs font-medium text-white">Saving</span>
							</div>
							<div className="flex flex-col items-center gap-3">
								<div className="w-12 h-12 rounded-full bg-white/10 text-white/60 border-2 border-white/20 flex items-center justify-center text-xl">
									<i className="ph-bold ph-book-open"></i>
								</div>
								<span className="text-xs font-medium text-white/70">Budgeting</span>
							</div>
							<div className="flex flex-col items-center gap-3">
								<div className="w-12 h-12 rounded-full bg-white/10 text-white/70 border-2 border-white/20 flex items-center justify-center text-xl">
									<i className="ph-bold ph-book-open"></i>
								</div>
								<span className="text-xs font-medium text-white/70">Investing</span>
							</div>
							<div className="flex flex-col items-center gap-3">
								<div className="w-12 h-12 rounded-full bg-white/10 text-white/70 border-2 border-white/20 flex items-center justify-center text-xl">
									<i className="ph-bold ph-book-open"></i>
								</div>
								<span className="text-xs font-medium text-white/70">Business</span>
							</div>
						</div>
					</div>
				</div>
			</main>
		</div>
	);
}
