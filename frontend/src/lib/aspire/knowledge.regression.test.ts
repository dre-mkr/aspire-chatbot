/** P1 regression tests — written BEFORE any fix existed. */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
	answerToText,
	type InlineNode,
	parseAnswer,
	parseInline,
} from "./knowledge.ts";

/** Flatten inline nodes back to the text a reader would actually see. */
function rendered(nodes: Array<InlineNode>): string {
	return nodes
		.map((node) =>
			node.kind === "text"
				? node.text
				: node.kind === "bold"
					? rendered(node.children)
					: node.text,
		)
		.join("");
}

// ── P1-004 — bracketed runs render inconsistently ───────────────────────────

test("P1-004: two identical bracketed runs render identically", () => {
	const nodes = parseInline("Choose [A] or [B]");
	assert.equal(
		rendered(nodes),
		"Choose [A] or [B]",
		"PARTIAL_LINK is anchored to $, so only the LAST bracketed run is treated " +
			"as a half-typed link and stripped. Today this renders 'Choose [A] or B' " +
			"— the same construct drawn two different ways in one sentence.",
	);
});

test("P1-004: a citation marker keeps its brackets", () => {
	const nodes = parseInline("See note [1]");
	assert.equal(
		rendered(nodes),
		"See note [1]",
		"Today renders 'See note 1'. PARTIAL_LINK exists to hide half-typed " +
			"markdown links during the reveal, but it also fires on settled text " +
			"where the brackets are the author's, not a link in progress.",
	);
});

test("P1-004: bracketed text mid-sentence is untouched", () => {
	// Control: proves the defect is positional, not about brackets in general.
	const nodes = parseInline("Fill in [your name] on the form");
	assert.equal(rendered(nodes), "Fill in [your name] on the form");
});

// ── P1-005 — ordered lists lose their numbering ─────────────────────────────

test("P1-005: an ordered list is distinguishable from an unordered one", () => {
	const ordered = parseAnswer(
		"Steps:\n1. Get a form\n2. Sign it\n3. Return it",
	);
	const list = ordered.find((block) => block.kind === "list");
	assert.ok(list && list.kind === "list");

	assert.equal(
		list.ordered,
		true,
		"AnswerBlock had no way to say a list was numbered: BULLET strips '1. ' " +
			"in parseAnswer and Transcript always rendered <ul>. So the application " +
			"steps behind the 'How do I apply for ASPIRE?' starter prompt lost their " +
			"numbers. The block type carries an `ordered` flag now.",
	);
});

test("P1-005: a dashed list is still unordered", () => {
	const blocks = parseAnswer("- Bring ID\n- Bring a form");
	const list = blocks[0];
	assert.ok(list?.kind === "list");
	assert.equal(list.ordered, false);
});

test("P1-005: numbering survives the flatten used for clipboard and speech", () => {
	const blocks = parseAnswer("1. Get a form\n2. Sign it");
	assert.equal(answerToText(blocks), "1. Get a form\n2. Sign it");
});

// ── P1-006 — duplicate list items collide as React keys ────────────────────

// The original form of this test asserted `parseAnswer` returns unique items.
test("P1-006: duplicate item text is legitimate parser output", () => {
	const blocks = parseAnswer("- Yes\n- No\n- Yes");
	const list = blocks[0];
	assert.ok(list?.kind === "list");

	assert.deepEqual(
		list.items,
		["Yes", "No", "Yes"],
		"Repeated item text is common in a true/false or yes/no answer, so the " +
			"renderer must not key by content. It keys by index.",
	);
	assert.ok(
		new Set(list.items).size < list.items.length,
		"if this ever stops holding, the duplicate-key hazard is gone and the " +
			"positional key in Transcript.tsx can be revisited",
	);
});

// ── P1-007 — an unterminated ** bolds the rest of the answer forever ────────

test("P1-007: a stray ** does not bold the remainder of a settled answer", () => {
	const nodes = parseInline("Save 10% ** of your income");
	const hasBold = nodes.some((node) => node.kind === "bold");
	assert.equal(
		hasBold,
		false,
		"parseInline treats an unterminated ** as an open bold run. That is right " +
			"mid-reveal and wrong once the text has settled: an odd number of " +
			"asterisks in the final answer leaves the tail bold permanently.",
	);
});

// ── The reveal still gets its optimism ────────────────────────────────────── P1-004 and P1-007 are both fixed…

test("revealing: a half-typed link still renders as its label", () => {
	assert.equal(
		rendered(parseInline("Visit [the site](htt", true)),
		"Visit the site",
	);
	assert.equal(rendered(parseInline("Visit [the sit", true)), "Visit the sit");
});

test("revealing: an unterminated ** is still bold mid-reveal", () => {
	const nodes = parseInline("Save **10", true);
	assert.ok(nodes.some((node) => node.kind === "bold"));
});

test("settled: a complete markdown link is still a link either way", () => {
	for (const revealing of [false, true]) {
		const nodes = parseInline(
			"See [ASPIRE](https://aspire.gov.kn/)",
			revealing,
		);
		const link = nodes.find((node) => node.kind === "link");
		assert.ok(
			link?.kind === "link",
			`lost the link with revealing=${revealing}`,
		);
		assert.equal(link.href, "https://aspire.gov.kn/");
	}
});

// ── P9-006 — the autolinker invents links out of prose ──────────────────────

test("P9-006: code-shaped prose does not become a link", () => {
	for (const text of [
		"document.cookie",
		"index.js",
		"config.io",
		"the object.com property",
	]) {
		const nodes = parseInline(text);
		assert.equal(
			nodes.some((node) => node.kind === "link"),
			false,
			`"${text}" autolinked. A dotted token is not evidence of a destination; ` +
				`<script>alert(document.cookie)</script> produced a link to ` +
				`https://document.co because .co matched and "okie" was abandoned.`,
		);
	}
});

test("P9-006: the corpus's real destinations still link", () => {
	const cases: Array<[string, string]> = [
		["aspire.gov.kn", "https://aspire.gov.kn"],
		["www.gov.kn", "https://www.gov.kn"],
		["facebook.com/aspireskn", "https://facebook.com/aspireskn"],
		["https://sknis.gov.kn/news", "https://sknis.gov.kn/news"],
		["info@aspire.gov.kn", "mailto:info@aspire.gov.kn"],
	];
	for (const [text, href] of cases) {
		const nodes = parseInline(text);
		const link = nodes.find((node) => node.kind === "link");
		assert.ok(link?.kind === "link", `"${text}" stopped linking`);
		assert.equal(link.href, href);
	}
});

test("P9-006: a sentence-ending period stays out of the target", () => {
	const nodes = parseInline("Apply at aspire.gov.kn.");
	const link = nodes.find((node) => node.kind === "link");
	assert.ok(link?.kind === "link");
	assert.equal(link.href, "https://aspire.gov.kn");
	assert.equal(rendered(nodes), "Apply at aspire.gov.kn.");
});
