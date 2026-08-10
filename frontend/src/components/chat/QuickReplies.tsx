/** The tap-not-type surface. */
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
	/** Whether this turn came from the learning agent. */
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
		<fieldset
			className="quick-replies"
			style={{
				display: "grid",
				// One per row for the youngest band.
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
						// Semantic tokens only.
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
						// A press state a child can see.
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

/** The "type instead" affordance for the youngest band. */
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
