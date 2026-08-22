import { ViewHeader } from "./ViewHeader";

interface ParentsViewProps {
	onBack: () => void;
	/** Set by the rail's launcher, which closes a panel rather than navigating. */
	backLabel?: string;
}

export function ParentsView({ onBack, backLabel }: ParentsViewProps) {
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
			<ViewHeader onBack={onBack} backLabel={backLabel} />

			<main className="flex-1 w-full max-w-4xl mx-auto px-6 py-12">
				<div className="mb-12">
					<h1 className="text-4xl md:text-5xl font-display font-medium text-[#1A103C] mb-4">
						For Parents & Guardians
					</h1>
					<p className="text-xl text-[#482977]/80">
						Secure your child's financial future with the ASPIRE Programme.
					</p>
				</div>

				<div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-12">
					<div className="bg-white rounded-3xl p-8 shadow-sm border border-[#482977]/10">
						<div className="w-12 h-12 rounded-full bg-[#c22f99]/10 flex items-center justify-center text-[#c22f99] mb-6">
							<i className="ph-duotone ph-piggy-bank text-2xl"></i>
						</div>
						<h3 className="text-xl font-bold mb-3 text-[#1A103C]">The EC$1,000 Grant</h3>
						<p className="text-[#482977]/80 leading-relaxed mb-4">
							Every eligible child (ages 5-18) receives an EC$1,000 contribution from the Government of St. Kitts and Nevis:
						</p>
						<ul className="space-y-2 text-sm font-semibold text-[#1A103C]">
							<li className="flex items-center gap-2"><i className="ph-fill ph-check-circle text-emerald-500"></i> EC$500 in a savings account at the St. Kitts-Nevis-Anguilla National Bank</li>
							<li className="flex items-center gap-2"><i className="ph-fill ph-check-circle text-emerald-500"></i> EC$500 invested in shares of local government-owned entities</li>
						</ul>
					</div>

					<div className="bg-white rounded-3xl p-8 shadow-sm border border-[#482977]/10">
						<div className="w-12 h-12 rounded-full bg-[#fed141]/20 flex items-center justify-center text-amber-600 mb-6">
							<i className="ph-duotone ph-file-text text-2xl"></i>
						</div>
						<h3 className="text-xl font-bold mb-3 text-[#1A103C]">How to Register</h3>
						{/* Street and opening hours restored from the corpus. ASP-299 names
						  * Cayon Street; ASP-300 gives the hours. Naming a building without
						  * either sends a parent across Basseterre to a locked door, which is
						  * a worse outcome than not mentioning the walk-in centre at all. */}
						<p className="text-[#482977]/80 leading-relaxed mb-4">
							Register online at <strong>aspire.gov.kn</strong>, or in person at The Cable
							Office on Cayon Street in Basseterre — walk-in support is available
							Monday to Friday, 9:00 AM to 3:00 PM.
						</p>
						<p className="text-sm font-semibold text-[#1A103C]">What you'll need:</p>
						<ul className="space-y-1 text-sm text-[#482977]/80 mt-2">
							<li>• Parent/Guardian Valid ID</li>
							<li>• Child's SKN Birth Certificate or Passport</li>
							<li>• Recent proof of address (within 3 months)</li>
						</ul>
					</div>
				</div>

				<div className="bg-gradient-to-br from-[#482977] to-[#1A103C] rounded-3xl p-8 text-white flex flex-col md:flex-row items-center justify-between shadow-lg">
					<div className="mb-6 md:mb-0 md:mr-8">
						<h3 className="text-2xl font-bold mb-2">Ready to enroll your child?</h3>
						<p className="text-white/80">Help them build wealth and learn financial literacy early.</p>
					</div>
					<a href="https://aspire.gov.kn/" target="_blank" rel="noopener noreferrer" className="bg-[#fed141] text-[#1A103C] px-8 py-3 rounded-full font-bold hover:bg-white transition-colors whitespace-nowrap shadow-md">
						Register Now
					</a>
				</div>
			</main>
			</div>
		</div>
	);
}
