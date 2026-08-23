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
const STAGES = [
	{ label: "Basics", icon: "ph-duotone ph-book-open" },
	{ label: "Saving", icon: "ph-duotone ph-piggy-bank" },
	{ label: "Budgeting", icon: "ph-duotone ph-list-checks" },
	{ label: "Investing", icon: "ph-duotone ph-chart-line-up" },
	{ label: "Business", icon: "ph-duotone ph-storefront" },
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
	return (
		/* This page and Chat History were painted #0B051D — near-black — while the
		 * four views reached from the same nav were white, and the product's root
		 * declares `color-scheme: light only`. Two of six is not a dark mode; it
		 * is a page that was designed on a different day. */
		<div className="view">
			<ViewHeader onBack={onBack} backLabel={backLabel} />

			<main className="view__main">
				<div className="view__head">
					<h1 className="view__title">Your financial journey</h1>
					<p className="view__lede">
						Track your progress as you master new money skills, earn badges, and
						build your future in St. Kitts and Nevis.
					</p>
				</div>

				<section className="panel">
					<h2 className="panel__title">Your progress lives with your account</h2>
					<p>Sign in and your badges, lessons and coins follow you here.</p>
					{/* The empty state named an action and gave no way to take it. */}
					{onSignIn ? (
						<button
							type="button"
							onClick={onSignIn}
							className="mt-2 inline-flex items-center gap-2 min-h-11 px-5 rounded-full bg-plum text-white font-semibold hover:bg-plum-deep transition-colors cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-magenta"
						>
							Sign in
							<i className="ph-bold ph-arrow-right" aria-hidden="true" />
						</button>
					) : null}
				</section>

				<section className="panel">
					<h2 className="panel__title">What you will learn</h2>
					{/* The connector rail was drawn at `-z-10`, which put it behind the
					 * card that contained it — so it never appeared at any width. And
					 * the five columns had no width of their own, so at 390px the
					 * labels ran together as "BudgetingInvestingBusiness". */}
					{/* No 1 / 2 / 3 above the labels. The rail already runs left to
					 * right and the list is an `<ol>`, so the order is stated twice
					 * before a number is added on top of it. */}
					<ol className="journey">
						{STAGES.map((stage) => (
							<li className="journey__step" key={stage.label}>
								<span className="journey__dot" aria-hidden="true">
									<i className={stage.icon} />
								</span>
								<span className="journey__label">{stage.label}</span>
							</li>
						))}
					</ol>
				</section>
			</main>
		</div>
	);
}
