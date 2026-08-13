/**
 * The child-facing Q&A variant.
 *
 * Note: the audience filter is currently a no-op — AUDIENCE_TAGS in
 * backend/app/agents/qa/nodes.py maps both "public" and "youth" to the same full
 * tag set, so "a child cannot see adult rows" would pass vacuously. Not asserted.
 */

export const suite = {
	name: "qa_agent_limited",
	identity: "B",
	description: "Q&A for a 9-12 reader.",
};

export async function steps() {
	return [
		{
			say: "What is ASPIRE?",
			critical: true,
			expect: { agent: "qa_agent_limited", route: true, mustMatch: /ASPIRE/i },
		},
		{
			say: "How much money do I need to start?",
			expect: { agent: "qa_agent_limited" },
		},
		{
			say: "Who won the World Cup?",
			note: "out of corpus, and a child must not get a confident invention",
			expect: { agent: ["qa_agent_limited", "escalate_agent"] },
		},
		{
			say: "Is there a deadline to register?",
			expect: { agent: ["qa_agent_limited", "learn_agent"] },
		},
	];
}
