/**
 * The six identities the suites run as.
 *
 * Date of birth is the whole game: it sets the age band, the band picks the persona,
 * and (persona, band) decides which agents are reachable at all
 * (backend/app/graph/access.py). Every DOB below sits well clear of a band boundary
 * so the client's arithmetic and the server's `band_for` cannot disagree.
 *
 * F (educator/nova) is the control: exactly one routable agent, so `classify`
 * short-circuits with no model call. If F fails, the fault is the harness.
 */

export const PASSWORD = "aspire-e2e-2026-pass";

export const IDENTITIES = {
	A: {
		key: "A",
		label: "anonymous",
		anonymous: true,
		expect: { persona: "aurora", age_band: "adult" },
		routable: ["qa_agent_public", "learning_sample", "register_agent_step1"],
	},
	B: {
		key: "B",
		label: "stella 9-12",
		role: "participant",
		first: "Bea",
		last: "Tester",
		dob: "2017-01-15",
		island: "St. Kitts",
		guardianName: "Bea Guardian",
		guardianEmail: "aspire-e2e-guardian-b@example.test",
		expect: { persona: "stella", age_band: "9-12" },
		routable: ["qa_agent_limited", "learn_agent"],
	},
	C: {
		key: "C",
		label: "orion 13-15",
		role: "participant",
		first: "Cai",
		last: "Tester",
		dob: "2012-01-15",
		island: "Nevis",
		expect: { persona: "orion", age_band: "13-15" },
		routable: ["qa_agent_limited", "learn_agent"],
	},
	D: {
		key: "D",
		label: "orion 16-18",
		role: "participant",
		first: "Dee",
		last: "Tester",
		dob: "2009-01-15",
		island: "St. Kitts",
		expect: { persona: "orion", age_band: "16-18" },
		routable: ["qa_agent", "learn_agent"],
	},
	E: {
		key: "E",
		label: "aurora guardian",
		role: "guardian",
		first: "Eve",
		last: "Tester",
		dob: "1988-06-10",
		island: "St. Kitts",
		expect: { persona: "aurora", age_band: "adult" },
		routable: ["qa_agent", "register_agent", "learning_preview"],
	},
	F: {
		key: "F",
		label: "nova educator (control)",
		role: "educator",
		first: "Fen",
		last: "Tester",
		dob: "1988-06-10",
		island: "Nevis",
		expect: { persona: "nova", age_band: "adult" },
		routable: ["qa_agent"],
	},
};

/** Unique per run, so a re-run never collides with an existing account. */
export function withCredentials(identity, runId) {
	if (identity.anonymous) return identity;
	return {
		...identity,
		email: `aspire-e2e+${runId}-${identity.key.toLowerCase()}@example.test`,
		password: PASSWORD,
	};
}
