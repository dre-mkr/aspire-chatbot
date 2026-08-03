/**
 * Signing up, signing in, and getting back in.
 *
 * Every call that establishes an account sends the current anonymous token
 * alongside the credentials, which is what makes the claim run: the questions
 * somebody asked before signing up follow them into the account. The service
 * does the reassignment transactionally; this only has to remember to offer the
 * token, and to store whatever comes back.
 */

import {
	type Session,
	authHeaders,
	clearSession,
	resetToFreshAnonymous,
	storeSession,
} from "./session";

const API_URL = (
	import.meta.env.VITE_ASPIRE_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

/** What happened to the anonymous session, so the page can say so. */
export interface ClaimOutcome {
	attempted: boolean;
	conversations: number;
	reason: string | null;
}

export interface AuthResult extends Session {
	claim: ClaimOutcome;
}

/**
 * A failure worth showing next to a field.
 *
 * `field` is what the page uses to put the message under the input it belongs
 * to rather than in a banner at the top — a message about the password should
 * be beside the password.
 */
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
	if (status === 422 && /password|characters|guess/i.test(detail)) return "password";
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
		// Offline, DNS, a dropped connection. Named as itself rather than as a
		// credentials problem, because telling somebody their password is wrong
		// when their wifi is off sends them to reset a password that is fine.
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
	};
	// Stored before returning, so every surface is already agreed about who is
	// signed in by the time the page reacts.
	storeSession(session);
	return {
		...session,
		claim: wire.claim ?? { attempted: false, conversations: 0, reason: null },
	};
}

export interface SignUpFields {
	email: string;
	password: string;
	firstName: string;
	lastName: string;
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

export async function signIn(email: string, password: string): Promise<AuthResult> {
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

export async function completeReset(token: string, password: string): Promise<AuthResult> {
	return adopt(await post<WireSession>("/api/auth/reset", { token, password }));
}

export async function redeemSignInLink(token: string): Promise<AuthResult> {
	return adopt(await post<WireSession>("/api/auth/signin-link/redeem", { token }));
}

/**
 * Sign out, and come back as somebody new.
 *
 * The service retires the token; the client then takes a brand-new anonymous
 * identity rather than resurrecting the one from before signing in. On a shared
 * device, signing out should not leave a thread back to who was there.
 */
export async function signOut(afterCleared?: () => void): Promise<void> {
	try {
		// While the token is still in hand, so the service can retire it.
		await post<void>("/api/auth/logout", {});
	} catch {
		// The local session is cleared either way. A token the server has not
		// heard about is still useless once this browser has forgotten it.
	}

	clearSession();

	// Dropped here, in the gap where this browser has no identity at all, and
	// the ordering is the whole point. Removing a mounted query makes it
	// refetch immediately: doing that before the token was cleared re-fetched
	// the person who had just signed out, and put their conversation titles
	// straight back into the rail.
	afterCleared?.();

	await resetToFreshAnonymous();
}
