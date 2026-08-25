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
 *
 * THE ACCOUNT CONTROL LIVES HERE, and it did not before. `LandingScreen`
 * renders `<AccountControl>` only in the landing branch, and every section
 * view returns before that branch is reached -- so on all nine of these pages
 * a signed-in reader had no avatar, no menu, and therefore no way to sign
 * out. Reported as "the sign out button is not clickable"; it was not there
 * to click. It belongs in the header the pages share rather than in nine
 * copies of the same JSX.
 *
 * THE `tone` PROP IS GONE. It painted Journey and History near-black while the
 * four views reached from the same nav stayed white, and it took the focus ring
 * with it: `--focus-ring` defaults to plum, which is 1.77:1 on #0B051D, so the
 * only way out of those two pages could not be seen by anyone tabbing to it.
 * The section views are one surface now.
 */

import { AccountControl } from "#/components/auth/AccountControl";
import { ASPIRE_EXPANSION } from "./Brandmark";

export function ViewHeader({
	onBack,
	backLabel,
}: {
	onBack: () => void;
	/**
	 * What the way out is called.
	 *
	 * "Back to ASPIRE" is right on a section page, where back really is the
	 * landing. Inside a dialog opened from the rail it is a lie in two
	 * directions: the reader never left ASPIRE, and the button closes a panel
	 * rather than navigating anywhere.
	 */
	backLabel?: string;
}) {
	// Read BEFORE the default is applied. Defaulting in the destructuring meant
	// `backLabel` was never undefined by the time it was tested, so every page
	// looked like a rail dialog and the account control rendered nowhere.
	const standalone = backLabel === undefined;
	const label = backLabel ?? "Back to ASPIRE";
	return (
		<header className="view-head">
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
				className="view-head__mark"
				aria-label="ASPIRE — home"
			>
				<picture>
					<source srcSet="/brand/aspire-lockup.webp" type="image/webp" />
					<img
						src="/brand/aspire-lockup.png"
						alt={`ASPIRE — ${ASPIRE_EXPANSION}`}
						width={3046}
						height={888}
					/>
				</picture>
			</button>

			<div className="view-head__actions">
				{/* Was a 26px-tall target on a phone, and it is the only way out of
				    every one of these pages. */}
				<button type="button" onClick={onBack} className="view-head__back">
					<i className="ph-bold ph-arrow-left" aria-hidden="true" /> {label}
				</button>

				{/* Only on a section PAGE. `backLabel` is set exactly when the view
				    was opened as a dialog from the chat rail, and the rail carries
				    its own account block at its foot -- a second one floating over
				    the dialog would be the same control twice on one screen. */}
				{standalone ? <AccountControl variant="corner" /> : null}
			</div>
		</header>
	);
}
