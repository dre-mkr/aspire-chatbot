import { useCallback, useEffect, useMemo, useState } from "react";
import {
	AlertIcon,
	CheckIcon,
	ExitIcon,
	SparkIcon,
	SpeakerIcon,
} from "#/components/icons";
import {
	type ApplicationStep,
	answerEligibility,
	type ChecklistItem,
	EligibilityError,
	type EligibilityLabels,
	type EligibilityResult,
	type EligibilityState,
	goBack,
	loadCheckedItems,
	quitEligibility,
	restartEligibility,
	saveCheckedItems,
	saveEligibilityResult,
} from "#/lib/aspire/eligibility";

/** The ASPIRE eligibility pre-check, played in the thread. */

interface EligibilityCheckProps {
	threadId: string;
	state: EligibilityState;
	/** Null closes the card. */
	onChanged: (state: EligibilityState | null) => void;
	/** Speaks the question or the verdict. Never the option labels. */
	onSpeak?: (text: string) => void;
	speakAvailable?: boolean;
}

export function EligibilityCheck({
	threadId,
	state,
	onChanged,
	onSpeak,
	speakAvailable = false,
}: EligibilityCheckProps) {
	const [busy, setBusy] = useState(false);
	const [failure, setFailure] = useState<string | null>(null);

	const { labels, question, result } = state;

	const guard = useCallback(async (work: () => Promise<void>) => {
		setBusy(true);
		setFailure(null);
		try {
			await work();
		} catch (error) {
			setFailure(
				error instanceof EligibilityError
					? error.message
					: "Something went wrong. Try again.",
			);
		} finally {
			setBusy(false);
		}
	}, []);

	/** Answering is also where a finished flow is banked. */
	const choose = (value: string) =>
		guard(async () => {
			const next = await answerEligibility(threadId, value);
			if (next.result) {
				saveEligibilityResult(threadId, {
					result: next.result,
					labels: next.labels,
					language: next.language,
				});
			}
			onChanged(next);
		});

	const back = () =>
		guard(async () => {
			onChanged(await goBack(threadId));
		});

	const restart = () =>
		guard(async () => {
			onChanged(await restartEligibility(threadId, state.language));
		});

	const leave = () =>
		guard(async () => {
			// A finished flow has no session to quit; asking would be a meaningless 200.
			if (state.active) await quitEligibility(threadId).catch(() => undefined);
			onChanged(null);
		});

	return (
		<section
			className="game elig"
			// The subtitle is the card's accessible description rather than a second line of chrome.
			aria-label={`${labels.title}. ${labels.subtitle}`}
			data-verdict={result?.verdict}
		>
			<header className="game__head">
				<span className="game__badge" aria-hidden="true">
					<SparkIcon />
				</span>
				<span className="game__title">{labels.title}</span>

				{question ? (
					/* Decorative: the card's label names the question, so bare markers would be noise. */
					<div className="game__steps" aria-hidden="true">
						{Array.from({ length: question.total }, (_, i) => {
							const n = i + 1;
							const done = n < question.position;
							const now = n === question.position;
							return (
								<span
									key={n}
									className="game__step"
									data-state={done ? "done" : now ? "now" : "next"}
								>
									{done ? <CheckIcon size={13} /> : now ? n : null}
								</span>
							);
						})}
					</div>
				) : null}

				<button
					type="button"
					className="game__leave"
					onClick={leave}
					disabled={busy}
				>
					<ExitIcon />
					{result ? labels.close : labels.leave}
				</button>
			</header>

			{/* Not fine print, and not under a disclosure. */}
			<p className="elig__banner">
				<AlertIcon />
				<span>{labels.banner}</span>
			</p>

			<div className="game__body">
				{failure ? <output className="game__failure">{failure}</output> : null}

				{result ? (
					<ResultPanel
						threadId={threadId}
						result={result}
						labels={labels}
						busy={busy}
						onRestart={restart}
						onSpeak={onSpeak}
						speakAvailable={speakAvailable}
					/>
				) : question ? (
					<QuestionPanel
						question={question}
						labels={labels}
						busy={busy}
						onChoose={choose}
						onBack={back}
						onSpeak={onSpeak}
						speakAvailable={speakAvailable}
					/>
				) : null}
			</div>
		</section>
	);
}

function QuestionPanel({
	question,
	labels,
	busy,
	onChoose,
	onBack,
	onSpeak,
	speakAvailable,
}: {
	question: NonNullable<EligibilityState["question"]>;
	labels: EligibilityLabels;
	busy: boolean;
	onChoose: (value: string) => void;
	onBack: () => void;
	onSpeak?: (text: string) => void;
	speakAvailable: boolean;
}) {
	const progress = labels.progress
		.replace("{position}", String(question.position))
		.replace("{total}", String(question.total));

	return (
		<div className="elig__step">
			<p className="elig__progress">
				<span>{progress}</span>
				{/* Reads the question, and only the question. */}
				{speakAvailable && onSpeak ? (
					<button
						type="button"
						className="elig__speak"
						onClick={() => onSpeak(question.text)}
					>
						<SpeakerIcon size={14} />
						<span className="sr-only">{question.text}</span>
					</button>
				) : null}
			</p>

			<h3 className="elig__question">{question.text}</h3>
			{question.help ? <p className="elig__help">{question.help}</p> : null}

			{/* Tappable options, never free text: every answer set is finite, and typing is slower. */}
			<div className="elig__options">
				{question.options.map((option) => (
					<button
						key={option.value}
						type="button"
						className="elig__option"
						// "I am not sure" is an ordinary option, deliberately not styled as a way out.
						data-chosen={option.value === question.answered_with || undefined}
						onClick={() => onChoose(option.value)}
						disabled={busy}
					>
						<span className="elig__tick" aria-hidden="true">
							{option.value === question.answered_with ? (
								<CheckIcon size={13} />
							) : null}
						</span>
						{option.label}
					</button>
				))}
			</div>

			<div className="game__actions">
				{question.can_go_back ? (
					<button
						type="button"
						className="game__btn game__btn--quiet"
						onClick={onBack}
						disabled={busy}
					>
						{labels.back}
					</button>
				) : null}
			</div>
		</div>
	);
}

function ResultPanel({
	threadId,
	result,
	labels,
	busy,
	onRestart,
	onSpeak,
	speakAvailable,
}: {
	threadId: string;
	result: EligibilityResult;
	labels: EligibilityLabels;
	busy: boolean;
	onRestart: () => void;
	onSpeak?: (text: string) => void;
	speakAvailable: boolean;
}) {
	/** The verdict as one utterance, for read-aloud. Never the checklist. */
	const spoken = useMemo(
		() => [result.headline, ...result.body, result.disclaimer].join(". "),
		[result],
	);

	return (
		<div className="elig__result">
			<p className="elig__verdict" data-verdict={result.verdict}>
				<span className="elig__verdict-icon" aria-hidden="true">
					{result.verdict === "likely_eligible" ? <CheckIcon /> : <SparkIcon />}
				</span>
				{result.headline}
				{speakAvailable && onSpeak ? (
					<button
						type="button"
						className="elig__speak"
						onClick={() => onSpeak(spoken)}
					>
						<SpeakerIcon size={14} />
						<span className="sr-only">{result.headline}</span>
					</button>
				) : null}
			</p>

			{result.body.map((line) => (
				<p key={line} className="elig__body">
					{line}
				</p>
			))}

			{/* The unresolved criterion, and the question to put to a person about it. */}
			{result.mentor_question ? (
				<div className="elig__mentor">
					{result.unresolved.length > 1 ? (
						<ul className="elig__unresolved">
							{result.unresolved.map((item) => (
								<li key={item}>{item}</li>
							))}
						</ul>
					) : null}
					<p className="elig__mentor-question">“{result.mentor_question}”</p>
				</div>
			) : null}

			{result.notices.length > 0 ? (
				<div className="elig__notices">
					{result.notices.map((notice) => (
						<p key={notice} className="elig__notice">
							{notice}
						</p>
					))}
				</div>
			) : null}

			{result.checklist.length > 0 ? (
				<Checklist
					threadId={threadId}
					items={result.checklist}
					labels={labels}
				/>
			) : null}

			{result.steps.length > 0 ? (
				<Walkthrough steps={result.steps} labels={labels} />
			) : null}

			<div className="elig__contacts">
				<span className="game__meaning-label">
					<SparkIcon size={13} />
					{labels.contact_heading}
				</span>
				{result.contacts.map((line) => (
					<p key={line} className="elig__contact">
						{line}
					</p>
				))}
			</div>

			{/* Repeated under the verdict, where the decision would be read. */}
			<p className="elig__disclaimer">{result.disclaimer}</p>

			<div className="game__actions">
				<button
					type="button"
					className="game__btn game__btn--quiet"
					onClick={onRestart}
					disabled={busy}
				>
					{labels.restart}
				</button>
			</div>
		</div>
	);
}

/** The personalised document list. */
function Checklist({
	threadId,
	items,
	labels,
}: {
	threadId: string;
	items: Array<ChecklistItem>;
	labels: EligibilityLabels;
}) {
	const [checked, setChecked] = useState<Array<string>>([]);

	// Read after mount: localStorage does not exist during SSR.
	useEffect(() => setChecked(loadCheckedItems(threadId)), [threadId]);

	const toggle = (id: string) => {
		setChecked((current) => {
			const next = current.includes(id)
				? current.filter((item) => item !== id)
				: [...current, id];
			saveCheckedItems(threadId, next);
			return next;
		});
	};

	return (
		<div className="elig__section">
			<h4 className="elig__heading">{labels.checklist_heading}</h4>
			<ul className="elig__checklist">
				{items.map((item) => {
					const on = checked.includes(item.id);
					return (
						<li
							key={item.id}
							className="elig__doc"
							data-checked={(!item.alternative && on) || undefined}
							data-alt={item.alternative || undefined}
						>
							{/* An alternative gets no tick box. */}
							{item.alternative ? (
								<p className="elig__doc-title elig__doc-title--alt">
									{item.title}
								</p>
							) : (
								<label className="elig__doc-row">
									<input
										type="checkbox"
										className="elig__checkbox"
										checked={on}
										onChange={() => toggle(item.id)}
									/>
									<span className="elig__doc-title">{item.title}</span>
								</label>
							)}
							<p className="elig__doc-detail">{item.detail}</p>
							{item.signed_by ? (
								<p className="elig__doc-meta">
									<b>{labels.signed_label}:</b> {item.signed_by}
								</p>
							) : null}
							<p className="elig__doc-meta">
								<b>{labels.where_label}:</b> {item.where}
							</p>
							{/* The source's own hedge. */}
							{item.caveat ? (
								<p className="elig__doc-caveat">{item.caveat}</p>
							) : null}
						</li>
					);
				})}
			</ul>
			<p className="elig__note">{labels.checked_note}</p>
		</div>
	);
}

function Walkthrough({
	steps,
	labels,
}: {
	steps: Array<ApplicationStep>;
	labels: EligibilityLabels;
}) {
	return (
		<div className="elig__section">
			<h4 className="elig__heading">{labels.steps_heading}</h4>
			<ol className="elig__steps">
				{steps.map((step) => (
					<li key={step.number} className="elig__step-row">
						<span className="game__chip" aria-hidden="true">
							{step.number}
						</span>
						<div className="elig__step-text">
							<b>{step.title}</b>
							<p>{step.detail}</p>
							{step.link ? (
								<a
									className="answer-link"
									href={step.link}
									target="_blank"
									rel="noopener noreferrer"
								>
									{step.link_label ?? step.link}
								</a>
							) : null}
						</div>
					</li>
				))}
			</ol>
		</div>
	);
}
