/**
 * The tap-not-type surface.
 *
 * Two to four large cards. For bands 5-8 and 9-12 these are the PRIMARY way to
 * reply and the text input is secondary; for older bands they are a
 * convenience under an ordinary chat.
 *
 * ## Sizes are not decoration
 *
 * 44x44 CSS pixels is the WCAG 2.1 floor and the minimum here. Band 5-8 gets
 * 64pt of height and 18px type, because a six-year-old's tap is imprecise and a
 * missed tap reads to them as the app ignoring them -- which is the single
 * fastest way to lose a young user.
 *
 * ## The fallback chip
 *
 * A learning turn that arrives with no quick replies renders one "Keep going"
 * chip rather than nothing. The server already re-prompts for chips and falls
 * back to the same string (`safety_out`), so this is the second net under the
 * same hole: a dead end in a tap-first interface is a child stuck with no
 * visible way forward and a keyboard they may not use.
 */
import { useAgeBand } from "./AgeBandProvider";

export interface QuickReply {
	label: string;
	/** What is actually sent. Usually the label; sometimes a fuller sentence. */
	value: string;
}

/** The fallback, per locale. Matches the server's own fallback string. */
const KEEP_GOING: Record<string, string> = {
	en: "Keep going",
	es: "Seguimos",
	fr: "On continue",
};

export function QuickReplies({
	options,
	onPick,
	locale = "en",
	/**
	 * Whether this turn came from the learning agent.
	 *
	 * Only a learning turn gets the fallback chip. A Q&A answer with no
	 * suggestions is a finished answer, and inventing a "Keep going" under it
	 * would invite somebody to continue a conversation that is complete.
	 */
	isLesson = false,
	disabled = false,
}: {
	options: Array<QuickReply>;
	onPick: (value: string) => void;
	locale?: string;
	isLesson?: boolean;
	disabled?: boolean;
}) {
	const band = useAgeBand();

	const chips =
		options.length > 0
			? options.slice(0, 4)
			: isLesson
				? [
						{
							label: KEEP_GOING[locale] ?? KEEP_GOING.en,
							value: KEEP_GOING[locale] ?? KEEP_GOING.en,
						},
					]
				: [];

	if (chips.length === 0) return null;

	const youngest = band.band === "5-8";

	return (
		// A fieldset with a hidden legend, rather than a div with role="group".
		// Both announce as a group; only this one does it with the element the
		// platform already has, so it needs no ARIA to be understood and cannot
		// drift out of step with it. The default border and padding are removed
		// because a box around chat replies is not what a fieldset looks like
		// here.
		<fieldset
			className="quick-replies"
			style={{
				display: "grid",
				// One per row for the youngest band. Two side by side at 375px is
				// two 160px targets, and 160px is not a card a six-year-old aims at.
				gridTemplateColumns: youngest
					? "1fr"
					: "repeat(auto-fit, minmax(min(100%, 11rem), 1fr))",
				gap: youngest ? "0.75rem" : "0.5rem",
				marginBlockStart: "0.75rem",
				border: "none",
				margin: "0.75rem 0 0",
				padding: 0,
				minInlineSize: "auto",
			}}
		>
			<legend
				style={{
					position: "absolute",
					width: "1px",
					height: "1px",
					overflow: "hidden",
					clip: "rect(0, 0, 0, 0)",
					whiteSpace: "nowrap",
				}}
			>
				Suggested replies
			</legend>
			{chips.map((chip) => (
				<button
					key={chip.value}
					type="button"
					disabled={disabled}
					onClick={() => onPick(chip.value)}
					style={{
						minHeight: `${band.touchTarget}px`,
						minWidth: "44px",
						fontSize: youngest
							? "18px"
							: `${Math.max(15, band.typeScale - 1)}px`,
						lineHeight: 1.35,
						padding: youngest ? "1rem 1.25rem" : "0.625rem 1rem",
						borderRadius: "0.875rem",
						// Semantic tokens only. The palette lives in styles.css and a
						// hex value here would be a colour the theme cannot correct.
						border: "1px solid var(--hairline)",
						background: "var(--wash-6)",
						color: "var(--plum-deep)",
						fontWeight: 600,
						textAlign: "left",
						cursor: disabled ? "default" : "pointer",
						opacity: disabled ? 0.5 : 1,
						// Under 600ms and only on a property that does not reflow.
						transition: "background-color 140ms ease, transform 140ms ease",
					}}
					onPointerDown={(event) => {
						// A press state a child can see. Transform only, so it cannot
						// shift anything around it.
						event.currentTarget.style.transform = "scale(0.98)";
					}}
					onPointerUp={(event) => {
						event.currentTarget.style.transform = "";
					}}
					onPointerLeave={(event) => {
						event.currentTarget.style.transform = "";
					}}
				>
					{chip.label}
				</button>
			))}
		</fieldset>
	);
}

/**
 * The "type instead" affordance for the youngest band.
 *
 * Small, quiet, and always present. The input is collapsed behind it, never
 * removed -- see `AgeBandProvider.inputCollapsed` for why that distinction is
 * the whole point.
 */
export function TypeInstead({ onOpen }: { onOpen: () => void }) {
	const band = useAgeBand();
	if (!band.inputCollapsed) return null;

	return (
		<button
			type="button"
			onClick={onOpen}
			style={{
				minHeight: "44px",
				marginBlockStart: "0.5rem",
				padding: "0.5rem 0.75rem",
				background: "transparent",
				border: "none",
				color: "var(--quiet)",
				fontSize: "15px",
				textDecoration: "underline",
				textUnderlineOffset: "3px",
				cursor: "pointer",
			}}
		>
			…or type instead
		</button>
	);
}
