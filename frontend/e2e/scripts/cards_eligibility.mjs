/**
 * The eligibility questionnaire: a card, claimed before the router, answered over
 * its own HTTP endpoints rather than through the graph. So only the first turn is a
 * graph turn at all — the rest are DOM steps.
 */

export const suite = {
	name: "cards_eligibility",
	identity: "E",
	description: "The eligibility check, opened by a card and answered in place.",
};

export async function steps() {
	return [
		{
			// The card is not part of the graph turn: the directive arrives, then the
			// client fetches /api/eligibility/state and mounts it. So the turn settling
			// is not the card rendering, and the wait has to be separate.
			say: "Am I eligible?",
			critical: true,
			expect: { noRoute: true, allowEmpty: true, directive: "eligibility" },
		},
		{
			label: "the card mounts after its own round trip",
			domOnly: async ({ page }) => {
				await page.waitForSelector("section.game.elig", {
					visible: true,
					timeout: 30_000,
				});
			},
		},
		{
			label: "answer through to a verdict",
			domOnly: async ({ page }) => {
				for (let step = 0; step < 15; step++) {
					const done = await page.$(".elig__verdict[data-verdict]");
					if (done) return;
					const option = await page.$("section.game.elig button.elig__option");
					if (!option) return;
					await option.click();
					await new Promise((resolve) => setTimeout(resolve, 700));
				}
			},
		},
		{
			say: "What was that check about?",
			note: "back to a normal turn afterwards",
			expect: { agent: "qa_agent" },
		},
	];
}

export async function report({ page }, records) {
	const walked = records.find((record) => record.label?.startsWith("answer through"));
	if (!walked) return;
	const verdict = await page.$eval(".elig__verdict", (node) => node.getAttribute("data-verdict")).catch(() => null);
	walked.verdict = verdict;
	walked.reasons = verdict ? [] : ["the questionnaire never reached a verdict"];
	walked.pass = !!verdict;
}
