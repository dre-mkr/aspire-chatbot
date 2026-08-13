/**
 * The default agent, and the two handoffs that cross it.
 *
 * Identity D (orion 16-18) reaches exactly `qa_agent` and `learn_agent`, so a
 * switch has one alternative and no third attractor.
 */

export const suite = {
	name: "qa_agent",
	identity: "D",
	description: "Grounded Q&A, a refusal, and the handoff in both directions.",
};

export async function steps() {
	return [
		{
			say: "What is the ASPIRE programme?",
			critical: true,
			expect: { agent: "qa_agent", route: true, mustMatch: /ASPIRE/i, citations: true },
		},
		{
			say: "How long has it been running?",
			note: "a follow-up: staying in Q&A is correct",
			expect: { agent: "qa_agent", mustMatch: /\S/ },
		},
		{
			say: "Which branches are on Nevis?",
			expect: { agent: "qa_agent", citations: true },
		},
		{
			say: "What is the capital of France?",
			note: "out of corpus — the ground check is what is under test",
			expect: {
				agent: ["qa_agent", "escalate_agent"],
				mustNotMatch: /\bParis\b/i,
			},
		},
		{
			say: "Teach me about compound interest.",
			note: "qa -> learn. Either the classifier or QA's own _delegate may do it.",
			expect: { agent: "learn_agent" },
		},
		{
			say: "Which papers must a family bring to a branch?",
			note: "learn -> qa, the direction under investigation",
			expect: { agent: "qa_agent" },
		},
	];
}
