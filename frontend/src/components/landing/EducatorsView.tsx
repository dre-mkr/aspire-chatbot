import { currentLocale } from "#/lib/aspire/i18n";
import { viewsCopy } from "#/lib/aspire/views-copy";
import { ViewHeader } from "./ViewHeader";

interface EducatorsViewProps {
	onBack: () => void;
	/** Set by the rail's launcher, which closes a panel rather than navigating. */
	backLabel?: string;
}

export function EducatorsView({ onBack, backLabel }: EducatorsViewProps) {
	const copy = viewsCopy(currentLocale()).educators;
	return (
		<div className="view">
			<ViewHeader onBack={onBack} backLabel={backLabel} />

			<main className="view__main">
				<div className="view__head">
					<h1 className="view__title">{copy.title}</h1>
					<p className="view__lede">{copy.lede}</p>
				</div>

				{/* This card was wrapped in a `flex md:flex-row items-center` container
				 * holding exactly one `flex-1` child — a two-column layout with one
				 * column in it, left behind when the second was removed. */}
				<section className="panel">
					<span className="panel__icon" aria-hidden="true">
						<i className="ph-duotone ph-books" />
					</span>
					<h2 className="panel__title">{copy.currTitle}</h2>
					<p>{copy.currBody}</p>
					<div className="view__tags">
						{copy.topics.map((topic) => (
							<span key={topic}>{topic}</span>
						))}
					</div>
				</section>

				<div className="panel-row">
					<section className="panel">
						<h2 className="panel__title">{copy.trainTitle}</h2>
						<p>{copy.trainBody}</p>
					</section>

					<section className="panel">
						<h2 className="panel__title">{copy.interTitle}</h2>
						<p>{copy.interBody}</p>
					</section>
				</div>
			</main>
		</div>
	);
}
