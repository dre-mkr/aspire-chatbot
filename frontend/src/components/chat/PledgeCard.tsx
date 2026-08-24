import { say } from "#/lib/aspire/i18n";
import type { PledgeDirective } from "#/lib/stream/types";

/**
 * A savings pledge, made signable.
 *
 * A goal said in chat evaporates; a card with a button is a small ceremony.
 * Signing sends a plain message the cards node reads and stores, so the pledge
 * needs no new transport -- the button IS a chip with gravitas.
 */
export function PledgeCard({
	directive,
	send,
}: {
	directive: PledgeDirective;
	send: (value: string) => void;
}) {
	const { amount_line, goal, button_label, button_value, pledged } = directive;
	return (
		<div className="pledge" data-pledged={pledged || undefined}>
			<p className="pledge__eyebrow">
				{pledged ? say("pledgeMine") : say("pledgeOffer")}
			</p>
			<p className="pledge__amount">{amount_line}</p>
			{goal ? (
				<p className="pledge__goal">
					{say("towards")} {goal}
				</p>
			) : null}
			{pledged ? (
				<p className="pledge__sealed">{say("pledgeSealed")} ✓</p>
			) : (
				<button
					type="button"
					className="pledge__sign"
					onClick={() => send(button_value)}
				>
					{button_label}
				</button>
			)}
		</div>
	);
}
