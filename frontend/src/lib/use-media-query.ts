import { useEffect, useState } from "react";

/**
 * Reports whether a media query currently matches.
 *
 * Returns `false` on the server and for the first client paint, so markup is
 * identical on both sides and hydration stays quiet. Layout that must be right
 * before JS runs belongs in a CSS media query instead — this is for behaviour
 * that genuinely differs, like a sidebar that becomes a modal drawer.
 */
export function useMediaQuery(query: string) {
	const [matches, setMatches] = useState(false);

	useEffect(() => {
		const list = window.matchMedia(query);
		const sync = () => setMatches(list.matches);

		sync();
		list.addEventListener("change", sync);
		return () => list.removeEventListener("change", sync);
	}, [query]);

	return matches;
}
