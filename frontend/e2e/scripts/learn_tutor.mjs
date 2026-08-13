/**
 * The topic tutor — the other machine inside learn_agent.
 *
 * `asks_about_a_topic` claims the opener, which sets `active_concept_id`. From that
 * point `_entry` returns "tutor" for every turn the learn agent receives, whatever
 * the reader typed. That claim is the thing the routing suite measures.
 */

export const suite = {
	name: "learn_tutor",
	identity: "C",
	description: "Concept resolution and re-explanation for a 13-15 reader.",
};

export async function steps() {
	return [
		{
			say: "Can you explain what compound interest is?",
			critical: true,
			expect: {
				agent: "learn_agent",
				log: [/learn_turn concept_id=/],
				noLog: [/placement session=/],
			},
		},
		{
			say: "Why does that matter?",
			expect: { agent: "learn_agent", log: [/learn_turn concept_id=/] },
		},
		{
			say: "I don't really get it.",
			expect: { agent: "learn_agent" },
		},
		{
			say: "What about budgeting?",
			note: "a different concept, still the tutor",
			expect: { agent: "learn_agent", log: [/learn_turn concept_id=/] },
		},
		{
			say: "Explain quantum chromodynamics.",
			note: "off corpus: declining is right, inventing physics is not",
			expect: { agent: "learn_agent", mustNotMatch: /\bquark|gluon\b/i },
		},
	];
}
