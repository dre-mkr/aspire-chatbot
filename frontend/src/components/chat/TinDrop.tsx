import { useEffect } from "react";
import { addCoins } from "#/lib/aspire/tin";
import type { TinDirective } from "#/lib/stream/types";

/** Coins landing in the Tin: a small inline drop, bigger on a milestone. */
export function TinDrop({ directive }: { directive: TinDirective }) {
	const { delta, coins, milestone, caption } = directive;
	// Banked on sight, so My Journey's tin holds the running device total.
	useEffect(() => addCoins(delta), [delta]);
	return (
		<div className="tin-drop" data-milestone={milestone || undefined}>
			<span className="tin-drop__coin" aria-hidden="true">
				🪙
			</span>
			<span className="tin-drop__text">
				<strong>+{delta}</strong> {caption.replace(/^[+¡]*\+?\d+\s*/, "")}
			</span>
			<span className="tin-drop__total">{coins}</span>
		</div>
	);
}
