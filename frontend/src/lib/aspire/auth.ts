/** Signing up, signing in, and getting back in. */

import { API_URL } from "../config";
import {
	authHeaders,
	clearSession,
	currentSession,
	resetToFreshAnonymous,
	type Session,
	storeSession,
} from "./session";

/** What happened to the anonymous session, so the page can say so. */
export interface ClaimOutcome {
	attempted: boolean;
	conversations: number;
	reason: string | null;
}

export interface AuthResult extends Session {
	claim: ClaimOutcome;
}

/** A failure worth showing next to a field. */
export class AuthError extends Error {
	readonly field: "email" | "password" | "form";
	readonly status: number;

	constructor(message: string, field: AuthError["field"] = "form", status = 0) {
		super(message);
		this.name = "AuthError";
		this.field = field;
		this.status = status;
	}
}

/** Which input a failure belongs under, from what the service said about it. */
function fieldFor(status: number, detail: string): AuthError["field"] {
	if (status === 409) return "email";
	if (status === 401) return "password";
	if (status === 422 && /password|characters|guess/i.test(detail))
		return "password";
	if (status === 422 && /email|address/i.test(detail)) return "email";
	return "form";
}

async function post<T>(path: string, body: unknown): Promise<T> {
	let response: Response;
	try {
		response = await fetch(`${API_URL}${path}`, {
			method: "POST",
			headers: { "Content-Type": "application/json", ...authHeaders() },
			body: JSON.stringify(body),
			signal: AbortSignal.timeout(20000),
		});
	} catch {
		// Offline, DNS, a dropped connection.
		throw new AuthError(
			"Could not reach ASPIRE. Check your connection and try again.",
		);
	}

	if (response.status === 204) return undefined as T;

	let detail = "";
	let payload: unknown;
	try {
		payload = await response.json();
		const asRecord = payload as { detail?: unknown };
		if (typeof asRecord.detail === "string") detail = asRecord.detail;
		else if (Array.isArray(asRecord.detail)) {
			// FastAPI's validation errors arrive as a list.
			const first = asRecord.detail[0] as { msg?: string } | undefined;
			detail = first?.msg ?? "";
		}
	} catch {
		payload = null;
	}

	if (!response.ok) {
		throw new AuthError(
			detail || "Something went wrong. Please try again.",
			fieldFor(response.status, detail),
			response.status,
		);
	}
	return payload as T;
}

interface WireSession {
	token: string;
	user_id: string;
	account_type: "anonymous" | "registered";
	email: string | null;
	display_name: string | null;
	avatar_url: string | null;
	role?: "participant" | "guardian" | "educator";
	persona?: string;
	claim?: { attempted: boolean; conversations: number; reason: string | null };
}

function adopt(wire: WireSession): AuthResult {
	const session: Session = {
		token: wire.token,
		userId: wire.user_id,
		accountType: wire.account_type,
		email: wire.email ?? null,
		displayName: wire.display_name ?? null,
		avatarUrl: wire.avatar_url ?? null,
		role: wire.role,
		// Left undefined rather than defaulted when the service does not send it.
		persona: wire.persona,
	};
	// Stored before returning, so every surface agrees before the page reacts.
	storeSession(session);
	return {
		...session,
		claim: wire.claim ?? { attempted: false, conversations: 0, reason: null },
	};
}

export interface SignUpFields {
	/** Who the account is for. */
	role: "participant" | "guardian" | "educator";
	email: string;
	password: string;
	firstName: string;
	lastName: string;
	/** The DOB of the person the account is for — a guardian's own, not their child's. */
	dateOfBirth: string;
	island?: string | null;
	school?: string | null;
	guardianName?: string | null;
	guardianEmail?: string | null;
	guardianPhone?: string | null;
}

export async function register(fields: SignUpFields): Promise<AuthResult> {
	return adopt(
		await post<WireSession>("/api/auth/register", {
			role: fields.role,
			email: fields.email,
			password: fields.password,
			first_name: fields.firstName,
			last_name: fields.lastName,
			date_of_birth: fields.dateOfBirth,
			island: fields.island || null,
			school: fields.school || null,
			guardian_name: fields.guardianName || null,
			guardian_email: fields.guardianEmail || null,
			guardian_phone: fields.guardianPhone || null,
		}),
	);
}

export async function signIn(
	email: string,
	password: string,
): Promise<AuthResult> {
	return adopt(await post<WireSession>("/api/auth/login", { email, password }));
}

/** Ask for a reset link. Answers the same whether or not the address is known. */
export async function requestReset(email: string): Promise<void> {
	await post<{ sent: boolean }>("/api/auth/forgot", { email });
}

/** Ask for a link that signs you in without a password. */
export async function requestSignInLink(email: string): Promise<void> {
	await post<{ sent: boolean }>("/api/auth/signin-link", { email });
}

export async function completeReset(
	token: string,
	password: string,
): Promise<AuthResult> {
	return adopt(await post<WireSession>("/api/auth/reset", { token, password }));
}

/**
 * Confirm an email address, from the link in the confirm-your-email message.
 *
 * `POST /api/auth/verify` has existed all along and had NO caller: `/verify`
 * was redeeming against `signin-link/redeem` instead, and `_redeem` matches on
 * the token's purpose as well as its hash. A verify token carries
 * `purpose="verify"`, so the lookup missed every time and the reader was told
 * "That link has been used" -- which was not true, and left them with no way
 * to confirm an address. This endpoint also sets `email_verified_at`, which
 * the sign-in path does not.
 */
export async function confirmEmail(token: string): Promise<AuthResult> {
	return adopt(await post<WireSession>("/api/auth/verify", { token }));
}

export async function redeemSignInLink(token: string): Promise<AuthResult> {
	return adopt(
		await post<WireSession>("/api/auth/signin-link/redeem", { token }),
	);
}

/** How close to expiry is close enough to renew. */
const RENEW_WITHIN_MS = 3 * 24 * 60 * 60 * 1000;

let renewing: Promise<void> | null = null;

/** Quietly take a fresh token when the current one is getting old. */
export function renewSessionIfStale(): void {
	const session = currentSession();
	if (!session || renewing) return;
	// Unknown expiry means a session stored before expiry was recorded.
	if (!session.expiresAt || session.expiresAt - Date.now() > RENEW_WITHIN_MS)
		return;

	renewing = post<WireSession>("/api/auth/refresh", {})
		.then((wire) => {
			adopt(wire);
		})
		.catch(() => undefined)
		.finally(() => {
			renewing = null;
		});
}

/** Sign out, and come back as somebody new. */
export async function signOut(afterCleared?: () => void): Promise<void> {
	try {
		// While the token is still in hand, so the service can retire it.
		await post<void>("/api/auth/logout", {});
	} catch {
		// The local session is cleared either way.
	}

	clearSession();

	// Dropped in the gap where this browser has no identity; the ordering is the point.
	afterCleared?.();

	await resetToFreshAnonymous();
}
