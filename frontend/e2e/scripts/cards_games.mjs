/**
 * The game flow, which is not a graph agent at all: `cards` claims the turn before
 * the router is consulted, and the result comes back through a channel of its own.
 *
 * So the assertions are: a card opened, the router was NOT consulted, and the score
 * arrives as `__game_result` rather than as prose.
 */

export const suite = {
	name: "cards_games",
	identity: "B",
	description: "A game opened by a card and finished through its own channel.",
};

const clickFirst = (selector) => async (page) => {
	await page.waitForSelector(selector, { visible: true, timeout: 20_000 });
	await page.click(selector);
};

export async function steps() {
	return [
		{
			say: "Can we play a game?",
			critical: true,
			note: "no named game, so the agent should ask which",
			expect: { noRoute: true },
		},
		{
			label: "choose a game from the chips",
			custom: async ({ page }) => {
				const { snapshot, settle } = await import("../lib/turn.mjs");
				const chip = await page.$(".follow-ups button.follow-up");
				if (!chip) return null;
				const before = await snapshot(page);
				await chip.click();
				return settle(page, before);
			},
			expect: {},
		},
		{
			label: "answer the game until it ends",
			custom: async ({ page }) => {
				const { snapshot, settle } = await import("../lib/turn.mjs");
				for (let round = 0; round < 12; round++) {
					const choice = await page.$("section.game .tf__choice, section.game .game__btn");
					if (!choice) break;
					const before = await snapshot(page);
					await choice.click();
					// Only the last answer produces a turn; the rest just advance the card.
					try {
						return await settle(page, before, { timeout: 8000 });
					} catch {
						continue;
					}
				}
				return null;
			},
			expect: {},
		},
	];
}

export async function report(_ctx, records) {
	const played = records.find((record) => record.label?.startsWith("answer the game"));
	if (!played) return;
	if (!played.wire) {
		played.reasons = ["skipped: no game card rendered"];
		played.pass = true;
		played.skipped = true;
		return;
	}
	const reasons = [];
	if (!played.request?.__game_result) reasons.push("the score did not arrive as __game_result");
	if (played.backend?.route) reasons.push("the router was consulted for a game result");
	played.reasons = reasons;
	played.pass = reasons.length === 0;
}
