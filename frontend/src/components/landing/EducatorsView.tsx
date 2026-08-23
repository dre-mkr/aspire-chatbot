import { ViewHeader } from "./ViewHeader";

interface EducatorsViewProps {
	onBack: () => void;
	/** Set by the rail's launcher, which closes a panel rather than navigating. */
	backLabel?: string;
}

const TOPICS = [
	"Budgeting",
	"Saving",
	"Investing",
	"Debt management",
	"Entrepreneurship",
];

export function EducatorsView({ onBack, backLabel }: EducatorsViewProps) {
	return (
		<div className="view">
			<ViewHeader onBack={onBack} backLabel={backLabel} />

			<main className="view__main">
				<div className="view__head">
					<h1 className="view__title">For educators</h1>
					<p className="view__lede">
						Empower the next generation with essential financial literacy.
					</p>
				</div>

				{/* This card was wrapped in a `flex md:flex-row items-center` container
				 * holding exactly one `flex-1` child — a two-column layout with one
				 * column in it, left behind when the second was removed. */}
				<section className="panel">
					<span className="panel__icon" aria-hidden="true">
						<i className="ph-duotone ph-books" />
					</span>
					<h2 className="panel__title">The ASPIRE AI financial curriculum</h2>
					<p>
						Educators are at the heart of ASPIRE&rsquo;s financial literacy
						programme. Developed by the ASPIRE AI team in collaboration with the
						Eastern Caribbean Central Bank, the curriculum introduces students
						to the ideas that will shape their financial futures &mdash; and
						gives every learner a guide who meets them at their own age.
					</p>
					<div className="view__tags">
						{TOPICS.map((topic) => (
							<span key={topic}>{topic}</span>
						))}
					</div>
				</section>

				<div className="panel-row">
					<section className="panel">
						<h2 className="panel__title">Educator training</h2>
						<p>
							{/* "specialized" here and "programme" two lines up: one page,
							 * two spelling conventions, on a Government of St Kitts and
							 * Nevis service. */}
							The ASPIRE Programme hosts specialised educator training sessions
							to equip teachers with the knowledge and tools to teach financial
							literacy confidently in the classroom.
						</p>
					</section>

					<section className="panel">
						<h2 className="panel__title">Interactive learning</h2>
						<p>
							Our AI assistant and gamified learning paths reinforce classroom
							lessons, letting students play, explore and earn rewards while
							mastering the EC dollar.
						</p>
					</section>
				</div>
			</main>
		</div>
	);
}
