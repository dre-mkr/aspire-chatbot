/**
 * The person mark.
 *
 * Drawn rather than shipped as a PNG. The supplied asset was 48×48, which is
 * soft above about 24px on a retina screen, and this appears at 36px in the
 * sidebar — so it would have needed a 2× export at minimum. A path costs
 * nothing, is exact at every size, and takes the plum from the same token the
 * rest of the product uses instead of baking `#482977` into a file.
 *
 * A user-supplied image is honoured when there is one. There is no upload here
 * yet; this only has to render `avatarUrl` correctly when something else starts
 * setting it.
 */

interface AvatarProps {
	/** Whose face this is, used to say so out loud. */
	name?: string | null;
	url?: string | null;
	size?: number;
}

export function Avatar({ name, url, size = 36 }: AvatarProps) {
	// Named for whoever it belongs to. "Avatar" alone tells a screen-reader user
	// nothing they could not already guess from the button around it.
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
			{/* The shoulders, clipped by the circle rather than drawn to fit it —
			    one arc that stays correct at any size. */}
			<path
				d="M8.6 42.4a15.9 15.9 0 0 1 30.8 0A23.9 23.9 0 0 1 24 48a23.9 23.9 0 0 1-15.4-5.6Z"
				fill="#fff"
			/>
		</svg>
	);
}
