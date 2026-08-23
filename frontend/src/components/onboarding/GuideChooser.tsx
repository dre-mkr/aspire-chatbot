import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { ChevronRightIcon } from "#/components/icons";
import {
	CHOOSABLE_GUIDES,
	type Guide,
	type PersonaId,
} from "#/lib/aspire/personas";
import { GeneralMark } from "./GuideMascots";

/**
 * THIS LIST OFFERED FOUR GUIDES. The product has five.
 *
 * It predated the Skye/Kaleb split and had never been updated: `stella` was
 * listed once, labelled "Ages 5–12", while every other surface splits that
 * range into Skye at 5–8 and Kaleb at 9–12. So an eleven-year-old who answered
 * this dialog was given Skye, and the same eleven-year-old choosing from the
 * landing row was given Kaleb — two different voices, two different reading
 * levels, from the same question asked twice.
 *
 * It also drew its own mascots: a cloud, a rocket, a star and a scholar, for
 * five guides who have illustrated faces used everywhere else in the product.
 * A reader met an abstract shape here and a person on the next screen.
 *
 * Both are gone. The list is `GUIDES`, the faces are the guides' own, and the
 * only mark still drawn here is the one for General — which is not a person.
 */

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
	/**
	 * `null` is the general option: balanced answers, no band.
	 *
	 * The guide row rides along because a persona key alone cannot say which of
	 * Skye and Kaleb was chosen — they are one key and two bands, which is
	 * exactly the distinction this dialog used to lose.
	 */
	onChoose: (persona: PersonaId | null, guide?: Guide) => void;
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
					{CHOOSABLE_GUIDES.map((guide: Guide) => (
						<li key={guide.guideId}>
							<button
								type="button"
								className="guide__card"
								onClick={() => onChoose(guide.persona, guide)}
							>
								<span className="guide__card-face" aria-hidden="true">
									<picture>
										<source
											srcSet={`/guides/${guide.guideId}.webp`}
											type="image/webp"
										/>
										<img
											src={`/guides/${guide.guideId}.png`}
											alt=""
											width={480}
											height={480}
											loading="lazy"
											decoding="async"
										/>
									</picture>
								</span>
								<span className="guide__card-text">
									<span
										className="guide__card-who"
										style={{ color: guide.pillFg }}
									>
										{guide.audience}
									</span>
									<span className="guide__card-name">
										Meet <b>{guide.name}</b>
									</span>
									<span className="guide__card-blurb">
										{guide.chooserBlurb}
									</span>
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
					className="guide__card guide__card--general"
					onClick={() => onChoose(null)}
				>
					<GeneralMark className="guide__card-mark" />
					<span className="guide__card-text">
						<span className="guide__card-name">
							Continue with ASPIRE AI <b>General</b>
						</span>
						<span className="guide__card-blurb">
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
