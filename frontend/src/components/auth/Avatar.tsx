/** The person mark. */

interface AvatarProps {
	/** Whose face this is, used to say so out loud. */
	name?: string | null;
	url?: string | null;
	size?: number;
}

export function Avatar({ name, url, size = 36 }: AvatarProps) {
	// Named for whoever it belongs to.
	const label = name ? `${name}'s profile` : "Your profile";

	if (url) {
		return (
			<img
				className="avatar"
				src={url}
				alt={label}
				width={size}
				height={size}
				style={{ width: size, height: size }}
			/>
		);
	}

	return (
		<svg
			className="avatar"
			width={size}
			height={size}
			viewBox="0 0 48 48"
			role="img"
			aria-label={label}
			style={{ width: size, height: size }}
		>
			<circle cx="24" cy="24" r="24" fill="var(--plum)" />
			<circle cx="24" cy="18.5" r="7.4" fill="#fff" />
			{/* Shoulders clipped by the circle: one arc, correct at any size. */}
			<path
				d="M8.6 42.4a15.9 15.9 0 0 1 30.8 0A23.9 23.9 0 0 1 24 48a23.9 23.9 0 0 1-15.4-5.6Z"
				fill="#fff"
			/>
		</svg>
	);
}
