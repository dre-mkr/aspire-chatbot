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

/**
 * One mark, two proportions.
 *
 * `hero` is the title-page lockup: the wordmark large and centred, the
 * expansion beneath it, stars falling behind.
 *
 * `header` is the same mark doing a different job, and it exists because the
 * hero lockup was being used in the header -- 84px of wordmark stacked over a
 * two-line expansion, giving a 211px header on a 900px viewport. Nearly a
 * quarter of the screen, before a word of the page had been read, and it was
 * what pushed the footer out of reach.
 *
 * Smaller is not less confident. The mark still leads, the expansion still
 * travels with it, and the page fits.
 */
export function Brandmark({
	variant = "hero",
}: {
	variant?: "hero" | "header";
} = {}) {
	const [mounted, setMounted] = useState(false);
	useEffect(() => setMounted(true), []);

	return (
		<div
			className={
				variant === "header"
					? `brandmark brandmark--header flex flex-col items-start gap-1 transform transition-all duration-1000 ${mounted ? "translate-y-0 opacity-100" : "translate-y-2 opacity-0"}`
					: `brandmark flex flex-col items-center justify-center transform transition-all duration-1000 ${mounted ? "translate-y-0 opacity-100" : "translate-y-8 opacity-0"}`
			}
		>
			<div
				className={
					variant === "header"
						? "relative w-[196px] md:w-[224px] group flex-none"
						: "relative w-full max-w-[280px] md:max-w-[340px] mb-4 group"
				}
			>
				<div className="absolute inset-0 bg-magenta/10 blur-2xl rounded-full scale-110 opacity-0 group-hover:opacity-100 transition-opacity duration-700 pointer-events-none"></div>

				{/* Falling stars behind the mark, in both lockups.
				 *
				 * They were hero-only for a while, on the theory that they would
				 * crowd the nav at header scale. They do not -- what crowds it is
				 * a fall written for a 340px mark playing out behind a 224px one,
				 * which drops them through the navigation. The fall is scaled
				 * instead, in `.brandmark--header .falling-star`. */}
				<div
					className="absolute inset-0 pointer-events-none z-0 overflow-visible"
					style={
						variant === "header"
							? { top: "-10px", bottom: "-34px" }
							: { top: "-20px", bottom: "-100px" }
					}
				>
					<i
						className={`ph-fill ph-star absolute text-gold falling-star falling-star-1 drop-shadow-md ${variant === "header" ? "text-sm" : "text-2xl"}`}
					></i>
					<i
						className={`ph-fill ph-star absolute text-gold falling-star falling-star-2 drop-shadow-md ${variant === "header" ? "text-xs" : "text-xl"}`}
					></i>
					<i
						className={`ph-fill ph-star absolute text-gold falling-star falling-star-3 drop-shadow-md ${variant === "header" ? "text-sm" : "text-2xl"}`}
					></i>
				</div>

				<picture>
					{/* The lockup: mark and expansion in one artwork, as supplied.
					    3046x888 at source, so it finally renders sharp -- the old
					    `aspire-wordmark.png` was 190x48 and was being upscaled. */}
					<source srcSet="/brand/aspire-lockup.webp" type="image/webp" />
					<img
						src="/brand/aspire-lockup.png"
						alt={`ASPIRE — ${ASPIRE_EXPANSION}`}
						width={3046}
						height={888}
						className="w-full h-auto drop-shadow-xl transition-transform duration-500 group-hover:scale-105 group-hover:-translate-y-1 relative z-10"
					/>
				</picture>
			</div>

			{/* The expansion used to be set here as text under the mark.
			    It is part of the artwork now, so setting it again put the same
			    sentence on the page twice. `ASPIRE_EXPANSION` still exists and is
			    still what the alt text says, which is where a screen reader needs
			    it. */}
		</div>
	);
}
