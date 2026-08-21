import { type ReactElement, useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { ChevronRightIcon } from "#/components/icons";
import { type PersonaId, personaById } from "#/lib/aspire/personas";
import {
	CloudMark,
	GeneralMark,
	RocketMark,
	ScholarMark,
	StarMark,
} from "./GuideMascots";

/**
 * One guide, in the order a family meets them: youngest reader outwards.
 *
 * The name is not written here. It lives in `PERSONAS`, which mirrors the
 * backend's `names.py`, and is read below -- a guide's label changed twice in
 * two commits and this file was the copy that kept the old one. What is written
 * here is what this screen alone knows: the mascot, and blurbs pitched at a
 * family choosing rather than at the composer menu.
 */
const GUIDES: ReadonlyArray<{
	id: PersonaId;
	who: string;
	blurb: string;
	Mark: (props: { className?: string }) => ReactElement;
}> = [
	{
		id: "stella",
		who: "Ages 5–12",
		blurb: "Simple words, shorter answers and easy explanations.",
		Mark: CloudMark,
	},
	{
		id: "orion",
		who: "Ages 13–18",
		blurb: "Fuller explanations, games, challenges and activities.",
		Mark: RocketMark,
	},
	{
		id: "aurora",
		who: "Parent or guardian",
		blurb: "Practical answers about the programme and your child's learning.",
		Mark: StarMark,
	},
	{
		id: "nova",
		who: "Teacher or educator",
		blurb: "Clear explanations and teaching support you can use with learners.",
		Mark: ScholarMark,
	},
];

/**
 * Who is reading, asked once, before the first question.
 *
 * The band already decides the voice, the vocabulary ladder, the examples and
 * the check questions -- and until now the only way to set it was a control in
 * the composer that a first-time reader has no reason to open. A twelve-year-old
 * and a guardian got the same default and the same answers.
 *
 * Every option leaves immediately: this asks one thing and then gets out of the
 * way. Skipping is a real choice, not a dark pattern, so it sits in the frame
 * rather than behind a corner glyph.
 */
export function GuideChooser({
	onChoose,
	onSkip,
}: {
	/** `null` is the general option: balanced answers, no band. */
	onChoose: (persona: PersonaId | null) => void;
	onSkip: () => void;
}) {
	const titleId = useId();
	const describedById = useId();
	const panelRef = useRef<HTMLDivElement>(null);

	// Focus the panel, NOT the first guide. Focusing a button paints its ring on
	// arrival, and a ring around the first card reads as "this one is the
	// recommended one" -- exactly the thing a chooser with no default must not
	// say. From here Tab still reaches the guides in order.
	useEffect(() => {
		panelRef.current?.focus();
	}, []);

	// Escape skips. A chooser that cannot be dismissed is a wall, and the
	// general option is a perfectly good answer.
	useEffect(() => {
		const onKey = (event: KeyboardEvent) => {
			if (event.key === "Escape") {
				event.stopPropagation();
				onSkip();
				return;
			}
			if (event.key !== "Tab") return;
			// Contain the tab ring: everything behind this is inert while it is open.
			const focusable =
				panelRef.current?.querySelectorAll<HTMLElement>("button");
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
		document.addEventListener("keydown", onKey, true);
		return () => document.removeEventListener("keydown", onKey, true);
	}, [onSkip]);

	// The page behind must not scroll under an open chooser.
	//
	// STATELESS, and it has to be. Two earlier shapes both leaked, and a leaked
	// lock is not cosmetic: `body` stays `overflow: hidden` for the rest of the
	// session, the landing page cannot be scrolled by hand, and 128px of it --
	// the whole footer -- becomes unreachable.
	//
	// Saving and restoring the previous value fails when two choosers overlap:
	// the second captures the "hidden" the first just set and hands it back on
	// the way out. A counter fails too, more quietly -- React invokes effects
	// twice in development and HMR resets module state underneath it, so the
	// count desyncs from reality and never returns to zero.
	//
	// Presence in the DOM is the one thing that cannot desync. Released on the
	// next frame, because at cleanup time this chooser's own portal may not be
	// gone yet.
	useEffect(() => {
		document.body.style.overflow = "hidden";
		return () => {
			requestAnimationFrame(() => {
				if (!document.querySelector(".guide-scrim")) {
					document.body.style.removeProperty("overflow");
				}
			});
		};
	}, []);

	return createPortal(
		<div className="guide-scrim">
			<div
				className="guide"
				role="dialog"
				aria-modal="true"
				aria-labelledby={titleId}
				aria-describedby={describedById}
				ref={panelRef}
				tabIndex={-1}
			>
				<div className="guide__head">
					<h2 className="guide__title" id={titleId}>
						Choose your ASPIRE AI guide
					</h2>
					<p className="guide__lede">Tell us who is using ASPIRE AI today.</p>
					<p className="guide__note" id={describedById}>
						We will match you with the guide written for you. You can change
						your guide at any time.
					</p>
				</div>

				<ul className="guide__list">
					{GUIDES.map((guide) => (
						<li key={guide.id}>
							<button
								type="button"
								className="guide-card"
								onClick={() => onChoose(guide.id)}
							>
								<guide.Mark className="guide-card__mark" />
								<span className="guide-card__text">
									<span
										className={`guide-card__who guide-card__who--${guide.id}`}
									>
										{guide.who}
									</span>
									<span className="guide-card__name">
										Meet <b>{personaById(guide.id)?.name ?? guide.who}</b>
									</span>
									<span className="guide-card__blurb">{guide.blurb}</span>
								</span>
								<ChevronRightIcon />
							</button>
						</li>
					))}
				</ul>

				<p className="guide__divider">
					<span>Not sure which guide fits?</span>
				</p>

				<button
					type="button"
					className="guide-card guide-card--general"
					onClick={() => onChoose(null)}
				>
					<GeneralMark className="guide-card__mark" />
					<span className="guide-card__text">
						<span className="guide-card__name">
							Continue with ASPIRE AI <b>General</b>
						</span>
						<span className="guide-card__blurb">
							Balanced answers for a mixed audience.
						</span>
					</span>
					<ChevronRightIcon />
				</button>

				<button type="button" className="guide__skip" onClick={onSkip}>
					Skip for now
				</button>
			</div>
		</div>,
		document.body,
	);
}
