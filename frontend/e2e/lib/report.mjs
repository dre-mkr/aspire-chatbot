/** Artifacts: what happened, in a form both a person and a re-run can read. */

import fs from "node:fs";
import path from "node:path";

export function writeSuite(dir, suite, records, extra = {}) {
	fs.mkdirSync(dir, { recursive: true });

	fs.writeFileSync(
		path.join(dir, "turns.json"),
		JSON.stringify({ suite: suite.name, identity: suite.identity, ...extra, turns: records }, null, 2),
	);

	const lines = [`# ${suite.name}`, "", `Identity **${suite.identity}**. ${suite.description || ""}`, ""];
	for (const record of records) {
		const mark = record.pass ? "PASS" : "FAIL";
		lines.push(`## ${record.n}. ${mark} — ${record.label}`);
		if (record.sent) lines.push("", `> ${record.sent}`);
		const agent = record.wire?.usage?.agent ?? "—";
		const route = record.backend?.route;
		lines.push(
			"",
			`\`agent=${agent}\`` +
				(route
					? ` \`route=${route.agent} conf=${route.confidence} sticky=${route.sticky} active=${route.active}\``
					: " `route=(router not consulted)`") +
				(record.wire?.usage?.cached ? " **cached**" : ""),
		);
		const answer = (record.ui?.lastAnswer || "").trim();
		if (answer) {
			lines.push("", answer.split("\n").map((line) => `    ${line}`).join("\n"));
		}
		const kinds = (record.wire?.directives || []).map((d) => d?.t || d?.type);
		if (kinds.length) lines.push("", `directives: ${kinds.join(", ")}`);
		if (record.ui?.chips?.length) lines.push("", `chips: ${record.ui.chips.join(" | ")}`);
		if (!record.pass) lines.push("", ...record.reasons.map((reason) => `- ${reason}`));
		lines.push("");
	}
	fs.writeFileSync(path.join(dir, "transcript.md"), lines.join("\n"));
}

export function writeSummary(root, results) {
	fs.mkdirSync(root, { recursive: true });
	fs.writeFileSync(path.join(root, "summary.json"), JSON.stringify(results, null, 2));

	const rows = ["# ASPIRE agent suites", "", "| suite | identity | turns | passed | failed |", "|---|---|---|---|---|"];
	for (const result of results) {
		rows.push(
			`| ${result.suite} | ${result.identity} | ${result.total} | ${result.passed} | ${result.failed} |`,
		);
	}
	rows.push("");
	for (const result of results) {
		if (!result.failed) continue;
		rows.push(`## ${result.suite}`, "");
		for (const failure of result.failures) {
			rows.push(`- **${failure.n}. ${failure.label}** — ${failure.reasons.join("; ")}`);
		}
		rows.push("");
	}
	fs.writeFileSync(path.join(root, "summary.md"), rows.join("\n"));
	return rows.join("\n");
}

export function summarise(suite, records) {
	const real = records.filter((record) => !record.aborted);
	return {
		suite: suite.name,
		identity: suite.identity,
		total: real.length,
		passed: real.filter((record) => record.pass).length,
		failed: real.filter((record) => !record.pass).length,
		failures: real
			.filter((record) => !record.pass)
			.map(({ n, label, reasons }) => ({ n, label, reasons })),
	};
}
