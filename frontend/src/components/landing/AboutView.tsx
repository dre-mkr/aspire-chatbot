import { ViewHeader } from "./ViewHeader";

interface AboutViewProps {
	onBack: () => void;
}

export function AboutView({ onBack }: AboutViewProps) {
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
						filter: "saturate(0.85) brightness(1.12)",
					}}
				></div>
			</div>

			<div className="relative z-10 flex flex-col flex-1">
				<ViewHeader onBack={onBack} />

				<main className="flex-1 w-full max-w-4xl mx-auto px-6 py-12">
					<div className="text-center mb-16">
						{/* The wordmark used to sit here, in the body, with alt text
					    reading "ASPIRE Logo" -- which tells a screen reader the file
					    is a logo, something the reader had already assumed. It is in
					    the header now, once, named properly. */}
						<h1 className="text-4xl md:text-6xl font-display font-medium text-[#1A103C] mb-6">
							About{" "}
							<span className="text-transparent bg-clip-text bg-gradient-to-r from-[#c22f99] to-[#482977]">
								ASPIRE
							</span>
						</h1>
						<p className="text-xl text-[#482977] max-w-2xl mx-auto font-medium">
							Achieving Success through Personal Investment, Resources, and
							Education
						</p>
					</div>

					<div className="bg-white rounded-3xl p-8 md:p-12 shadow-sm border border-[#482977]/10 mb-12">
						<h2 className="text-2xl font-bold mb-6 text-[#1A103C]">
							Our Mission
						</h2>
						<p className="text-[#482977]/80 leading-relaxed text-lg mb-8">
							The ASPIRE Programme provides a foundational grant of EC$1,000 for
							every eligible youth in St. Kitts and Nevis, split evenly between
							a dedicated savings account and local investments. This landmark
							government initiative is designed to foster financial literacy,
							robust saving habits, and responsible wealth-building practices
							among our nation's youth.
						</p>

						<div className="grid grid-cols-1 md:grid-cols-3 gap-6">
							<div className="bg-[#F5F2FA] p-6 rounded-2xl">
								<i className="ph-duotone ph-vault text-3xl text-[#482977] mb-4"></i>
								<h4 className="font-bold text-[#1A103C] mb-2">Real Savings</h4>
								<p className="text-sm text-[#482977]/80">
									An initial EC$500 held in a savings account at the St.
									Kitts-Nevis-Anguilla National Bank for every eligible child.
								</p>
							</div>
							<div className="bg-[#F5F2FA] p-6 rounded-2xl">
								<i className="ph-duotone ph-chart-line-up text-3xl text-[#fed141] mb-4"></i>
								<h4 className="font-bold text-[#1A103C] mb-2">
									Local Investment
								</h4>
								<p className="text-sm text-[#482977]/80">
									A further EC$500 invested in shares of local government-owned
									entities.
								</p>
							</div>
							<div className="bg-[#F5F2FA] p-6 rounded-2xl">
								<i className="ph-duotone ph-student text-3xl text-[#c22f99] mb-4"></i>
								<h4 className="font-bold text-[#1A103C] mb-2">
									Education First
								</h4>
								<p className="text-sm text-[#482977]/80">
									Teaching youth aged 5-18 the fundamentals of budgeting and
									wealth building.
								</p>
							</div>
						</div>
					</div>

					<div className="text-center">
						<p className="text-sm font-semibold text-[#482977]/60 uppercase tracking-wider mb-4">
							Information sourced from
						</p>
						<a
							href="https://aspire.gov.kn/"
							target="_blank"
							rel="noopener noreferrer"
							className="inline-flex items-center gap-2 text-[#c22f99] hover:text-[#482977] font-bold text-lg transition-colors"
						>
							aspire.gov.kn <i className="ph-bold ph-arrow-up-right"></i>
						</a>
					</div>
				</main>
			</div>
		</div>
	);
}
