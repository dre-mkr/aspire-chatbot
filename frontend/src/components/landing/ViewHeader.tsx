/**
 * The header every section page shares: the mark, then the way back.
 *
 * Five of the six section views carried no logo at all -- a reader who landed
 * on "For Parents & Guardians" from a shared link saw a heading, a back link
 * reading "Back to ASPIRE", and nothing anywhere on the page saying they were
 * *in* ASPIRE. On a government programme's site that is the one thing a page
 * cannot leave out.
 *
 * The sixth, About, had one, and it was the odd one out in two ways: it sat in
 * the body rather than the header, and its alt text read "ASPIRE Logo". A
 * screen reader announcing "image, ASPIRE Logo" tells you the file is a logo,
 * which the reader already assumed; what it should say is the name, once,
 * followed by what the name stands for. `Brandmark` had this right and nothing
 * else used it.
 *
 * The mark is a link home rather than decoration, because on every other site
 * in the world it is.
 */

import { ASPIRE_EXPANSION } from "./Brandmark";

export function ViewHeader({
	onBack,
	tone = "light",
}: {
	onBack: () => void;
	/** Journey, History and Stories sit on the deep plum; the rest on white. */
	tone?: "light" | "dark";
}) {
	const dark = tone === "dark";
	return (
		<header className="p-6 flex items-center justify-between gap-4 flex-wrap">
			{/* The mark never travels without what it stands for.
			  *
			  * ASPIRE is an acronym, and a wordmark on its own is four syllables
			  * of nothing to a reader meeting the programme for the first time --
			  * which, on a page reached from a shared link, is most of them. The
			  * landing hero has always carried the expansion underneath; every
			  * section page does now too. */}
			<button
				type="button"
				onClick={onBack}
				className="group relative inline-flex items-center"
				aria-label="ASPIRE — home"
			>
				<span
					className="absolute inset-0 bg-[#c22f99]/10 blur-2xl rounded-full scale-110 opacity-0 group-hover:opacity-100 transition-opacity duration-700 pointer-events-none"
					aria-hidden="true"
				/>
				<picture>
					<source srcSet="/brand/aspire-lockup.webp" type="image/webp" />
					<img
						src="/brand/aspire-lockup.png"
						alt={`ASPIRE — ${ASPIRE_EXPANSION}`}
						width={3046}
						height={888}
						className={`relative z-10 h-11 md:h-14 w-auto transition-transform duration-500 group-hover:scale-105 ${
							dark ? "brightness-0 invert" : ""
						}`}
					/>
				</picture>
			</button>

			<button
				type="button"
				onClick={onBack}
				className={`flex items-center gap-2 transition-colors font-semibold ${
					dark
						? "text-white/70 hover:text-white"
						: "text-[#482977] hover:text-[#c22f99]"
				}`}
			>
				<i className="ph-bold ph-arrow-left" aria-hidden="true" /> Back to ASPIRE
			</button>
		</header>
	);
}
