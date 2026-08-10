/** The directive-aware parser, and the regression that guards the flash fix. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { OrdinalBuffer, parseFrame, splitFrames } from "./client.ts";
import { assertNoFlash, proseCount, timeline } from "./parser.ts";
import type { Directive } from "./types.ts";

const CHIPS: Directive = {
	t: "quick_replies",
	options: [{ label: "Yes", value: "Yes" }],
};

const ANSWER =
	"ASPIRE is open to children aged 5 to 18. A parent or guardian opens the account.\n" +
	"You will need:\n" +
	"- the birth certificate\n" +
	"- a photo ID\n" +
	"Bring both to any branch.";

/** The offset of the list, which is where a mid-answer directive lands. */
const MID = ANSWER.indexOf("- the birth");

test("prose, then a directive, then prose", () => {
	const entries = timeline(ANSWER, true, [
		{ directive: CHIPS, ordinal: 5, afterChars: MID },
	]);

	const kinds = entries.map((entry) => entry.kind);
	assert.ok(kinds.includes("directive"));
	assert.ok(kinds.indexOf("prose") < kinds.indexOf("directive"));
	assert.ok(kinds.lastIndexOf("prose") > kinds.indexOf("directive"));
});

test("a directive with no prose yet still renders", () => {
	const entries = timeline("", true, [
		{ directive: CHIPS, ordinal: 1, afterChars: 0 },
	]);
	assert.equal(entries.length, 1);
	assert.equal(entries[0].kind, "directive");
});

test("no directives means the timeline is exactly the prose blocks", () => {
	const entries = timeline(ANSWER, true, []);
	assert.equal(proseCount(entries), entries.length);
});

test("an unknown directive type travels through the parser untouched", () => {
	// The parser does not know or care what a directive is; the registry decides whether to render it.
	const future = { t: "hologram", spin: 3 } as unknown as Directive;
	const entries = timeline("hello", true, [
		{ directive: future, ordinal: 2, afterChars: 5 },
	]);
	assert.ok(entries.some((entry) => entry.kind === "directive"));
});

test("REGRESSION: adding a directive does not reintroduce the completion flash", () => {
	// The flash was: the revealed prefix is REPLACED by the finished answer in one frame, so everything lands at on…
	const problem = assertNoFlash(ANSWER, [
		{ directive: CHIPS, ordinal: 5, afterChars: MID },
	]);
	assert.equal(problem, null, problem ?? "");
});

test("REGRESSION: no flash with a directive at the very start", () => {
	const problem = assertNoFlash(ANSWER, [
		{ directive: CHIPS, ordinal: 1, afterChars: 0 },
	]);
	assert.equal(problem, null, problem ?? "");
});

test("REGRESSION: no flash with several directives interleaved", () => {
	const problem = assertNoFlash(ANSWER, [
		{ directive: CHIPS, ordinal: 3, afterChars: 20 },
		{ directive: CHIPS, ordinal: 9, afterChars: MID },
		{ directive: CHIPS, ordinal: 20, afterChars: ANSWER.length },
	]);
	assert.equal(problem, null, problem ?? "");
});

/* ── the client's framing ───────────────────────────────────────────────── */

test("frames split on the blank line and keep the remainder", () => {
	const { frames, rest } = splitFrames(
		'event: token\ndata: {"i":1,"t":"a"}\n\nevent: token\ndata: {"i":2,',
	);
	assert.equal(frames.length, 1);
	assert.ok(rest.startsWith("event: token"));
});

test("a frame split across two chunks is not dropped", () => {
	// The bug this prevents: a chunk boundary inside a frame, which happens constantly, silently losing roughly one…
	const first = splitFrames('event: token\ndata: {"i":1,');
	const second = splitFrames(`${first.rest}"t":"hello"}\n\n`);
	assert.equal(first.frames.length, 0);
	assert.equal(second.frames.length, 1);
	assert.deepEqual(parseFrame(second.frames[0]), {
		event: "token",
		data: { i: 1, t: "hello" },
	});
});

test("a malformed frame is skipped rather than ending the turn", () => {
	assert.equal(parseFrame("event: token\ndata: {not json"), null);
	assert.equal(parseFrame(": keep-alive"), null);
	assert.equal(parseFrame(""), null);
});

test("the buffer orders by ordinal, not by arrival", () => {
	const buffer = new OrdinalBuffer();
	buffer.token(3, "world");
	buffer.token(1, "hello ");
	assert.equal(buffer.text(), "hello world");
});

test("a directive's character offset counts only the prose before it", () => {
	const buffer = new OrdinalBuffer();
	buffer.token(1, "hello ");
	buffer.directive(2, CHIPS);
	buffer.token(3, "world");
	const placed = buffer.placed();
	assert.equal(placed.length, 1);
	assert.equal(placed[0].afterChars, 6);
});

test("gaps in the ordinal sequence are tolerated", () => {
	// An error event consumes no ordinal, so a gap is a legitimate state and must not truncate the text at the hole.
	const buffer = new OrdinalBuffer();
	buffer.token(1, "a");
	buffer.token(4, "b");
	assert.equal(buffer.text(), "ab");
});
