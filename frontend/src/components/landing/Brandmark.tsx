/** The ASPIRE lockup on the landing page, with the arrow in orbit. */

/**
 * What ASPIRE stands for.
 *
 * Verified against the knowledge base the assistant itself answers from —
 * row `ASP-002` of `backend/data/knowledge_base.csv`, sourced to
 * https://aspire.gov.kn/. It is written here once so the landing page and the
 * sign-in surface cannot drift apart; do not reword it.
 */
export const ASPIRE_EXPANSION =
	"Achieving Success through Personal Investment, Resources and Education";

/**
 * The mark, an orbiting arrow, the wordmark, and what the letters mean.
 *
 * The arrow is drawn here rather than taken from the artwork, and that is
 * forced rather than chosen: the only arrow ASPIRE has is baked into
 * `aspire-wordmark.png` as pixels, so it cannot leave the letters it sits on.
 * `aspire-mark.png` — the A with the star knocked out of it — has no arrow at
 * all, which makes it the one thing in the brand an arrow can travel around.
 * Its magenta is the wordmark's own, sampled: #C22F99.
 *
 * The whole lockup is one `<svg>` so the orbit is defined in the mark's own
 * coordinates. A DOM element circling a raster would need the radius restated
 * at every breakpoint and would drift by a pixel or two at each one.
 */
export function Brandmark({ still = false }: { still?: boolean }) {
	return (
		<div className="brandmark" data-still={still || undefined}>
			<div className="brandmark__orbit">
				<svg
					viewBox="0 0 120 120"
					className="brandmark__svg"
					role="img"
					aria-label={`ASPIRE — ${ASPIRE_EXPANSION}`}
				>
					<title>{`ASPIRE — ${ASPIRE_EXPANSION}`}</title>

					{/* The mark, inset so the orbit has somewhere to be. */}
					<image
						href="/brand/aspire-mark.png"
						x="22"
						y="22"
						width="76"
						height="76"
						className="brandmark__mark"
					/>

					{/*
					  The arrow, and the path it travels. `rotate` on a group whose
					  origin is the centre is one compositor-driven transform — no
					  layout, no paint, and it costs nothing to leave running.

					  The arrowhead is drawn pointing along the direction of travel
					  (tangent), so it reads as going somewhere rather than being
					  dragged around backwards.
					*/}
					<g className="brandmark__arrow-spin">
						<g transform="translate(60 8)">
							<path
								className="brandmark__arrow"
								d="M-13 0 A 13 13 0 0 1 6 -3"
								fill="none"
								strokeLinecap="round"
							/>
							<path className="brandmark__head" d="M2 -8 L10 -2.5 L1.5 2 Z" />
						</g>
					</g>
				</svg>
			</div>

			<img
				className="brandmark__wordmark"
				src="/brand/aspire-wordmark.png"
				width={190}
				height={48}
				alt=""
			/>

			<p className="brandmark__expansion">{ASPIRE_EXPANSION}</p>
		</div>
	);
}
