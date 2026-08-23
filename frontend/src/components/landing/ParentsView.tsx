import { ViewHeader } from "./ViewHeader";

interface ParentsViewProps {
	onBack: () => void;
	/** Set by the rail's launcher, which closes a panel rather than navigating. */
	backLabel?: string;
}

export function ParentsView({ onBack, backLabel }: ParentsViewProps) {
	return (
		<div className="view">
			<ViewHeader onBack={onBack} backLabel={backLabel} />

			<main className="view__main">
				<div className="view__head">
					<h1 className="view__title">For parents &amp; guardians</h1>
					<p className="view__lede">
						Secure your child&rsquo;s financial future with the ASPIRE
						Programme.
					</p>
				</div>

				<div className="panel-row">
					<section className="panel">
						<span className="panel__icon" aria-hidden="true">
							<i className="ph-duotone ph-piggy-bank" />
						</span>
						<h2 className="panel__title">The EC$1,000 grant</h2>
						<p>
							Every eligible child (ages 5–18) receives an EC$1,000 contribution
							from the Government of St. Kitts and Nevis:
						</p>
						{/* This list used filled green tick circles at 2.54:1 against the
						 * card, in a green the palette does not contain; the list in the
						 * card beside it used typed "•" characters. One bullet now, from
						 * `.panel__list`, in the brand accent. */}
						<ul className="panel__list">
							<li>
								EC$500 in a savings account at the St. Kitts-Nevis-Anguilla
								National Bank
							</li>
							<li>
								EC$500 invested in shares of local government-owned entities
							</li>
						</ul>
					</section>

					<section className="panel">
						<span className="panel__icon" aria-hidden="true">
							<i className="ph-duotone ph-file-text" />
						</span>
						<h2 className="panel__title">How to register</h2>
						{/* Street and opening hours restored from the corpus. ASP-299 names
						 * Cayon Street; ASP-300 gives the hours. Naming a building without
						 * either sends a parent across Basseterre to a locked door, which is
						 * a worse outcome than not mentioning the walk-in centre at all. */}
						<p>
							Register online at{" "}
							{/* This was inert bold text while the same address on About was
							 * a working link. */}
							<a
								href="https://aspire.gov.kn/"
								target="_blank"
								rel="noopener noreferrer"
								className="font-semibold text-magenta underline underline-offset-2 hover:text-plum transition-colors"
							>
								aspire.gov.kn
							</a>
							, or in person at The Cable Office on Cayon Street in Basseterre —
							walk-in support is available Monday to Friday, 9:00 AM to 3:00 PM.
						</p>
						<p className="panel__label">What you&rsquo;ll need</p>
						<ul className="panel__list">
							<li>Parent or guardian valid ID</li>
							<li>Child&rsquo;s SKN birth certificate or passport</li>
							<li>Recent proof of address (within 3 months)</li>
						</ul>
					</section>
				</div>

				{/* "Enroll" here and "Register" three paragraphs above were the same
				 * action under two verbs, and the button said "Register Now" in Title
				 * Case where every other control on the site is sentence case. */}
				<div className="view__cta">
					<div>
						<h2>Ready to register your child?</h2>
						<p>Help them build wealth and learn financial literacy early.</p>
					</div>
					<a
						href="https://aspire.gov.kn/"
						target="_blank"
						rel="noopener noreferrer"
					>
						Register your child
						<i className="ph-bold ph-arrow-up-right" aria-hidden="true" />
					</a>
				</div>
			</main>
		</div>
	);
}
