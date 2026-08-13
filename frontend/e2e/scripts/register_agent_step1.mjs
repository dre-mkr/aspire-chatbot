/**
 * Starting an application before signing in.
 *
 * Two negatives matter more than the happy path: this walk must never ask an
 * anonymous child to upload identity documents, and must never collect a sensitive
 * guardian slot. Today it avoids both by an ordering accident — `_needs_document`
 * (backend/app/agents/register/graph.py) calls `pick_slot` without
 * `allow_sensitive=False`, and merely happens to land on a non-document slot.
 */

export const suite = {
	name: "register_agent_step1",
	identity: "A",
	description: "The signed-out application start, and its handoff.",
};

export async function steps() {
	return [
		{
			say: "I would like to start signing my child up",
			critical: true,
			expect: {
				agent: "register_agent_step1",
				route: true,
				noDirective: ["upload"],
			},
		},
		{ say: "I am their mother.", expect: { agent: "register_agent_step1", noDirective: ["upload"] } },
		{ say: "Saint George Basseterre", expect: { agent: "register_agent_step1", noDirective: ["upload"] } },
		{
			say: "What happens next?",
			expect: {
				agent: "register_agent_step1",
				noDirective: ["upload"],
				// Nothing sensitive may be collected without a signed-in adult.
				noLog: [/\[collected: (national_id|date_of_birth|full_name)\]/],
			},
		},
	];
}
