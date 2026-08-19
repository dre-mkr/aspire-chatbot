/**
 * The five marks on the guide chooser.
 *
 * Drawn here rather than pulled from an emoji or an icon set: these are the
 * only place a reader meets a guide as a character rather than as a name, and
 * a system glyph renders differently on every platform the Federation's
 * schools actually use. Flat fills, one geometry, no shading -- they sit at
 * 56px and must stay legible at 40.
 */

const FACE = "#2d2a45";

/** Two eyes and a smile, shared so no guide's expression drifts from another's. */
function Face({
	x,
	y,
	spread = 7,
	smile = 5,
}: {
	x: number;
	y: number;
	spread?: number;
	smile?: number;
}) {
	return (
		<g>
			<circle cx={x - spread / 2} cy={y} r="1.9" fill={FACE} />
			<circle cx={x + spread / 2} cy={y} r="1.9" fill={FACE} />
			<path
				d={`M${x - smile / 2} ${y + 4.2} Q${x} ${y + 7.6} ${x + smile / 2} ${y + 4.2}`}
				fill="none"
				stroke={FACE}
				strokeWidth="1.7"
				strokeLinecap="round"
			/>
		</g>
	);
}

/** The small four-point sparkles that mark a guide as a guide. */
function Sparkle({ x, y, r }: { x: number; y: number; r: number }) {
	return (
		<path
			d={`M${x} ${y - r} Q${x + r * 0.24} ${y - r * 0.24} ${x + r} ${y} Q${x + r * 0.24} ${y + r * 0.24} ${x} ${y + r} Q${x - r * 0.24} ${y + r * 0.24} ${x - r} ${y} Q${x - r * 0.24} ${y - r * 0.24} ${x} ${y - r} Z`}
			fill="currentColor"
		/>
	);
}

interface MarkProps {
	className?: string;
}

/** Ages 5 to 12. A cloud, because the youngest band reads pictures first. */
export function CloudMark({ className }: MarkProps) {
	return (
		<svg
			viewBox="0 0 56 56"
			className={className}
			aria-hidden="true"
			focusable="false"
		>
			<circle cx="28" cy="28" r="28" fill="#dcecfd" />
			<g color="#8fc0f2">
				<Sparkle x={12} y={16} r={3.4} />
				<Sparkle x={45} y={20} r={2.6} />
				<Sparkle x={41} y={40} r={2.2} />
			</g>
			<path
				d="M18 38h20a8 8 0 0 0 1-15.9A11 11 0 0 0 18.6 20 7.5 7.5 0 0 0 18 38Z"
				fill="#fff"
				stroke="#8fc0f2"
				strokeWidth="1.6"
				strokeLinejoin="round"
			/>
			<circle cx="20.5" cy="30.5" r="2.6" fill="#f9c6d9" opacity="0.75" />
			<circle cx="35.5" cy="30.5" r="2.6" fill="#f9c6d9" opacity="0.75" />
			<Face x={28} y={28} spread={9} smile={6.5} />
		</svg>
	);
}

/** Ages 13 to 18. A rocket: the band that is going somewhere. */
export function RocketMark({ className }: MarkProps) {
	return (
		<svg
			viewBox="0 0 56 56"
			className={className}
			aria-hidden="true"
			focusable="false"
		>
			<circle cx="28" cy="28" r="28" fill="#e7ddfa" />
			<g color="#a98ede">
				<Sparkle x={13} y={19} r={3.2} />
				<Sparkle x={44} y={17} r={2.4} />
				<Sparkle x={14} y={40} r={2.2} />
			</g>
			{/* Flame first, so the body's edge sits over it. */}
			<path
				d="M24 40.5c1.2 4 2.6 6.2 4 6.6 1.4-.4 2.8-2.6 4-6.6Z"
				fill="#f6a723"
			/>
			<path
				d="M25.9 41c.8 2.6 1.5 4 2.1 4.3.6-.3 1.3-1.7 2.1-4.3Z"
				fill="#fcd34d"
			/>
			{/* Fins. */}
			<path d="M22.2 32.6 17 37.4c-.5.5-.2 1.3.5 1.4l5.2.6Z" fill="#7c5cc4" />
			<path d="M33.8 32.6 39 37.4c.5.5.2 1.3-.5 1.4l-5.2.6Z" fill="#7c5cc4" />
			{/* Body. */}
			<path
				d="M28 9.5c4.6 4 7.2 10.2 7.2 17.2 0 5-1.1 9.6-2.6 13.1H23.4c-1.5-3.5-2.6-8.1-2.6-13.1 0-7 2.6-13.2 7.2-17.2Z"
				fill="#fff"
				stroke="#7c5cc4"
				strokeWidth="1.6"
				strokeLinejoin="round"
			/>
			<path d="M23.4 39.8h9.2l-1.1 2.6h-7Z" fill="#7c5cc4" />
			<Face x={28} y={24.5} spread={8} smile={6} />
		</svg>
	);
}

/** A parent or guardian. A star, warm and steady. */
export function StarMark({ className }: MarkProps) {
	return (
		<svg
			viewBox="0 0 56 56"
			className={className}
			aria-hidden="true"
			focusable="false"
		>
			<circle cx="28" cy="28" r="28" fill="#fdeccb" />
			<g color="#f3c164">
				<Sparkle x={13} y={17} r={3.2} />
				<Sparkle x={44} y={20} r={2.5} />
				<Sparkle x={42} y={41} r={2.2} />
			</g>
			<path
				d="m28 9.6 5.4 11.3 12.3 1.7-8.9 8.7 2.2 12.4L28 37.8l-11 5.9 2.2-12.4-8.9-8.7 12.3-1.7Z"
				fill="#f9bf24"
				stroke="#e0a015"
				strokeWidth="1.5"
				strokeLinejoin="round"
			/>
			<circle cx="21.6" cy="28.4" r="2.5" fill="#f28aa8" opacity="0.6" />
			<circle cx="34.4" cy="28.4" r="2.5" fill="#f28aa8" opacity="0.6" />
			<Face x={28} y={26} spread={8.4} smile={6.2} />
		</svg>
	);
}

/** A teacher or educator. The same star, with the glasses. */
export function ScholarMark({ className }: MarkProps) {
	return (
		<svg
			viewBox="0 0 56 56"
			className={className}
			aria-hidden="true"
			focusable="false"
		>
			<circle cx="28" cy="28" r="28" fill="#e2e5fa" />
			<g color="#9aa2e4">
				<Sparkle x={13} y={18} r={3.2} />
				<Sparkle x={44} y={19} r={2.5} />
				<Sparkle x={41} y={41} r={2.2} />
			</g>
			<path
				d="m28 9.6 5.4 11.3 12.3 1.7-8.9 8.7 2.2 12.4L28 37.8l-11 5.9 2.2-12.4-8.9-8.7 12.3-1.7Z"
				fill="#5560c6"
				stroke="#3f47a0"
				strokeWidth="1.5"
				strokeLinejoin="round"
			/>
			{/* Glasses, drawn over the face line so the eyes read through them. */}
			<g fill="none" stroke="#eef0ff" strokeWidth="1.7">
				<circle cx="23.7" cy="26.2" r="3.9" fill="#c9cef4" fillOpacity="0.5" />
				<circle cx="32.3" cy="26.2" r="3.9" fill="#c9cef4" fillOpacity="0.5" />
				<path d="M27.6 26.2h.8" strokeLinecap="round" />
			</g>
			<circle cx="23.7" cy="26.2" r="1.8" fill="#20244a" />
			<circle cx="32.3" cy="26.2" r="1.8" fill="#20244a" />
			<path
				d="M25 31.4q3 3 6 0"
				fill="none"
				stroke="#20244a"
				strokeWidth="1.7"
				strokeLinecap="round"
			/>
		</svg>
	);
}

/** The general option. Two people, not a character: it is a setting, not a guide. */
export function GeneralMark({ className }: MarkProps) {
	return (
		<svg
			viewBox="0 0 56 56"
			className={className}
			aria-hidden="true"
			focusable="false"
		>
			<circle cx="28" cy="28" r="28" fill="#e9e2f8" />
			<g fill="#6b42a1">
				<circle cx="21.5" cy="23" r="5.6" />
				<path d="M11.4 39.4a10.1 10.1 0 0 1 20.2 0 1.4 1.4 0 0 1-1.4 1.5H12.8a1.4 1.4 0 0 1-1.4-1.5Z" />
			</g>
			<g fill="#a482d8">
				<circle cx="36.6" cy="24.6" r="4.6" />
				<path d="M28.6 38.6a8.2 8.2 0 0 1 16 0 1.3 1.3 0 0 1-1.3 1.4H29.9a1.3 1.3 0 0 1-1.3-1.4Z" />
			</g>
		</svg>
	);
}
