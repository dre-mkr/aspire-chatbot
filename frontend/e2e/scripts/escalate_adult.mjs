/**
 * Escalation for an adult, and the trap it leaves behind.
 *
 * `escalate_agent` is unroutable by design, so the router is never involved: `cards`
 * claims "I want a person" and jumps straight to it.
 *
 * The last turn is the interesting one. The escalation subgraph persists
 * `active_agent = "escalate_agent"`, and `apply_stickiness` tests membership against
 * `allowed_agents` — which contains it — rather than the routable set. If the next
 * turn's proposal lands below the threshold, stickiness hands back an unroutable
 * agent and the belt-and-braces branch forces `allowed[0]`. The reply looks fine
 * either way, so only the ERROR line catches it.
 */

export const suite = {
	name: "escalate_adult",
	identity: "E",
	description: "Human handoff, a complaint, and the turn immediately after.",
};

export async function steps() {
	return [
		{
			say: "Can I speak to a real person?",
			critical: true,
			expect: {
				agent: "escalate_agent",
				noRoute: true,
				log: [/Escalating as \S+ without the router/, /escalation ticket=/],
			},
		},
		{
			say: "What are the branch opening hours?",
			note: "THE TRAP: an ordinary question straight after an escalation",
			expect: {
				agent: "qa_agent",
				noLog: [/Classifier escaped the allowed list/],
			},
		},
		{
			say: "I want to make a complaint.",
			expect: {
				agent: "escalate_agent",
				log: [/escalation ticket=\S+ priority=\S+ category=complaint/],
			},
		},
	];
}
