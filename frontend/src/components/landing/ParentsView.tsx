import { currentLocale } from "#/lib/aspire/i18n";
import { viewsCopy } from "#/lib/aspire/views-copy";
import { ViewHeader } from "./ViewHeader";

interface ParentsViewProps {
	onBack: () => void;
	/** Set by the rail's launcher, which closes a panel rather than navigating. */
	backLabel?: string;
}

export function ParentsView({ onBack, backLabel }: ParentsViewProps) {
	const copy = viewsCopy(currentLocale()).parents;
	return (
		<div className="view">
			<ViewHeader onBack={onBack} backLabel={backLabel} />

			<main className="view__main">
				<div className="view__head">
					<h1 className="view__title">{copy.title}</h1>
					<p className="view__lede">{copy.lede}</p>
				</div>

				<div className="panel-row">
					<section className="panel">
						<span className="panel__icon" aria-hidden="true">
							<i className="ph-duotone ph-piggy-bank" />
						</span>
						<h2 className="panel__title">{copy.grantTitle}</h2>
						<p>{copy.grantBody}</p>
						{/* This list used filled green tick circles at 2.54:1 against the
						 * card, in a green the palette does not contain; the list in the
						 * card beside it used typed "•" characters. One bullet now, from
						 * `.panel__list`, in the brand accent. */}
						<ul className="panel__list">
							{copy.grantItems.map((item) => (
								<li key={item.slice(0, 20)}>{item}</li>
							))}
						</ul>
					</section>

					<section className="panel">
						<span className="panel__icon" aria-hidden="true">
							<i className="ph-duotone ph-file-text" />
						</span>
						<h2 className="panel__title">{copy.regTitle}</h2>
						{/* Street and opening hours restored from the corpus. ASP-299 names
						 * Cayon Street; ASP-300 gives the hours. Naming a building without
						 * either sends a parent across Basseterre to a locked door, which is
						 * a worse outcome than not mentioning the walk-in centre at all. */}
						<p>
							{copy.regBody1}{" "}
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
							{copy.regBody2}
						</p>
						<p className="panel__label">{copy.needLabel}</p>
						<ul className="panel__list">
							{copy.needItems.map((item) => (
								<li key={item.slice(0, 20)}>{item}</li>
							))}
						</ul>
					</section>
				</div>

				{/* "Enroll" here and "Register" three paragraphs above were the same
				 * action under two verbs, and the button said "Register Now" in Title
				 * Case where every other control on the site is sentence case. */}
				<div className="view__cta">
					<div>
						<h2>{copy.ctaTitle}</h2>
						<p>{copy.ctaBody}</p>
					</div>
					<a
						href="https://aspire.gov.kn/"
						target="_blank"
						rel="noopener noreferrer"
					>
						{copy.ctaButton}
						<i className="ph-bold ph-arrow-up-right" aria-hidden="true" />
					</a>
				</div>
			</main>
		</div>
	);
}
