/**
 * One conversation, eleven turns, four independent probes of the same question:
 * once a lesson is under way, can an ordinary factual question get back to Q&A?
 *
 * Identity D (orion 16-18) is used because `routable()` gives exactly
 * ["qa_agent", "learn_agent"] — a strict two-way choice with no third attractor.
 *
 * Each turn is chosen so a failure names ONE cause:
 *
 *   A   stickiness discarded a correct proposal   -> a "Staying in ..." log line
 *   A'  the classifier itself chose wrong         -> a route line naming learn_agent
 *   B   the tutor claimed the turn                -> learn_turn with no placement
 *   C   cards claimed the turn                    -> a card line and no route line
 *
 * Every probe message was checked against the regexes in
 * backend/app/graph/nodes/intents.py, so `cards` cannot claim it and the router is
 * genuinely consulted.
 */

import fs from "node:fs";
import path from "node:path";

export const suite = {
	name: "routing_one_chat",
	identity: "D",
	description: "Can one chat move between the learning agent and Q&A as the reader does?",
};

const PROBE = "probe";

export async function steps() {
	return [
		{
			say: "What is the ASPIRE programme?",
			critical: true,
			note: "baseline: active_agent is None, so stickiness is inert and this measures the classifier alone",
			expect: { agent: "qa_agent", route: true },
		},
		{
			say: "Teach me about compound interest.",
			critical: true,
			note: "the easy direction, and it arms the tutor",
			expect: { agent: "learn_agent" },
		},
		{
			say: "Why does that matter?",
			note: "GUARD RAIL: short, ambiguous, plainly a continuation. Stickiness exists for this. A fix that breaks this turn is the wrong fix.",
			expect: { agent: "learn_agent" },
		},
		{
			say: "Which papers must a family bring to a branch?",
			kind: PROBE,
			note: "PROBE 1 — a long, specific, factual question mid-lesson",
			expect: { agent: "qa_agent" },
		},
		{
			say: "Teach me about compound interest again.",
			note: "re-arm",
			expect: { agent: "learn_agent" },
		},
		{
			say: "I have a factual question about the ASPIRE programme, not a lesson: which papers must a family bring to a branch?",
			kind: PROBE,
			note: "PROBE 2 — the same question, disambiguated. If this switches and probe 1 did not, the blocker is purely the confidence threshold.",
			expect: { agent: "qa_agent" },
		},
		{
			say: "Give me a different lesson.",
			kind: "tutor-claim",
			note: "no routing decision at all: `wants_a_different_lesson` exists for exactly this, but `_entry` returns the tutor before `branch` is ever reached",
			expect: { agent: "learn_agent" },
		},
		{
			say: "Can we play a game?",
			note: "a card turn, expected by design — does it corrupt what comes after?",
			expect: {},
		},
		{
			say: "When does the application deadline close?",
			kind: PROBE,
			note: "PROBE 3 — the same switch, but after a card turn",
			expect: { agent: "qa_agent" },
		},
		{
			say: "Teach me about budgeting.",
			note: "re-arm with different vocabulary",
			expect: { agent: "learn_agent" },
		},
		{
			say: "How much money does a family need to open an account?",
			kind: PROBE,
			note: "PROBE 4 — different vocabulary, so a topic-specific classifier quirk is distinguishable from a structural block",
			expect: { agent: "qa_agent" },
		},
	];
}

function classify(record) {
	const route = record.backend?.route;
	const sticky = record.backend?.sticky;
	const agent = record.wire?.usage?.agent ?? null;

	if (agent === "qa_agent") return { blocker: null, detail: "switched" };
	if (sticky) {
		return {
			blocker: "A",
			detail: `stickiness kept ${sticky.kept}: ${sticky.proposed} proposed at ${sticky.confidence}, threshold ${sticky.threshold}`,
		};
	}
	if (!route) {
		return { blocker: "C", detail: "the router was never consulted (claimed before classify)" };
	}
	return {
		blocker: "A'",
		detail: `the classifier itself chose ${route.agent} at ${route.confidence} (active=${route.active}, reason=${route.reason})`,
	};
}

export async function report(ctx, records) {
	const steps_ = await steps();
	for (const [index, step] of steps_.entries()) {
		if (records[index]) records[index].kind = step.kind || null;
	}

	const probes = records.filter((record) => record.kind === PROBE);
	const findings = probes.map((record) => ({
		turn: record.n,
		said: record.sent,
		agent: record.wire?.usage?.agent ?? null,
		...classify(record),
	}));

	const claim = records.find((record) => record.kind === "tutor-claim");
	const claimLines = claim?.backend?.lines || [];
	const tutorClaimed =
		claimLines.some((line) => /learn_turn concept_id=/.test(line)) &&
		!claimLines.some((line) => /placement session=/.test(line));

	const guardRail = records[2];
	const counts = {};
	for (const finding of findings) {
		const key = finding.blocker || "switched";
		counts[key] = (counts[key] || 0) + 1;
	}

	const lines = [
		"# Mid-chat routing: diagnosis",
		"",
		`Identity D (orion 16-18), one conversation, ${records.length} turns.`,
		`Probes that reached Q&A: **${counts.switched || 0} of ${findings.length}**.`,
		"",
		"| turn | probe | agent | verdict |",
		"|---|---|---|---|",
	];
	for (const finding of findings) {
		lines.push(
			`| ${finding.turn} | ${String(finding.said).slice(0, 60)}${String(finding.said).length > 60 ? "…" : ""} | ${finding.agent} | ${finding.blocker ? `**blocker ${finding.blocker}** — ${finding.detail}` : "switched"} |`,
		);
	}

	lines.push(
		"",
		"## Blocker B — the tutor's claim on every turn",
		"",
		tutorClaimed
			? '**Confirmed.** "Give me a different lesson." was answered by the tutor: a `learn_turn` line with no `placement` line. ' +
					"`_entry` (backend/app/agents/learn/graph.py) returns `tutor` before `branch`, where `wants_a_different_lesson` is checked, is ever reached."
			: claim
				? "Not reproduced: the lesson was re-placed as designed."
				: "Not measured.",
		"",
		"## Guard rail",
		"",
		guardRail?.pass
			? "`Why does that matter?` correctly stayed in the lesson. Any fix must keep this passing."
			: `**The guard rail failed** (${guardRail?.reasons?.join("; ")}), so stickiness is not doing its job either.`,
		"",
	);

	fs.mkdirSync(ctx.dir, { recursive: true });
	fs.writeFileSync(path.join(ctx.dir, "diagnosis.md"), lines.join("\n"));
	fs.writeFileSync(
		path.join(ctx.dir, "diagnosis.json"),
		JSON.stringify({ findings, tutorClaimed, guardRail: guardRail?.pass ?? null, counts }, null, 2),
	);
	console.log(`\n  diagnosis: ${JSON.stringify(counts)}${tutorClaimed ? " + blocker B" : ""}`);
}
