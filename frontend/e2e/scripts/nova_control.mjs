/**
 * The control. Identity F (nova/educator) can reach exactly one routable agent, so
 * `classify` short-circuits with no model call and no route line at all.
 *
 * If this suite fails, the fault is the harness or the environment — never routing.
 */

export const suite = {
	name: "nova_control",
	identity: "F",
	description: "One routable agent, so the router is never consulted.",
};

export async function steps() {
	return [
		{
			say: "What is the ASPIRE programme?",
			critical: true,
			expect: {
				agent: "qa_agent",
				// Absence of a route line IS the assertion: len(allowed) == 1 returns early.
				noRoute: true,
				mustMatch: /ASPIRE/i,
			},
		},
		{
			say: "Who runs it?",
			expect: { agent: "qa_agent", noRoute: true },
		},
		{
			say: "Teach me about saving money.",
			note: "nova cannot reach any learning agent, so this must stay in Q&A",
			expect: { agent: "qa_agent", noRoute: true },
		},
	];
}
