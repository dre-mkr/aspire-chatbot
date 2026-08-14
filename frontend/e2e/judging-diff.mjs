#!/usr/bin/env node
/**
 * Did this run break anything that was working?
 *
 *   node e2e/judging-diff.mjs <runId>
 *
 * Most of the judging suite is red on purpose: the cases are written against
 * what has to be true on 20 Aug, not against today. A gate that just demands
 * green would be switched off within the hour, and one that ignores reds
 * entirely would let a fix for case 2 quietly break case 3.
 *
 * So the gate is the *difference*. `baseline/judging.json` lists the failures
 * that were already there and names the task that closes each. This exits
 * non-zero on any failure not in that list, and reports fixed ones so the
 * baseline can be tightened as the work lands.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));

function main() {
	const runId = process.argv[2];
	if (!runId) throw new Error("usage: node e2e/judging-diff.mjs <runId>");

	const baseline = JSON.parse(fs.readFileSync(path.join(HERE, "baseline", "judging.json"), "utf8"));
	const summaryPath = path.join(HERE, "artifacts", runId, "summary.json");
	if (!fs.existsSync(summaryPath)) throw new Error(`no summary.json for run ${runId}`);
	const results = JSON.parse(fs.readFileSync(summaryPath, "utf8"));

	const regressions = [];
	const fixed = [];
	const stillKnown = [];

	for (const result of results) {
		const known = baseline.known[result.suite] || [];
		const knownNumbers = new Set(known.map((entry) => entry.n));
		const failedNumbers = new Set(result.failures.map((failure) => failure.n));

		for (const failure of result.failures) {
			const entry = known.find((candidate) => candidate.n === failure.n);
			if (entry) stillKnown.push({ suite: result.suite, ...entry });
			else regressions.push({ suite: result.suite, ...failure });
		}

		// Only claim a fix for a suite this run actually exercised.
		if (result.total > 0) {
			for (const number of knownNumbers) {
				if (!failedNumbers.has(number)) {
					fixed.push({ suite: result.suite, ...known.find((entry) => entry.n === number) });
				}
			}
		}
	}

	const skipped = results.reduce((total, result) => total + (result.skipped || 0), 0);
	if (skipped) {
		console.log(`${skipped} assertion(s) skipped — a deployed run cannot read the log. Not passes.\n`);
	}

	if (fixed.length) {
		console.log(`fixed since the baseline (${fixed.length}) — tighten baseline/judging.json:`);
		for (const entry of fixed) console.log(`  + ${entry.suite} ${entry.n}. ${entry.label}  [${entry.closes}]`);
		console.log("");
	}

	if (stillKnown.length) {
		console.log(`still open (${stillKnown.length}):`);
		for (const entry of stillKnown) console.log(`  · ${entry.suite} ${entry.n}. ${entry.label}  [${entry.closes}]`);
		console.log("");
	}

	if (regressions.length) {
		console.error(`REGRESSIONS (${regressions.length}) — these were not failing before:`);
		for (const entry of regressions) {
			console.error(`  - ${entry.suite} ${entry.n}. ${entry.label}`);
			for (const reason of entry.reasons || []) console.error(`      ${reason}`);
		}
		process.exit(1);
	}

	console.log("no regressions.");
}

main();
