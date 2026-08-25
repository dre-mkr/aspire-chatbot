import { useEffect } from "react";
import { collect } from "#/lib/aspire/collectibles";
import type { CollectibleDirective } from "#/lib/stream/types";

/** The shiny drop: an artifact earned by finishing a played story. */
export function CollectibleCard({
	directive,
}: {
	directive: CollectibleDirective;
}) {
	const { name, emoji, caption, topic } = directive;
	// Shelved the moment it is seen, so My Journey has it from now on.
	useEffect(() => collect({ name, emoji, topic }), [name, emoji, topic]);
	return (
		<div className="collectible">
			<span className="collectible__emoji" aria-hidden="true">
				{emoji}
			</span>
			<p className="collectible__name">{name}</p>
			<p className="collectible__caption">{caption}</p>
		</div>
	);
}
