/** The ASPIRE lockup on the landing page. */

/**
 * What ASPIRE stands for.
 *
 * Verified against the knowledge base the assistant itself answers from —
 * row `ASP-002` of `backend/data/knowledge_base.csv`, sourced to
 * https://aspire.gov.kn/. It is written here once so the landing page and the
 * sign-in surface cannot drift apart; do not reword it.
 */
import { useEffect, useState } from "react";

export const ASPIRE_EXPANSION =
	"Achieving Success through Personal Investment, Resources and Education";

export function Brandmark() {
	const [mounted, setMounted] = useState(false);
	useEffect(() => setMounted(true), []);

	return (
		<div className={`brandmark flex flex-col items-center justify-center transform transition-all duration-1000 ${mounted ? 'translate-y-0 opacity-100' : 'translate-y-8 opacity-0'}`}>
			<div className="relative w-full max-w-[280px] md:max-w-[340px] mb-4 group">
				<div className="absolute inset-0 bg-[#c22f99]/10 blur-2xl rounded-full scale-110 opacity-0 group-hover:opacity-100 transition-opacity duration-700 pointer-events-none"></div>
				
				{/* Falling stars behind/around the wordmark */}
				<div className="absolute inset-0 pointer-events-none z-0 overflow-visible" style={{ top: '-20px', bottom: '-100px' }}>
					<i className="ph-fill ph-star absolute text-[#fed141] text-2xl falling-star falling-star-1 drop-shadow-md"></i>
					<i className="ph-fill ph-star absolute text-[#fed141] text-xl falling-star falling-star-2 drop-shadow-md"></i>
					<i className="ph-fill ph-star absolute text-[#fed141] text-2xl falling-star falling-star-3 drop-shadow-md"></i>
				</div>

				<img 
					src="/brand/aspire-wordmark.png" 
					alt={`ASPIRE — ${ASPIRE_EXPANSION}`}
					className="w-full h-auto drop-shadow-xl transition-transform duration-500 group-hover:scale-105 group-hover:-translate-y-1 relative z-10"
				/>
			</div>
			
			<p className="brandmark__expansion text-center text-sm md:text-base font-medium text-[#482977]/80 max-w-[420px] leading-snug tracking-tight !text-[#482977]/80 mt-2 relative z-10">
				{ASPIRE_EXPANSION}
			</p>
		</div>
	);
}
