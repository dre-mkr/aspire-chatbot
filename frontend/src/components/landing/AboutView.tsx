import { ASPIRE_EXPANSION } from "./Brandmark";
import { ViewHeader } from "./ViewHeader";

interface AboutViewProps {
	onBack: () => void;
}

/**
 * The three things the grant actually is. One card each, and the cards are
 * peers of one another rather than a grid nested inside a second card.
 *
 * `wash` says which brand tint the icon well takes. Three tints, not three
 * unrelated hues: the icons were plum, brand gold and magenta, with the gold
 * one sitting at 1.46:1 against its own white card.
 */
const PILLARS: ReadonlyArray<{ icon: string; title: string; body: string }> = [
	{
		icon: "ph-duotone ph-vault",
		title: "Real savings",
		body: "An initial EC$500 held in a savings account at the St. Kitts-Nevis-Anguilla National Bank for every eligible child.",
	},
	{
		icon: "ph-duotone ph-chart-line-up",
		title: "Local investment",
		body: "A further EC$500 invested in shares of local government-owned entities.",
	},
	{
		icon: "ph-duotone ph-student",
		title: "Education first",
		body: "Teaching youth aged 5–18 the fundamentals of budgeting and wealth building.",
	},
];

export function AboutView({ onBack }: AboutViewProps) {
	return (
		<div className="view">
			<ViewHeader onBack={onBack} />

			<main className="view__main">
				<div className="view__head">
					{/* "About ASPIRE" was set with the second word clipped out of a
					 * magenta-to-plum gradient — the one heading on the site that did
					 * it, and the treatment that reads as generated wherever it
					 * appears. The accent colour says the same thing flat. */}
					<h1 className="view__title">
						About <span className="text-magenta">ASPIRE</span>
					</h1>
					{/* The expansion was typed out here as well as in `Brandmark`, and
					 * the two had already drifted on the Oxford comma. */}
					<p className="view__lede">{ASPIRE_EXPANSION}</p>
				</div>

				<section className="panel">
					<h2 className="panel__title">Our mission</h2>
					<p>
						The ASPIRE Programme provides a foundational grant of EC$1,000 for
						every eligible youth in St. Kitts and Nevis, split evenly between a
						dedicated savings account and local investments. This landmark
						government initiative is designed to foster financial literacy,
						robust saving habits, and responsible wealth-building practices
						among our nation&rsquo;s youth.
					</p>
				</section>

				<div className="panel-row">
					{PILLARS.map((pillar) => (
						<section className="panel" key={pillar.title}>
							<span className="panel__icon" aria-hidden="true">
								<i className={pillar.icon} />
							</span>
							<h2 className="panel__title">{pillar.title}</h2>
							<p>{pillar.body}</p>
						</section>
					))}
				</div>

				{/* "INFORMATION SOURCED FROM" was a 14px uppercase letterspaced kicker
				 * at 3.6:1 on white. It is a caption; it is set as one. */}
				<p className="view__source">
					Information sourced from
					<a
						href="https://aspire.gov.kn/"
						target="_blank"
						rel="noopener noreferrer"
					>
						aspire.gov.kn
						<i className="ph-bold ph-arrow-up-right" aria-hidden="true" />
					</a>
				</p>
			</main>
		</div>
	);
}
