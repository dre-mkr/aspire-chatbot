#!/usr/bin/env node
/**
 * Case 13's real assertion: are the three personas actually different?
 *
 *   node e2e/judging-compare.mjs <runId>
 *
 * Each `judging_persona_*` suite asks the same three questions, so any
 * difference between the transcripts is the persona layer doing its job. If the
 * three answers to a question are near-identical, the layer is composed into
 * the prompt and changing nothing -- which is the failure the client would read
 * as "it talks to my six-year-old the same way it talks to me".
 *
 * Exits non-zero if any question fails to differentiate.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PERSONAS = ["stella", "orion", "aurora"];

/** Below this, two answers are saying the same thing in the same words. */
const TOO_SIMILAR = 0.8;

const words = (text) =>
	new Set(
		String(text || "")
			.toLowerCase()
			.replace(/[^a-z0-9\s]/g, " ")
			.split(/\s+/)
			.filter((word) => word.length > 3),
	);

/** Jaccard over content words -- crude, but it does not need to be subtle. */
function similarity(a, b) {
	const left = words(a);
	const right = words(b);
	if (!left.size || !right.size) return 0;
	let shared = 0;
	for (const word of left) if (right.has(word)) shared += 1;
	return shared / (left.size + right.size - shared);
}

function load(runId, persona) {
	const file = path.join(HERE, "artifacts", runId, `judging_persona_${persona}`, "turns.json");
	if (!fs.existsSync(file)) throw new Error(`missing ${path.relative(HERE, file)} — run the suite first`);
	return JSON.parse(fs.readFileSync(file, "utf8")).turns.filter((turn) => turn.sent);
}

function main() {
	const runId = process.argv[2];
	if (!runId) throw new Error("usage: node e2e/judging-compare.mjs <runId>");

	const byPersona = Object.fromEntries(PERSONAS.map((persona) => [persona, load(runId, persona)]));
	const count = Math.min(...PERSONAS.map((persona) => byPersona[persona].length));
	const failures = [];
	const rows = [];

	for (let index = 0; index < count; index++) {
		const asked = byPersona.stella[index].sent;
		const answers = Object.fromEntries(
			PERSONAS.map((persona) => [persona, byPersona[persona][index]?.ui?.lastAnswer || ""]),
		);
		const lengths = Object.fromEntries(PERSONAS.map((persona) => [persona, words(answers[persona]).size]));

		rows.push(
			`\n${index + 1}. ${asked}\n` +
				PERSONAS.map((persona) => `   ${persona.padEnd(7)} ${String(lengths[persona]).padStart(4)} content words`).join("\n"),
		);

		for (const [left, right] of [
			["stella", "orion"],
			["stella", "aurora"],
			["orion", "aurora"],
		]) {
			const score = similarity(answers[left], answers[right]);
			rows.push(`   ${left}/${right}: ${score.toFixed(2)}`);
			if (score >= TOO_SIMILAR) {
				failures.push(`Q${index + 1} ${left} and ${right} are ${score.toFixed(2)} similar — the persona layer changed nothing`);
			}
		}

		// Stella should be the shortest of the three. Not a hard rule, but if she
		// is the longest something is wrong with the band caps.
		if (lengths.stella > lengths.aurora) {
			failures.push(`Q${index + 1} stella (${lengths.stella}) ran longer than aurora (${lengths.aurora})`);
		}
	}

	console.log(rows.join("\n"));
	if (failures.length) {
		console.error(`\n${failures.length} problem(s):`);
		for (const failure of failures) console.error(`  - ${failure}`);
		process.exit(1);
	}
	console.log("\nthe three personas are materially different.");
}

main();
