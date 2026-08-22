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

import { type AgeBand, GUIDES, type PersonaId } from "#/lib/aspire/personas";

/** The ring colour a guide is remembered by, keyed to the guide id. */
const RING: Record<string, string> = {
	skye: "#C22F99",
	kaleb: "#3B82F6",
	zion: "#F4B000",
	imani: "#5C3AAE",
	azuri: "#0DAE93",
};

/** Pill background and text, per guide. Tinted from the ring, not neutral. */
const PILL: Record<string, { bg: string; fg: string }> = {
	skye: { bg: "#FCE5F3", fg: "#D72B91" },
	kaleb: { bg: "#E8F2FF", fg: "#2F7FE9" },
	zion: { bg: "#FFF1D5", fg: "#C88710" },
	imani: { bg: "#EEE6FF", fg: "#6435B6" },
	azuri: { bg: "#DDF7F1", fg: "#098B76" },
};

/**
 * One line on what changes, shown on hover and focus.
 *
 * Not printed under every avatar: five permanent paragraphs turn a row that
 * reads in two seconds into one that has to be studied.
 */
const HINT: Record<string, string> = {
	skye: "Simple, gentle explanations and playful learning.",
	kaleb: "Straight answers, real money words and challenges.",
	zion: "Direct, practical and sourced guidance.",
	imani: "Clear answers and next steps for families.",
	azuri: "Precise, sourced support for educators.",
};

/** Spoken aloud, so it says what the tap does and who it is for. */
const SPOKEN: Record<string, string> = {
	skye: "Choose Skye, the ASPIRE guide for ages 5 to 8",
	kaleb: "Choose Kaleb, the ASPIRE guide for ages 9 to 12",
	zion: "Choose Zion, the ASPIRE guide for ages 13 to 18",
	imani: "Choose Imani, the ASPIRE guide for parents and guardians",
	azuri: "Choose Azuri, the ASPIRE guide for teachers and educators",
};

/** The five guides, in reading order. `guest` is not one of them -- see above. */
const ROW = GUIDES.filter((guide) => guide.guideId !== "guest");

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
			<h2 className="guide-selector__heading" id={headingId}>
				<span className="guide-selector__heading-icon" aria-hidden="true">
					<i className="ph-bold ph-users-three" />
				</span>
				Meet your guides
			</h2>

			<div className="guide-selector__grid">
				{ROW.map((guide) => {
					const id = guide.guideId;
					const chosen = selected === id;
					const pill = PILL[id];
					return (
						<button
							key={id}
							type="button"
							className="guide-card"
							style={
								{
									"--guide-color": RING[id],
									"--guide-pill-bg": pill?.bg,
									"--guide-pill-fg": pill?.fg,
								} as React.CSSProperties
							}
							// `aria-pressed` rather than `aria-selected`: this is a button
							// that stays on, and `aria-selected` belongs to options inside a
							// listbox or a tab in a tablist. Neither is what this is.
							aria-pressed={chosen}
							aria-label={SPOKEN[id]}
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
							onMouseLeave={() => setHovered((was) => (was === id ? null : was))}
							onFocus={() => setHovered(id)}
							onBlur={() => setHovered((was) => (was === id ? null : was))}
						>
							<span className="guide-card__pill">{guide.audience}</span>

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
								{HINT[id]}
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
