/** The eligibility half of the ASPIRE backend client. */

const API_URL = (
	import.meta.env.VITE_ASPIRE_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

/** Every action is a tap away from the next; a slow one reads as broken. */
const TIMEOUT_MS = 10_000;

/** The three outcomes. */
export type Verdict = "likely_eligible" | "not_yet" | "needs_confirmation";

/** What a verdict turned on. `none` is a clean pass, not a null. */
export type Criterion =
	| "none"
	| "citizenship"
	| "age_minimum"
	| "age_cohort"
	| "residence"
	| "school";

export interface EligibilityOption {
	/** The token sent back. Never rendered. */
	value: string;
	label: string;
}

export interface EligibilityQuestion {
	id: string;
	text: string;
	help: string | null;
	options: Array<EligibilityOption>;
	position: number;
	total: number;
	/** The option already chosen here, when the reader has been back. */
	answered_with: string | null;
	can_go_back: boolean;
}

export interface ChecklistItem {
	id: string;
	title: string;
	detail: string;
	/** Where to get help with this document. */
	where: string;
	signed_by: string | null;
	/** The source's own hedge, where the source hedges. Never dropped to fit. */
	caveat: string | null;
	/** An alternative to the item above it, not another thing to bring. */
	alternative: boolean;
}

export interface ApplicationStep {
	number: number;
	title: string;
	detail: string;
	link: string | null;
	link_label: string | null;
}

export interface EligibilityResult {
	verdict: Verdict;
	criterion: Criterion;
	headline: string;
	body: Array<string>;
	/** The pre-check disclaimer. Rendered visibly, never as fine print. */
	disclaimer: string;
	unresolved: Array<string>;
	/** Written so it can be read out or pasted into an email unchanged. */
	mentor_question: string | null;
	checklist: Array<ChecklistItem>;
	steps: Array<ApplicationStep>;
	notices: Array<string>;
	contacts: Array<string>;
	/** Only on the under-5 branch: the year they can register. */
	reminder_year: number | null;
}

/** The card's own chrome, served so the copy has one home. */
export interface EligibilityLabels {
	title: string;
	subtitle: string;
	progress: string;
	back: string;
	leave: string;
	close: string;
	restart: string;
	checklist_heading: string;
	steps_heading: string;
	checked_note: string;
	where_label: string;
	signed_label: string;
	contact_heading: string;
	banner: string;
}

/** The card's whole world: a question, or a result, never both. */
export interface EligibilityState {
	active: boolean;
	language: string;
	question: EligibilityQuestion | null;
	result: EligibilityResult | null;
	answered: number;
	total: number;
	labels: EligibilityLabels;
}

export class EligibilityError extends Error {
	readonly reason: string;
	readonly status: number;

	constructor(reason: string, message: string, status: number) {
		super(message);
		this.name = "EligibilityError";
		this.reason = reason;
		this.status = status;
	}
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
	let response: Response;
	try {
		response = await fetch(`${API_URL}${path}`, {
			...init,
			headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
			signal: AbortSignal.timeout(TIMEOUT_MS),
		});
	} catch {
		throw new EligibilityError(
			"offline",
			"The eligibility check could not be reached.",
			0,
		);
	}

	if (!response.ok) {
		let reason = "eligibility_error";
		let message = "Something went wrong with the check.";
		try {
			const body = (await response.json()) as {
				detail?: { reason?: string; message?: string } | string;
			};
			if (body.detail && typeof body.detail === "object") {
				reason = body.detail.reason ?? reason;
				message = body.detail.message ?? message;
			}
		} catch {
			// Not JSON. The generic message stands.
		}
		throw new EligibilityError(reason, message, response.status);
	}

	return (await response.json()) as T;
}

/** The flow in progress, or an inactive envelope. */
export function fetchEligibilityState(threadId: string, language = "en") {
	return call<EligibilityState>(
		`/api/eligibility/state?thread_id=${encodeURIComponent(threadId)}&language=${encodeURIComponent(language)}`,
	);
}

export function startEligibility(threadId: string, language = "en") {
	return call<EligibilityState>("/api/eligibility/start", {
		method: "POST",
		body: JSON.stringify({ thread_id: threadId, language }),
	});
}

export function answerEligibility(threadId: string, value: string) {
	return call<EligibilityState>("/api/eligibility/answer", {
		method: "POST",
		body: JSON.stringify({ thread_id: threadId, value }),
	});
}

export function goBack(threadId: string) {
	return call<EligibilityState>("/api/eligibility/back", {
		method: "POST",
		body: JSON.stringify({ thread_id: threadId }),
	});
}

export function restartEligibility(threadId: string, language?: string) {
	return call<EligibilityState>("/api/eligibility/restart", {
		method: "POST",
		body: JSON.stringify({ thread_id: threadId, language: language ?? null }),
	});
}

export function quitEligibility(threadId: string) {
	return call<EligibilityState>("/api/eligibility/quit", {
		method: "POST",
		body: JSON.stringify({ thread_id: threadId }),
	});
}

/** The finished result, kept on this device. */
const RESULT_KEY = "aspire.eligibility.results.v1";
const CHECKED_KEY = "aspire.eligibility.checked.v1";

function canStore() {
	// Imported during SSR, where there is no window at all.
	return typeof window !== "undefined" && !!window.localStorage;
}

function readMap<T>(key: string): Record<string, T> {
	if (!canStore()) return {};
	try {
		const raw = window.localStorage.getItem(key);
		if (!raw) return {};
		const parsed: unknown = JSON.parse(raw);
		if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
			return {};
		return parsed as Record<string, T>;
	} catch {
		return {};
	}
}

function writeMap<T>(key: string, value: Record<string, T>) {
	if (!canStore()) return;
	try {
		window.localStorage.setItem(key, JSON.stringify(value));
	} catch {
		// Private browsing and full quotas both throw.
	}
}

/** What a finished check leaves behind, so the card can redraw it. */
export interface StoredEligibility {
	result: EligibilityResult;
	labels: EligibilityLabels;
	language: string;
}

export function saveEligibilityResult(
	threadId: string,
	stored: StoredEligibility,
) {
	writeMap(RESULT_KEY, {
		...readMap<StoredEligibility>(RESULT_KEY),
		[threadId]: stored,
	});
}

export function loadEligibilityResult(
	threadId: string,
): StoredEligibility | null {
	const stored = readMap<StoredEligibility>(RESULT_KEY)[threadId];
	// Storage is shared with older builds and with hand-editing, so nothing out of it is trusted structurally.
	if (!stored?.result?.verdict || !Array.isArray(stored.result.body))
		return null;
	return stored;
}

export function clearEligibilityResult(threadId: string) {
	const all = readMap<StoredEligibility>(RESULT_KEY);
	delete all[threadId];
	writeMap(RESULT_KEY, all);
	const checked = readMap<Array<string>>(CHECKED_KEY);
	delete checked[threadId];
	writeMap(CHECKED_KEY, checked);
}

/** Which checklist items have been ticked, per conversation. */
export function loadCheckedItems(threadId: string): Array<string> {
	const stored = readMap<Array<string>>(CHECKED_KEY)[threadId];
	return Array.isArray(stored) ? stored : [];
}

export function saveCheckedItems(threadId: string, items: Array<string>) {
	writeMap(CHECKED_KEY, {
		...readMap<Array<string>>(CHECKED_KEY),
		[threadId]: items,
	});
}
