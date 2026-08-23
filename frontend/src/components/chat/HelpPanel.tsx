import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
	CloseIcon,
	InfoIcon,
	MicIcon,
	PersonIcon,
	ShuffleIcon,
	SparkIcon,
} from "#/components/icons";
import { GUIDES } from "#/lib/aspire/personas";

/**
 * "How to use ASPIRE AI" — the launcher and the panel it opens.
 *
 * Self-contained on purpose. Both the landing screen and the chat screen render
 * the rail, so threading `open` state through two pages to reach one button
 * would be two props and a piece of state in each of them; the dialog is
 * portalled to the body and does not care where its trigger sits.
 *
 * The a11y behaviour is the project's existing modal recipe, the one
 * `VoiceSettings` uses: Escape closes, Tab is trapped inside, focus is captured
 * before opening and handed back on close.
 */
export function HelpLauncher() {
	const [open, setOpen] = useState(false);
	const [mounted, setMounted] = useState(false);
	const dialogId = useId();
	const triggerRef = useRef<HTMLButtonElement>(null);
	const panelRef = useRef<HTMLDivElement>(null);
	const returnFocusTo = useRef<HTMLElement | null>(null);

	// The portal is client-only: during SSR there is no document to look for.
	useEffect(() => setMounted(true), []);

	useEffect(() => {
		if (!open) return;

		const onKey = (event: KeyboardEvent) => {
			if (event.key === "Escape") {
				event.stopPropagation();
				setOpen(false);
				return;
			}
			if (event.key !== "Tab") return;

			const focusable = panelRef.current?.querySelectorAll<HTMLElement>(
				'button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
			);
			if (!focusable || focusable.length === 0) return;
			const first = focusable[0];
			const last = focusable[focusable.length - 1];
			if (event.shiftKey && document.activeElement === first) {
				event.preventDefault();
				last.focus();
			} else if (!event.shiftKey && document.activeElement === last) {
				event.preventDefault();
				first.focus();
			}
		};

		window.addEventListener("keydown", onKey, true);
		return () => window.removeEventListener("keydown", onKey, true);
	}, [open]);

	// Focus in on open, and back where it came from on close.
	useEffect(() => {
		if (open) {
			returnFocusTo.current = document.activeElement as HTMLElement | null;
			panelRef.current?.querySelector<HTMLElement>("button")?.focus();
			return;
		}
		returnFocusTo.current?.focus?.();
		returnFocusTo.current = null;
	}, [open]);

	return (
		<>
			<button
				ref={triggerRef}
				type="button"
				className="btn-help"
				aria-haspopup="dialog"
				aria-expanded={open}
				aria-controls={open ? dialogId : undefined}
				onClick={() => setOpen(true)}
			>
				<span className="btn-help__glyph">
					<InfoIcon />
				</span>
				<span className="rail__fold">How to use</span>
			</button>

			{open && mounted
				? createPortal(
						<div className="help">
							<button
								type="button"
								className="help__scrim"
								onClick={() => setOpen(false)}
								tabIndex={-1}
							>
								<span className="sr-only">Close</span>
							</button>

							<div
								className="help__panel"
								id={dialogId}
								ref={panelRef}
								role="dialog"
								aria-modal="true"
								aria-labelledby={`${dialogId}-title`}
							>
								<div className="help__head">
									<h2 className="help__title" id={`${dialogId}-title`}>
										How to use ASPIRE AI
									</h2>
									<button
										type="button"
										className="icon-btn help__close"
										onClick={() => setOpen(false)}
									>
										<CloseIcon />
										<span className="sr-only">Close</span>
									</button>
								</div>

								<div className="help__body">
									<HelpContent />
								</div>
							</div>
						</div>,
						document.body,
					)
				: null}
		</>
	);
}

function Section({
	title,
	glyph,
	children,
}: {
	title: string;
	glyph?: React.ReactNode;
	children: React.ReactNode;
}) {
	return (
		<section className="help__section">
			<h3 className="help__heading">
				{glyph ? (
					<span className="help__heading-glyph" aria-hidden="true">
						{glyph}
					</span>
				) : null}
				{title}
			</h3>
			{children}
		</section>
	);
}

function HelpContent() {
	return (
		<>
			<p className="help__lede">
				ASPIRE AI is the assistant for the ASPIRE Programme, a Government of St
				Kitts and Nevis initiative. It explains what the programme is, helps
				with joining it, and teaches how saving and money work.
			</p>

			<Section title="Who it is for">
				<p>
					Young people aged 5 to 18, and the parents, guardians and teachers
					helping them. You do not need an account to ask a question — signing
					in is only needed to apply, or to keep your lessons between visits.
				</p>
			</Section>

			<Section title="Who you are talking to" glyph={<PersonIcon />}>
				<p>
					Choosing a persona changes how ASPIRE AI writes to you: the words it
					picks, how long an answer is, and whether it explains or gets to the
					point. It is not just a label — the same question genuinely gets a
					different answer.
				</p>
				{/* GUIDES, not PERSONAS. Skye and Kaleb share the `stella` key, so the
				 * persona list collapses them into one row reading "Skye & Kaleb ·
				 * Ages 5-12" -- and then the picker this paragraph tells you to open
				 * offers them as two separate faces. The reader is being introduced
				 * to five and shown six. GUIDES is the six-row view the landing page
				 * and the picker already use; this is the third surface joining them.
				 */}
				<ul className="help__list">
					{GUIDES.map((guide) => (
						<li key={guide.guideId}>
							<strong>{guide.name}</strong>
							<span className="help__muted"> · {guide.audience}</span>
							<br />
							{guide.blurb}
						</li>
					))}
				</ul>
				<p className="help__note">
					<strong>To switch:</strong> use the person button at the bottom of the
					screen, next to where you type. You can change it at any time, as
					often as you like.
				</p>
			</Section>

			<Section title="Explain it simply" glyph={<SparkIcon />}>
				<p>
					Two ways to get a plainer version of the same answer. The{" "}
					<strong>Explain it simply</strong> button beside the text box keeps
					every new answer short and simple until you switch it off. Or press{" "}
					<strong>Simpler</strong> underneath any answer already on screen to
					have that one said again in easier words.
				</p>
				<p className="help__note">
					It changes the wording, never the facts — the figures, rules and
					sources stay exactly as they were.
				</p>
			</Section>

			<Section title="Listening and speaking" glyph={<MicIcon />}>
				<p>
					Press the <strong>microphone</strong> to talk instead of typing. Press{" "}
					<strong>Play</strong> under any answer to hear it read aloud. The
					sliders button opens voice settings, where you can have every answer
					read out automatically, change the reading speed, and switch between
					English, Spanish and French.
				</p>
				<p className="help__note">
					Each persona has its own voice, and the youngest one reads more
					slowly. Voice is optional and everything works without it.
				</p>
			</Section>

			<Section title="Games" glyph={<ShuffleIcon />}>
				{/* "There are two" — the build ships four. Millionaire and Hangman
				    have been in `game-kinds.ts` and rendering in the thread since
				    they were added, and the panel that tells a reader what the
				    product can do never heard about either of them. */}
				<p>
					Ask <em>"can we play a game"</em> and a card opens in the chat. There
					are four: <strong>Word scramble</strong>, where you unscramble a money
					word; <strong>True or false</strong>, which explains the answer after
					each round; <strong>Millionaire</strong>, four choices a question; and{" "}
					<strong>Hangman</strong>, one letter at a time. You can ask for a clue,
					skip a question, or leave at any point — your score is kept either way.
				</p>
				<p className="help__note">
					Questions are matched to who you are using ASPIRE AI as, so a younger
					reader and a teenager get different sets. The games are a learning
					activity for children and teenagers, so the Imani and Azuri personas
					are not offered them.
				</p>
			</Section>

			<Section title="Checking if you can join">
				<p>
					Ask <em>"am I eligible?"</em> and a short check opens. It asks a few
					questions — age, residency and the like — and tells you where you
					stand, with the rule behind the answer. Nothing you enter there is an
					application, and you can close it at any point.
				</p>
			</Section>

			<Section title="Applying">
				<p>
					Say <em>"I want to sign up"</em> and ASPIRE AI will walk you through
					the application one question at a time, tell you which documents are
					needed, and let you upload them. You can stop partway and pick it up
					again later.
				</p>
				<p className="help__note">
					A child cannot enrol on their own. If a young person starts an
					application, ASPIRE AI will explain that kindly and show how to bring
					in a parent or guardian.
				</p>
			</Section>

			<Section title="What it can and cannot do">
				<p className="help__can">It can:</p>
				<ul className="help__list">
					<li>Answer questions about ASPIRE from published information</li>
					<li>Explain how saving, interest and budgeting work</li>
					<li>Teach a lesson, set a practice question and play a game</li>
					<li>Check eligibility and help fill in an application</li>
					<li>Answer in English, Spanish or French</li>
					<li>Put you in touch with a person when it cannot help</li>
				</ul>
				<p className="help__cannot">It cannot:</p>
				<ul className="help__list">
					<li>
						See your account, your balance, or an application you have already
						sent
					</li>
					<li>
						Tell you what to do with your money. It will explain how something
						works and leave the decision to you — for advice about your own
						situation, speak to the ASPIRE team or a qualified adviser
					</li>
					<li>Make up a figure, a date or a contact detail it does not have</li>
					<li>Change anything on your account, or act on your behalf</li>
				</ul>
				<p className="help__note">
					If it does not know something, it will say so and tell you who does.
					That is a real answer, not a failure.
				</p>
			</Section>

			<Section title="Staying safe">
				<ul className="help__list">
					<li>
						Do not type anything you would not want kept — no passwords, no card
						or bank numbers. ASPIRE AI never needs them and will never ask.
					</li>
					<li>
						Personal details are only ever asked for inside an application, and
						only the ones that application needs.
					</li>
					<li>
						Conversations are saved so you can come back to them. You can rename
						or delete any of them from the list on the left.
					</li>
					<li>
						If you tell ASPIRE AI that you are not safe or that someone is
						hurting you, it will stop talking about money and make sure a person
						who can help is told.
					</li>
					<li>
						ASPIRE AI is a computer program, not a person, and it will always
						say so if you ask.
					</li>
				</ul>
			</Section>

			<Section title="If something goes wrong">
				<p>
					Ask for a person and ASPIRE AI will pass it on, along with the ASPIRE
					team's contact details. If an answer looks wrong, say so — it will
					hold to what it has, and give you the official contact for the last
					word rather than guessing.
				</p>
			</Section>
		</>
	);
}
