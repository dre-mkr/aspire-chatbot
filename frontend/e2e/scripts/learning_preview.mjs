/**
 * A guardian looking at what their child is being taught. Non-scoring: nothing here
 * may write mastery (backend/app/agents/learn/graph.py, NON_SCORING_AGENTS).
 *
 * The last turn is a third instance of the mid-chat switch, out of a third agent.
 */

export const suite = {
	name: "learning_preview",
	identity: "E",
	description: "Guardian preview of the lessons, then a switch back to Q&A.",
};

export async function steps() {
	return [
		{
			say: "What is my son being taught this week?",
			critical: true,
			expect: { agent: "learning_preview", route: true },
		},
		{
			say: "Show me the lessons my child has finished.",
			expect: { agent: "learning_preview" },
		},
		{
			say: "Can I see the next one?",
			note: "a continuation: staying is correct",
			expect: { agent: "learning_preview" },
		},
		{
			say: "Which papers must a family bring to a branch?",
			note: "learning_preview -> qa_agent",
			expect: { agent: "qa_agent" },
		},
	];
}
