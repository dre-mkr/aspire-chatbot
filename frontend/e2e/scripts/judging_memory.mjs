/**
 * Case 14: does a long conversation still know what it was told?
 *
 * Two facts are planted -- one early, one in the middle -- and asked for at the
 * end. The middle one is the point. `SUMMARY_AFTER_MESSAGES = 12` summarises
 * everything older than the last twelve messages, while `RECENT_TURNS = 6`
 * sends only the last six verbatim, so messages -12 to -7 are in neither. The
 * fact planted at exchange 8 lands in that gap by the time it is asked for.
 *
 * The filler turns are deliberately dull and on-corpus: they exist to push the
 * planted facts back through the window, not to test anything themselves.
 */

export const suite = {
	name: "judging_memory",
	identity: "A",
	description: "A fact planted early and one planted mid-thread, both recalled at the end.",
};

/** Kept on-corpus so a decline does not add an unplanned turn shape. */
const FILLER = [
	"What is a budget?",
	"Why is saving important?",
	"What does interest mean?",
	"How does a savings account work?",
	"What is the difference between saving and investing?",
	"What is a financial goal?",
	"Why do people make a spending plan?",
	"What does it mean to earn money?",
	"What is a bank?",
	"What is compound interest?",
];

export async function steps() {
	const steps = [
		{ say: "Hello, I would like to learn about money.", expect: { nonEmpty: true } },

		// Planted fact one. Early enough that it is inside the summary by the end.
		{
			say: "Please remember that my daughter is called Marisol and she is nine.",
			label: "plant #1 (Marisol, nine)",
			expect: { nonEmpty: true },
		},
	];

	// Exchanges 3-7: filler, to push plant #1 out of the verbatim window.
	for (const say of FILLER.slice(0, 5)) steps.push({ say, expect: { nonEmpty: true } });

	// Planted fact two, at exchange 8 -- the one that falls into the gap.
	steps.push({
		say: "One more thing to remember: we are saving for her secondary school uniform.",
		label: "plant #2 (secondary school uniform)",
		expect: { nonEmpty: true },
	});

	// Exchanges 9-13: filler, to carry plant #2 past the verbatim window.
	for (const say of FILLER.slice(5)) steps.push({ say, expect: { nonEmpty: true } });

	// ORDER MATTERS, and it is the whole test.
	//
	// Count in messages, two per exchange. Asking at turn 14 there are 26 before
	// it (indices 0-25): the summary covers [:-12] = 0-13, the verbatim window is
	// the last 6 = 20-25, and 14-19 is the hole. Plant #2 is exchange 8, so it
	// sits at indices 14-15 -- inside the hole, at turn 14 and only at turn 14.
	//
	// By turn 15 there are 28 messages, [:-12] reaches index 15, and the fact has
	// slid into the summary where it can be recalled again. Asking the two
	// questions the other way round passes for that reason and proves nothing;
	// it did, the first time this ran.
	steps.push(
		{
			say: "And what did I say we were saving for?",
			label: "recall #2 first -- this is the turn where it sits in the blind spot",
			expect: { mustMatch: /uniform/i },
		},
		{
			say: "What is my daughter's name and how old is she?",
			label: "recall #1 (deep in the summary by now)",
			expect: { mustMatch: /Marisol/i },
		},
	);

	return steps;
}
