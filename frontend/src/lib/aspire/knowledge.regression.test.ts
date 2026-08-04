/**
 * P1 regression tests — written BEFORE any fix exists.
 *
 * Every test in this file is expected to FAIL against the current code. Each one
 * states the behaviour the renderer should have; the assertion message names the
 * ledger id and what actually happens today.
 *
 * Marked `{ todo: true }` so a red suite does not block CI while these findings
 * are open — they document defects, they are not new breakage. node:test reports
 * a passing todo as "todo pass", which is the signal to drop the flag along with
 * the fix. Remove `{ todo: true }` in the same commit that fixes the finding.
 *
 * Run with:  node --test src/lib/aspire/*.test.ts
 *
 * No test framework was added. Node 26 runs TypeScript directly and ships
 * `node:test`, so these cost nothing in the dependency tree.
 *
 * These are pure-function tests over the LIVE render path. `parseAnswer` is
 * called on every settled reply (`use-conversation.ts:717`) and `parseInline`
 * on every rendered run, so a defect here is on screen for every user.
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { type InlineNode, parseAnswer, parseInline } from "./knowledge.ts";

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

test("P1-004: two identical bracketed runs render identically", { todo: true }, () => {
	const nodes = parseInline("Choose [A] or [B]");
	assert.equal(
		rendered(nodes),
		"Choose [A] or [B]",
		"PARTIAL_LINK is anchored to $, so only the LAST bracketed run is treated " +
			"as a half-typed link and stripped. Today this renders 'Choose [A] or B' " +
			"— the same construct drawn two different ways in one sentence.",
	);
});

test("P1-004: a citation marker keeps its brackets", { todo: true }, () => {
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

test("P1-005: an ordered list is distinguishable from an unordered one", { todo: true }, () => {
	const ordered = parseAnswer("Steps:\n1. Get a form\n2. Sign it\n3. Return it");
	const list = ordered.find((block) => block.kind === "list");
	assert.ok(list && list.kind === "list");

	assert.ok(
		"ordered" in list,
		"AnswerBlock has no way to say a list was numbered: BULLET strips '1. ' " +
			"in parseAnswer and Transcript.tsx:388 always renders <ul>. So the " +
			"application steps behind the 'How do I apply for ASPIRE?' starter " +
			"prompt lose their numbers. The block type needs an `ordered` flag.",
	);
});

// ── P1-006 — duplicate list items collide as React keys ────────────────────

test("P1-006: repeated list items are safe to render", { todo: true }, () => {
	const blocks = parseAnswer("- Yes\n- No\n- Yes");
	const list = blocks[0];
	assert.ok(list?.kind === "list");

	const unique = new Set(list.items);
	assert.equal(
		unique.size,
		list.items.length,
		"Transcript.tsx:390 uses `key={item}`. Repeated item text — common in a " +
			"true/false or yes/no answer — produces duplicate React keys, and the " +
			"array GROWS during the typewriter reveal, which is exactly when " +
			"mis-keyed reconciliation shows. Key by index or id instead.",
	);
});

// ── P1-007 — an unterminated ** bolds the rest of the answer forever ────────

test("P1-007: a stray ** does not bold the remainder of a settled answer", { todo: true }, () => {
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
