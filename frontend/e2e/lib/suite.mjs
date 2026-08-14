/**
 * Running a scripted conversation and judging it.
 *
 * A step is `{ say }` (type a message), `{ act }` (click something that starts a
 * turn), or `{ custom }` (anything else). Its `expect` is checked against three
 * independent sources: the wire (what the server sent), the DOM (what the reader
 * saw), and the backend log slice for exactly that turn (why it did that).
 */

import { act, directiveKinds, readSurfaces, say, settle, snapshot } from "./turn.mjs";
import { readRoute, readSticky, SIGNALS } from "./server.mjs";

const list = (value) => (value == null ? [] : Array.isArray(value) ? value : [value]);

function judge(step, record) {
	const want = step.expect || {};
	const reasons = [];
	const { wire, ui, backend } = record;

	// Against a deployed origin there is no log to slice, so the third source is
	// absent rather than silent. Those assertions are recorded as skipped on the
	// record instead of counting as failures -- see lib/remote.mjs.
	const readsLog = !backend?.remote;
	const skipped = [];

	if (wire?.error) reasons.push(`wire error: ${JSON.stringify(wire.error)}`);

	if (want.agent !== undefined) {
		const allowed = list(want.agent);
		const got = wire?.usage?.agent ?? null;
		if (!allowed.includes(got)) {
			reasons.push(`agent was ${got}, wanted ${allowed.join(" or ")}`);
		}
		if (got === "cache") {
			reasons.push("answered from cache — the graph never ran, so routing is unproven");
		}
	}

	// The wire and the log must agree; a disagreement means one of them is lying.
	if (!readsLog) {
		skipped.push("wire/log agreement (no log)");
	} else if (wire?.usage?.agent && backend.turnAgent && wire.usage.agent !== backend.turnAgent) {
		reasons.push(`wire says ${wire.usage.agent}, log says ${backend.turnAgent}`);
	}

	const text = ui?.lastAnswer || "";
	for (const pattern of list(want.mustMatch)) {
		if (!pattern.test(text)) reasons.push(`answer did not match ${pattern}`);
	}
	for (const pattern of list(want.mustNotMatch)) {
		if (pattern.test(text)) reasons.push(`answer matched forbidden ${pattern}`);
	}
	if (want.nonEmpty !== false && !text.trim() && !want.allowEmpty) {
		if (want.allowEmpty !== true) reasons.push("empty answer");
	}

	const kinds = directiveKinds(wire);
	for (const kind of list(want.directive)) {
		if (!kinds.includes(kind)) {
			reasons.push(`no ${kind} directive (saw ${kinds.join(",") || "none"})`);
		}
	}
	for (const kind of list(want.noDirective)) {
		if (kinds.includes(kind)) reasons.push(`unexpected ${kind} directive`);
	}

	if (want.chips !== undefined && (ui?.chips?.length ?? 0) < want.chips) {
		reasons.push(`${ui?.chips?.length ?? 0} chips, wanted at least ${want.chips}`);
	}
	if (want.surface) {
		for (const key of list(want.surface)) {
			if (!ui?.[key]) reasons.push(`${key} did not render`);
		}
	}

	if (!readsLog) {
		for (const key of ["log", "noLog", "route", "noRoute"]) {
			if (want[key] !== undefined) skipped.push(`${key} (no log)`);
		}
	} else {
		for (const pattern of list(want.log)) {
			if (!backend.lines.some((line) => pattern.test(line))) {
				reasons.push(`no log line matching ${pattern}`);
			}
		}
		for (const pattern of list(want.noLog)) {
			if (backend.lines.some((line) => pattern.test(line))) {
				reasons.push(`log line matched forbidden ${pattern}`);
			}
		}

		if (want.noRoute && backend.route) {
			reasons.push(`the router was consulted (${backend.route.agent}) but should not have been`);
		}
		if (want.route && !backend.route) {
			reasons.push("the router was never consulted");
		}
	}
	if (want.citations && !ui?.sources) reasons.push("no citations panel");

	record.skipped = skipped;
	return reasons;
}

async function observe(page, backendServer, cursor, wire) {
	await backendServer.settleLog();
	const lines = backendServer.since(cursor);
	const turnLine = lines.find((line) => SIGNALS.turn.test(line));
	return {
		wire,
		ui: await readSurfaces(page),
		backend: {
			lines,
			remote: backendServer.remote === true,
			route: readRoute(lines),
			sticky: readSticky(lines),
			turnAgent: turnLine ? turnLine.match(SIGNALS.turn)[2] : null,
		},
	};
}

export async function runSteps(ctx, steps) {
	const { page, backend } = ctx;
	const records = [];

	for (const [index, step] of steps.entries()) {
		const number = index + 1;
		const cursor = backend.cursor();
		const started = Date.now();
		let wire = null;
		let failure = null;

		try {
			if (step.say) {
				wire = await say(page, step.say);
			} else if (step.act) {
				wire = await act(page, step.act);
			} else if (step.custom) {
				const before = await snapshot(page);
				const result = await step.custom(ctx);
				wire = result === undefined ? await settle(page, before) : result;
			} else if (step.domOnly) {
				await step.domOnly(ctx);
			}
		} catch (error) {
			failure = String(error.message || error);
		}

		const observed = failure && !wire
			? { wire: null, ui: await readSurfaces(page).catch(() => null), backend: { lines: backend.since(cursor), remote: backend.remote === true, route: null, sticky: null, turnAgent: null } }
			: await observe(page, backend, cursor, wire);

		const record = {
			n: number,
			label: step.label || step.say || (step.act ? "(click)" : "(custom)"),
			sent: step.say || null,
			request: wire?.request ?? null,
			ms: Date.now() - started,
			...observed,
			expect: describe(step.expect),
			note: step.note || null,
			failure,
		};

		record.reasons = failure ? [failure] : judge(step, record);
		record.pass = record.reasons.length === 0;
		records.push(record);

		if (ctx.onStep) ctx.onStep(record);

		// A step marked `critical` makes everything after it uninterpretable.
		if (!record.pass && step.critical) {
			records.push({
				n: number + 1,
				label: "(aborted)",
				pass: false,
				reasons: [`aborted: step ${number} is critical and failed`],
				aborted: true,
			});
			break;
		}
	}

	return records;
}

function describe(expect) {
	if (!expect) return null;
	const out = {};
	for (const [key, value] of Object.entries(expect)) {
		out[key] = Array.isArray(value) ? value.map(String) : String(value);
	}
	return out;
}
