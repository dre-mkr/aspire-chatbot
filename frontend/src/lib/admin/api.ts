/**
 * The admin API client, and its own token storage.
 *
 * ## A separate realm means a separate everything
 *
 * Different storage key, different header, different login. The public chat's
 * session token is never read here and this token is never sent there --
 * `app/api/admin/auth.py` refuses each at the other's door, and this file makes
 * sure the two never even get the chance.
 *
 * The risk being closed is not a child guessing an admin password. It is that
 * one XSS on the chat surface, or one bearer token left on a shared school
 * tablet, would otherwise reach a queue of children's identity documents.
 *
 * ## `sessionStorage`, not `localStorage`
 *
 * A staff token dies with the tab. Reviewers work on shared desks, and a token
 * that survives closing the browser is a token the next person at that desk
 * inherits.
 */

const API_URL = (
	import.meta.env.VITE_ASPIRE_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

const TOKEN_KEY = "aspire.admin.token";

export type Role = "reviewer" | "supervisor" | "admin";

export type ApplicationStatus =
	| "submitted"
	| "under_review"
	| "info_requested"
	| "approved"
	| "rejected";

export interface QueueRow {
	id: string;
	status: ApplicationStatus;
	parish: string | null;
	children: number;
	created_at: string;
	flags: number;
}

export interface ApplicationDetail {
	id: string;
	status: ApplicationStatus;
	/** Decrypted, and every read of this endpoint writes an audit row. */
	fields: Record<string, string>;
	pending_corrections: Array<string>;
	consent_version: string | null;
	attested_at: string | null;
	created_at: string;
	submitted_at: string | null;
	documents: Array<{
		id: string;
		slot: string;
		mime: string;
		size_bytes: number;
		scan_status: string;
		check_confidence: number | null;
		check_notes: string | null;
		uploaded_at: string;
	}>;
	history: Array<{
		actor: string;
		from: string | null;
		to: string;
		reason: string;
		slots: Array<string>;
		at: string;
	}>;
}

export interface WidgetCandidate {
	id: string;
	concept_id: string;
	age_band: string;
	locale: string;
	kind: string;
	payload: Record<string, unknown>;
	source_question: string;
	generated_at: string;
	serve_count: number;
}

export interface SignIn {
	token: string;
	role: Role;
	email: string;
	/** Set for a seeded account. The portal refuses the queue until it clears. */
	must_change_password: boolean;
}

/**
 * Exchange an email and password for a staff token.
 *
 * Deliberately NOT routed through `call()`: that requires a token, and this is
 * the call that produces one. A sign-in that could reuse a stale token would
 * be a sign-in that never actually verified anything.
 */
export async function signIn(email: string, password: string): Promise<SignIn> {
	const response = await fetch(`${API_URL}/admin/auth/session`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ email, password }),
	});
	if (!response.ok) {
		const detail = await response
			.json()
			.then((body) => body.detail)
			.catch(() => null);
		throw new AdminError(
			detail ?? "Those details do not match.",
			response.status,
		);
	}
	return response.json() as Promise<SignIn>;
}

/** Rotate a password. Returns the replacement token; the old one is now dead. */
export function changePassword(
	current: string,
	next: string,
): Promise<{ token: string }> {
	return call("/auth/password", {
		method: "POST",
		body: JSON.stringify({ current, new: next }),
	});
}

export function token(): string | null {
	if (typeof sessionStorage === "undefined") return null;
	return sessionStorage.getItem(TOKEN_KEY);
}

export function setToken(value: string | null): void {
	if (typeof sessionStorage === "undefined") return;
	if (value) sessionStorage.setItem(TOKEN_KEY, value);
	else sessionStorage.removeItem(TOKEN_KEY);
}

export class AdminError extends Error {
	constructor(
		message: string,
		readonly status: number,
	) {
		super(message);
	}
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
	const bearer = token();
	if (!bearer) throw new AdminError("Sign in to continue.", 401);

	const response = await fetch(`${API_URL}/admin${path}`, {
		...init,
		headers: {
			"Content-Type": "application/json",
			// The admin token, and only ever the admin token.
			Authorization: `Bearer ${bearer}`,
			...(init.headers ?? {}),
		},
	});

	if (response.status === 401) {
		setToken(null);
		throw new AdminError("Your session has ended. Sign in again.", 401);
	}
	if (!response.ok) {
		const detail = await response
			.json()
			.then((body) => body.detail)
			.catch(() => null);
		throw new AdminError(
			detail ?? `Request failed (${response.status})`,
			response.status,
		);
	}
	return response.json() as Promise<T>;
}

export function queue(filters: {
	status?: string;
	parish?: string;
	since?: string;
	flagged?: boolean;
}): Promise<{ rows: Array<QueueRow> }> {
	const params = new URLSearchParams();
	if (filters.status) params.set("status", filters.status);
	if (filters.parish) params.set("parish", filters.parish);
	if (filters.since) params.set("since", filters.since);
	if (filters.flagged) params.set("flagged", "true");
	return call(`/applications?${params}`);
}

export function application(id: string): Promise<ApplicationDetail> {
	return call(`/applications/${id}`);
}

/**
 * A short-lived signed URL for a document.
 *
 * Fetched on demand, per document, per view -- never pre-fetched for a grid.
 * Every call writes its own audit row, so "who looked at this child's papers?"
 * is answerable; pre-fetching nine thumbnails would make that question
 * meaningless.
 */
export function documentUrl(
	id: string,
): Promise<{ url: string; expires_in: number }> {
	return call(`/documents/${id}/url`);
}

export function transition(
	id: string,
	body: { to: ApplicationStatus; reason: string; slots?: Array<string> },
): Promise<{ status: string; pending_corrections: Array<string> }> {
	return call(`/applications/${id}/transition`, {
		method: "POST",
		body: JSON.stringify(body),
	});
}

export function widgetQueue(): Promise<{ rows: Array<WidgetCandidate> }> {
	return call("/widgets");
}

export function reviewWidget(
	candidate: WidgetCandidate,
	body: {
		decision: "approved" | "rejected";
		payload?: Record<string, unknown>;
		note?: string;
	},
): Promise<{ status: string }> {
	return call(
		`/widgets/${encodeURIComponent(candidate.concept_id)}/${candidate.age_band}/${candidate.locale}`,
		{ method: "POST", body: JSON.stringify(body) },
	);
}
