import { collection } from "#/lib/aspire/collectibles";
import { currentLocale } from "#/lib/aspire/i18n";
import { viewsCopy } from "#/lib/aspire/views-copy";
import { ViewHeader } from "./ViewHeader";

/**
 * The shape of the course, which is not the same as anybody's place in it.
 *
 * A LEVEL, AN XP TOTAL AND A 72%-FULL BAR WERE HERE, ALL LITERALS. Every
 * visitor saw the same "Level 3 - Explorer, 720 / 1,000 XP", including the ones
 * who had never answered a question. A progress display that is identical for a
 * returning learner and a stranger is not a progress display. Real progress is
 * mastered concepts over `lessons_for_band(band)`, which needs a session — so
 * it belongs behind sign-in, not here.
 */
const STAGE_ICONS = [
	"ph-duotone ph-book-open",
	"ph-duotone ph-piggy-bank",
	"ph-duotone ph-list-checks",
	"ph-duotone ph-chart-line-up",
	"ph-duotone ph-storefront",
];

export function JourneyView({
	onBack,
	backLabel,
	onSignIn,
}: {
	onBack: () => void;
	/** Set by the rail's launcher, which closes a panel rather than navigating. */
	backLabel?: string;
	/** Omitted where there is nowhere to send them, as inside the chat rail. */
	onSignIn?: () => void;
}) {
	const copy = viewsCopy(currentLocale()).journey;
	return (
		/* This page and Chat History were painted #0B051D — near-black — while the
		 * four views reached from the same nav were white, and the product's root
		 * declares `color-scheme: light only`. Two of six is not a dark mode; it
		 * is a page that was designed on a different day. */
		<div className="view">
			<ViewHeader onBack={onBack} backLabel={backLabel} />

			<main className="view__main">
				<div className="view__head">
					<h1 className="view__title">{copy.title}</h1>
					<p className="view__lede">{copy.lede}</p>
				</div>

				<section className="panel">
					<h2 className="panel__title">{copy.accountTitle}</h2>
					<p>{copy.accountBody}</p>
					{/* The empty state named an action and gave no way to take it. */}
					{onSignIn ? (
						<button
							type="button"
							onClick={onSignIn}
							className="mt-2 inline-flex items-center gap-2 min-h-11 px-5 rounded-full bg-plum text-white font-semibold hover:bg-plum-deep transition-colors cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-magenta"
						>
							{copy.signIn}
							<i className="ph-bold ph-arrow-right" aria-hidden="true" />
						</button>
					) : null}
				</section>

				{collection().length > 0 ? (
					<section className="panel">
						<h2 className="panel__title">{copy.shelfTitle}</h2>
						<p>{copy.shelfLede}</p>
						<ul className="shelf">
							{collection().map((item) => (
								<li className="shelf__item" key={item.name + item.topic}>
									<span className="shelf__emoji" aria-hidden="true">
										{item.emoji}
									</span>
									<span className="shelf__name">{item.name}</span>
								</li>
							))}
						</ul>
					</section>
				) : null}

				<section className="panel">
					<h2 className="panel__title">{copy.learnTitle}</h2>
					{/* The connector rail was drawn at `-z-10`, which put it behind the
					 * card that contained it — so it never appeared at any width. And
					 * the five columns had no width of their own, so at 390px the
					 * labels ran together as "BudgetingInvestingBusiness". */}
					{/* No 1 / 2 / 3 above the labels. The rail already runs left to
					 * right and the list is an `<ol>`, so the order is stated twice
					 * before a number is added on top of it. */}
					<ol className="journey">
						{copy.stages.map((label, index) => (
							<li className="journey__step" key={label}>
								<span className="journey__dot" aria-hidden="true">
									<i className={STAGE_ICONS[index]} />
								</span>
								<span className="journey__label">{label}</span>
							</li>
						))}
					</ol>
				</section>
			</main>
		</div>
	);
}
