/**
 * Case 13: the same three questions, asked as three different readers.
 *
 * The persona layer is composed into every prompt (`prompting/builder.py`), but
 * the golden set's own comment records that persona "is not currently wired in
 * the client", so it may never have rendered in front of the client at all.
 * Three suites ask identical questions so the transcripts can be laid side by
 * side; each also asserts the properties its own band is supposed to have.
 *
 * The cross-persona comparison is the part a single suite cannot make -- it is
 * done after the run by `judging-compare.mjs`, which reads the three
 * `turns.json` files and fails if the answers are not materially different.
 */

/** Identical for all three, so any difference is the persona layer's doing. */
export const QUESTIONS = [
	"How does saving money actually help me?",
	"What happens to the money in an ASPIRE account?",
	"Why does interest matter?",
];

/**
 * What each band's answers must be true of on their own.
 *
 * Stella is the strict one: `safety_out` strips links for her and caps her word
 * count, and a percentage figure is exactly the kind of detail her card is
 * meant to keep out.
 */
const EXPECTATIONS = {
	stella: {
		// A five-to-twelve reader gets no figures-as-percentages and no links.
		mustNotMatch: [/\b\d+(\.\d+)?\s?%/, /\bhttps?:\/\//, /\[.+?\]\(.+?\)/],
	},
	orion: {
		mustNotMatch: [/\bhttps?:\/\//],
	},
	aurora: {},
};

export function probeSteps(persona) {
	const want = EXPECTATIONS[persona] || {};
	return QUESTIONS.map((say) => ({
		say,
		expect: { nonEmpty: true, ...want },
	}));
}
