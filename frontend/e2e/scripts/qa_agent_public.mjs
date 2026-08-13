/** Signed out. The public corpus, and the route to starting an application. */

export const suite = {
	name: "qa_agent_public",
	identity: "A",
	description: "Q&A for a visitor with no account.",
};

export async function steps() {
	return [
		{
			say: "What is ASPIRE?",
			critical: true,
			expect: { agent: "qa_agent_public", route: true, mustMatch: /ASPIRE/i },
		},
		{
			say: "Where can families find out about ASPIRE?",
			note: "worded to miss the eligibility card's regexes, so the router is consulted",
			expect: { agent: "qa_agent_public" },
		},
		{
			say: "What is my balance?",
			note: "no account exists — an invented figure would be the failure",
			expect: {
				agent: ["qa_agent_public", "escalate_agent"],
				mustNotMatch: /\$\s?\d/,
			},
		},
		{
			say: "I would like to start signing my child up",
			note: "public -> registration: a mid-chat switch on a third identity",
			expect: { agent: "register_agent_step1" },
		},
	];
}
