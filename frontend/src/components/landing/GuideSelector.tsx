/**
 * Meet your guides: five audience-specific ways in, not five profile pictures.
 *
 * The hierarchy is audience -> face -> name, in that order, and the order is
 * the whole point. The pill answers "which one is mine?" before the reader has
 * to know who Skye or Azuri is; the face makes them want to meet them; the ring
 * colour is what they remember it by; the name is what builds the relationship.
 * Reversed -- name first -- it is five strangers and a guessing game.
 *
 * DATA-DRIVEN ON PURPOSE, and driven from `GUIDES` rather than a list of its
 * own. `GUIDES` already carries the persona key and the age band for each
 * guide, and those two values are what the server actually routes on. A second
 * list here would be a second source of truth for the one thing that must not
 * drift: Skye and Kaleb are separate keys now, and the row that renders them
 * has to agree with the row that mints the token.
 *
 * Each guide is a BUTTON. Not an image with a click handler -- a button, so it
 * is reachable by keyboard and announced as an action, which matters more here
 * than anywhere else in the product given who is using it.
 *
 * Guest is deliberately absent. It is the safe state BEFORE a guide is chosen,
 * not a sixth guide, and putting it in the row would blunt the one thing the
 * row does well: five clearly different audiences. It sits underneath as a
 * quiet way past.
 */

import { useId, useState } from "react";

import {
	type AgeBand,
	CHOOSABLE_GUIDES,
	type PersonaId,
} from "#/lib/aspire/personas";

/**
 * The ring colour, the chip colours, the hover hint and the spoken label used
 * to be four maps in this file, keyed by guide id, sitting beside a fifth copy
 * of the ring colours in `LandingScreen`. They are fields on the guide now —
 * see `GUIDES` — so a guide added to the product cannot arrive here with no
 * colour and no spoken name.
 */
const ROW = CHOOSABLE_GUIDES;

export interface GuideSelectorProps {
	/** The guide id currently chosen, or null before anything is. */
	selected?: string | null;
	/** Called with everything the caller needs to route the conversation. */
	onChoose: (choice: {
		guideId: string;
		persona: PersonaId;
		band?: AgeBand;
		name: string;
		audience: string;
	}) => void;
	/** Offered under the row. Omitted where there is nothing to skip to. */
	onSkip?: () => void;
	/**
	 * How big the avatars are.
	 *
	 * `hero` is the designed size. `compact` exists because the landing page
	 * holds itself to one viewport with no scroll, and at `hero` this row alone
	 * is taller than the space that rule leaves.
	 */
	size?: "hero" | "compact";
}

export function GuideSelector({
	selected = null,
	onChoose,
	onSkip,
	size = "hero",
}: GuideSelectorProps) {
	const headingId = useId();
	const [hovered, setHovered] = useState<string | null>(null);

	return (
		<section
			className={`guide-selector guide-selector--${size}`}
			aria-labelledby={headingId}
		>
			{/* The glyph that sat here was in Tailwind's blue-500, a colour this
			    product does not use, and it was the only section heading on the
			    page wearing an icon. Five faces below it are already the picture. */}
			<h2 className="guide-selector__heading" id={headingId}>
				Meet your guides
			</h2>

			<div className="guide-selector__grid">
				{ROW.map((guide) => {
					const id = guide.guideId;
					const chosen = selected === id;
					return (
						<button
							key={id}
							type="button"
							className="guide-card"
							style={
								{
									"--guide-color": guide.colour,
									"--guide-pill-bg": guide.pillBg,
									"--guide-pill-fg": guide.pillFg,
								} as React.CSSProperties
							}
							// `aria-pressed` rather than `aria-selected`: this is a button
							// that stays on, and `aria-selected` belongs to options inside a
							// listbox or a tab in a tablist. Neither is what this is.
							aria-pressed={chosen}
							aria-label={guide.spoken}
							aria-describedby={`${headingId}-${id}-hint`}
							onClick={() =>
								onChoose({
									guideId: id,
									persona: guide.persona,
									band: guide.band,
									name: guide.name,
									audience: guide.audience,
								})
							}
							onMouseEnter={() => setHovered(id)}
							onMouseLeave={() =>
								setHovered((was) => (was === id ? null : was))
							}
							onFocus={() => setHovered(id)}
							onBlur={() => setHovered((was) => (was === id ? null : was))}
						>
							<span className="guide-card__pill">{guide.pill}</span>

							<span className="guide-card__avatar">
								<picture>
									<source srcSet={`/guides/${id}.webp`} type="image/webp" />
									<img
										src={`/guides/${id}.png`}
										alt=""
										width={480}
										height={480}
										loading="lazy"
										decoding="async"
									/>
								</picture>
							</span>

							<span className="guide-card__name">
								{guide.name}
								{chosen ? (
									<i
										className="ph-bold ph-check guide-card__check"
										aria-hidden="true"
									/>
								) : null}
							</span>

							{/* Always in the tree so `aria-describedby` resolves; shown only
							    on hover or focus, so the row stays readable at a glance. */}
							<span
								className="guide-card__hint"
								id={`${headingId}-${id}-hint`}
								data-visible={hovered === id ? "true" : undefined}
							>
								{guide.hint}
							</span>
						</button>
					);
				})}
			</div>

			{onSkip ? (
				<p className="guide-selector__skip">
					<button type="button" onClick={onSkip}>
						Not sure? Continue as Guest
					</button>
				</p>
			) : null}
		</section>
	);
}
