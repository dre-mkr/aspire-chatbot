/**
 * The curriculum lesson machine — place, teach, check, hint, and a digression.
 *
 * The opener matters: `_NAMES_NOTHING` in backend/app/agents/learn/graph.py sends
 * "Teach me something." down the phase table, while "Teach me about X" is claimed by
 * the topic tutor instead. Those are two different machines; this suite drives the
 * first one, learn_tutor drives the second.
 */

export const suite = {
	name: "learn_curriculum",
	identity: "B",
	description: "The placement-and-check lesson machine, for a 9-12 reader.",
};

export async function steps() {
	return [
		{
			say: "Teach me something.",
			critical: true,
			note: "names no topic, so the phase table runs rather than the tutor",
			expect: {
				agent: "learn_agent",
				log: [/placement session=/],
				noLog: [/learn_turn concept_id=/],
			},
		},
		{
			say: "i do not know",
			note: "a lesson reply, not a new enquiry — the hint ladder should start",
			expect: { agent: "learn_agent" },
		},
		{
			say: "hint",
			expect: { agent: "learn_agent" },
		},
		{
			say: "saving money for a goal",
			note: "an on-topic attempt; correctness is the agent's business, not the harness's",
			expect: { agent: "learn_agent" },
		},
		{
			say: "What is the weather like?",
			note: "An off-topic aside is answered rather than steered back: the router moves it before the lesson's `_digress` path is ever reached. Confirmed as the intended behaviour, so `_digress` and the `off_topic` flag are dead on this path.",
			expect: { agent: "qa_agent_limited" },
		},
		{
			label: "widget: Done (if one rendered)",
			custom: async ({ page }) => {
				const button = await page.$("figure.w-panel .w-actions .w-btn:not(.w-btn--quiet)");
				if (!button) return null; // no widget this turn; not a failure
				const { snapshot, settle } = await import("../lib/turn.mjs");
				const before = await snapshot(page);
				await button.click();
				return settle(page, before);
			},
			expect: {},
		},
		{
			say: "That's enough for today.",
			expect: { agent: "learn_agent" },
		},
	];
}
