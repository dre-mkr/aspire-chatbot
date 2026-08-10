import { useEffect, useState } from "react";

/** Reports whether a media query currently matches. */
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
