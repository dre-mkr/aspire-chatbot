/** The ASPIRE lockup on the landing page. */

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
 * The wordmark, and what the letters mean.
 *
 * The A mark and the arrow that orbited it used to sit above this. They are
 * gone: the wordmark already carries the arrow, baked into its artwork, and a
 * second one circling a second copy of the letter was the brand said twice
 * before the page had said anything. What is left is the name and the sentence
 * it stands for, which is what a first-time reader is here to learn.
 *
 * The wordmark carries the accessible name now — the orbit was one `<svg>` with
 * a `role="img"`, and that was where the name used to live.
 */
export function Brandmark() {
	return (
		<div className="brandmark">
			<img
				className="brandmark__wordmark"
				src="/brand/aspire-wordmark.png"
				width={190}
				height={48}
				alt={`ASPIRE — ${ASPIRE_EXPANSION}`}
			/>

			{/* Already said by the alt text above, so it is not said twice. */}
			<p className="brandmark__expansion" aria-hidden="true">
				{ASPIRE_EXPANSION}
			</p>
		</div>
	);
}
