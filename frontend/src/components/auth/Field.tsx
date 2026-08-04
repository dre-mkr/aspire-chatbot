import { useId, useState } from "react";

/**
 * One labelled input, with its icon, its hint and its error.
 *
 * The error lives with the field rather than in a banner at the top of the
 * form. A message about the password belongs beside the password: a summary at
 * the top makes somebody scan back down to work out which box it means, and on
 * a phone it is usually off screen by the time they are typing.
 */

export type FieldIcon =
	| "mail"
	| "lock"
	| "user"
	| "calendar"
	| "school"
	| "phone";

const PATHS: Record<FieldIcon, ReactPath> = {
	mail: [
		<rect key="r" x="2" y="4" width="20" height="16" rx="2" />,
		<path key="p" d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />,
	],
	lock: [
		<rect key="r" x="3" y="11" width="18" height="11" rx="2" />,
		<path key="p" d="M7 11V7a5 5 0 0 1 10 0v4" />,
	],
	user: [
		<path key="p" d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />,
		<circle key="c" cx="12" cy="7" r="4" />,
	],
	calendar: [
		<rect key="r" x="3" y="4" width="18" height="18" rx="2" />,
		<path key="a" d="M16 2v4" />,
		<path key="b" d="M8 2v4" />,
		<path key="c" d="M3 10h18" />,
	],
	school: [
		<path key="a" d="M22 10v6" />,
		<path key="b" d="M2 10l10-5 10 5-10 5z" />,
		<path key="c" d="M6 12v5c0 1.7 2.7 3 6 3s6-1.3 6-3v-5" />,
	],
	phone: [
		<path
			key="p"
			d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.4-1.2a2 2 0 0 1 2.1-.5c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z"
		/>,
	],
};

type ReactPath = Array<React.ReactElement>;

function Glyph({ icon }: { icon: FieldIcon }) {
	return (
		<svg
			width="19"
			height="19"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			strokeWidth="1.9"
			strokeLinecap="round"
			strokeLinejoin="round"
			aria-hidden="true"
		>
			{PATHS[icon]}
		</svg>
	);
}

interface FieldProps {
	label: string;
	icon: FieldIcon;
	type?: string;
	value: string;
	onChange: (value: string) => void;
	placeholder?: string;
	disabled?: boolean;
	hint?: string;
	error?: string;
	autoComplete?: string;
	/** Password fields get a reveal control; nothing else does. */
	revealable?: boolean;
	inputMode?: "text" | "email" | "numeric" | "tel";
}

export function Field({
	label,
	icon,
	type = "text",
	value,
	onChange,
	placeholder,
	disabled,
	hint,
	error,
	autoComplete,
	revealable,
	inputMode,
}: FieldProps) {
	const id = useId();
	const describedBy = `${id}-note`;
	const [revealed, setRevealed] = useState(false);
	const resolvedType = revealable && revealed ? "text" : type;

	return (
		<div className="field">
			<label className="field__label" htmlFor={id}>
				{label}
			</label>
			<div className="field__box" data-disabled={disabled || undefined}>
				<span className="field__icon" data-error={error ? "" : undefined}>
					<Glyph icon={icon} />
				</span>
				<input
					id={id}
					className="field__input"
					type={resolvedType}
					value={value}
					placeholder={placeholder}
					disabled={disabled}
					autoComplete={autoComplete}
					inputMode={inputMode}
					data-reveal={revealable || undefined}
					data-error={error ? "" : undefined}
					// The error is announced with the field rather than separately,
					// so a screen reader hears the problem while on the input it
					// belongs to.
					aria-invalid={error ? true : undefined}
					aria-describedby={hint || error ? describedBy : undefined}
					onChange={(event) => onChange(event.currentTarget.value)}
				/>
				{revealable ? (
					<button
						type="button"
						className="field__reveal"
						aria-label={revealed ? "Hide password" : "Show password"}
						aria-pressed={revealed}
						onClick={() => setRevealed((on) => !on)}
					>
						<svg
							width="19"
							height="19"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							strokeWidth="1.9"
							strokeLinecap="round"
							strokeLinejoin="round"
							aria-hidden="true"
						>
							{revealed ? (
								<>
									<path d="M10.7 5.1A10.9 10.9 0 0 1 12 5c6.4 0 10 7 10 7a17.6 17.6 0 0 1-2.3 3.3" />
									<path d="M6.6 6.6A17.6 17.6 0 0 0 2 12s3.6 7 10 7a10.9 10.9 0 0 0 4.4-.9" />
									<path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
									<path d="m2 2 20 20" />
								</>
							) : (
								<>
									<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7z" />
									<circle cx="12" cy="12" r="3" />
								</>
							)}
						</svg>
					</button>
				) : null}
			</div>
			{error ? (
				<span className="field__error" id={describedBy} role="alert">
					<svg width="15" height="15" viewBox="0 0 24 24" aria-hidden="true">
						<circle
							cx="12"
							cy="12"
							r="9"
							fill="none"
							stroke="currentColor"
							strokeWidth="2"
						/>
						<path
							d="M12 8v4M12 16h.01"
							fill="none"
							stroke="currentColor"
							strokeWidth="2"
							strokeLinecap="round"
						/>
					</svg>
					{error}
				</span>
			) : hint ? (
				<span className="field__hint" id={describedBy}>
					{hint}
				</span>
			) : null}
		</div>
	);
}
