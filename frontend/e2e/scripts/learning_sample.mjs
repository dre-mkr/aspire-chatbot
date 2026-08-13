/**
 * The taster lesson for a visitor with no account, and the switch out of it.
 *
 * The last turn is a second, independent instance of the mid-chat switch on a
 * different identity and a different pair of agents: if a fix only unsticks
 * learn -> qa, this stays broken and says so.
 */

export const suite = {
	name: "learning_sample",
	identity: "A",
	description: "A signed-out taster lesson, then a switch to registration.",
};

export async function steps() {
	return [
		{
			say: "Can I try one of the money lessons?",
			critical: true,
			expect: { agent: "learning_sample", route: true },
		},
		{ say: "Keep going.", expect: { agent: "learning_sample" } },
		{ say: "That makes sense, what is next?", expect: { agent: "learning_sample" } },
		{
			say: "I want to sign up.",
			note: "learning_sample -> register_agent_step1",
			expect: { agent: "register_agent_step1" },
		},
	];
}
