import { ViewHeader } from "./ViewHeader";

interface EducatorsViewProps {
	onBack: () => void;
}

export function EducatorsView({ onBack }: EducatorsViewProps) {
	return (
		<div className="relative flex flex-col min-h-screen bg-white text-[#1A103C]">
			{/* Scenic Background Layers */}
			<div className="absolute inset-0 pointer-events-none z-0 overflow-hidden bg-white">
				<div 
					className="absolute inset-0" 
					style={{
						background: `
							linear-gradient(
								to bottom,
								rgba(255,255,255,0.12) 0%,
								rgba(255,255,255,0.58) 38%,
								rgba(255,255,255,0.92) 72%,
								#ffffff 100%
							),
							image-set(
								url('/images/hero-bg.webp') type('image/webp'),
								url('/images/hero-bg.jpg') type('image/jpeg')
							) center top / cover no-repeat
						`,
						filter: 'saturate(0.85) brightness(1.12)'
					}}
				></div>
			</div>
			
			<div className="relative z-10 flex flex-col flex-1">
			<ViewHeader onBack={onBack} />

			<main className="flex-1 w-full max-w-4xl mx-auto px-6 py-12">
				<div className="mb-12">
					<h1 className="text-4xl md:text-5xl font-display font-medium text-[#1A103C] mb-4">
						For Educators
					</h1>
					<p className="text-xl text-[#482977]/80">
						Empower the next generation with essential financial literacy.
					</p>
				</div>

				<div className="bg-white rounded-3xl p-8 shadow-sm border border-[#482977]/10 mb-8">
					<div className="flex flex-col md:flex-row gap-8 items-center">
						<div className="flex-1">
							<div className="w-12 h-12 rounded-full bg-emerald-100 flex items-center justify-center text-emerald-600 mb-6">
								<i className="ph-duotone ph-books text-2xl"></i>
							</div>
							<h3 className="text-2xl font-bold mb-4 text-[#1A103C]">The ASPIRE AI Financial Curriculum</h3>
							<p className="text-[#482977]/80 leading-relaxed mb-4">
								Educators are at the heart of ASPIRE&rsquo;s financial literacy
								programme. Developed by the ASPIRE AI team in collaboration with
								the Eastern Caribbean Central Bank, the curriculum introduces
								students to the ideas that will shape their financial futures
								&mdash; and gives every learner a guide who meets them at their
								own age.
							</p>
							<div className="flex flex-wrap gap-2 mt-4">
								<span className="bg-[#482977]/5 text-[#482977] px-3 py-1 rounded-full text-sm font-semibold">Budgeting</span>
								<span className="bg-[#482977]/5 text-[#482977] px-3 py-1 rounded-full text-sm font-semibold">Saving</span>
								<span className="bg-[#482977]/5 text-[#482977] px-3 py-1 rounded-full text-sm font-semibold">Investing</span>
								<span className="bg-[#482977]/5 text-[#482977] px-3 py-1 rounded-full text-sm font-semibold">Debt Management</span>
								<span className="bg-[#482977]/5 text-[#482977] px-3 py-1 rounded-full text-sm font-semibold">Entrepreneurship</span>
							</div>
						</div>
					</div>
				</div>

				<div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-12">
					<div className="bg-white rounded-3xl p-8 shadow-sm border border-[#482977]/10">
						<h3 className="text-xl font-bold mb-3 text-[#1A103C]">Educator Training</h3>
						<p className="text-[#482977]/80 leading-relaxed">
							The ASPIRE Programme hosts specialized Educator Training Sessions to equip teachers with the necessary knowledge and tools to teach financial literacy confidently in the classroom.
						</p>
					</div>

					<div className="bg-white rounded-3xl p-8 shadow-sm border border-[#482977]/10">
						<h3 className="text-xl font-bold mb-3 text-[#1A103C]">Interactive Learning</h3>
						<p className="text-[#482977]/80 leading-relaxed">
							Our AI-powered assistant and gamified learning paths help reinforce classroom lessons, allowing students to play, explore, and earn rewards while mastering the EC Dollar.
						</p>
					</div>
				</div>
			</main>
			</div>
		</div>
	);
}
