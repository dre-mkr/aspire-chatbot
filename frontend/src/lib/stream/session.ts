/** The graph session token, and where it comes from. */
import { authHeaders } from "../aspire/session";

const API_URL = (
	import.meta.env.VITE_ASPIRE_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

export interface GraphSession {
	token: string;
	sessionId: string;
	persona: string;
	ageBand: string;
	accountStatus: string;
	locale: string;
	/** True when `persona` is not the one that was asked for. See `onPersonaRefused`. */
	personaRefused: boolean;
}

/** In-memory, per tab, per thread. Cleared by a reload, which is correct. */
const held = new Map<string, GraphSession>();
/** In-flight mints, so twelve chips tapped quickly mint one token, not twelve. */
const minting = new Map<string, Promise<GraphSession>>();

export function forget(threadId: string): void {
	held.delete(threadId);
	minting.delete(threadId);
}

export function forgetAll(): void {
	held.clear();
	minting.clear();
}

export interface PersonaRefusal {
	/** What the client asked for. */
	requested: string;
	/** What it got instead, and what every turn will actually run as. */
	granted: string;
}

/** Told when the server declines a persona request. */
let refusedListener: ((refusal: PersonaRefusal) => void) | null = null;

export function onPersonaRefused(
	listener: (refusal: PersonaRefusal) => void,
): () => void {
	refusedListener = listener;
	return () => {
		if (refusedListener === listener) refusedListener = null;
	};
}

/** The token for this thread, minting one if there is not one already. */
export async function graphSession(
	threadId: string,
	options: { locale?: string; persona?: string | null; deviceId?: string } = {},
): Promise<GraphSession> {
	const existing = held.get(threadId);
	if (existing) return existing;

	const pending = minting.get(threadId);
	if (pending) return pending;

	const request = mint(threadId, options)
		.then((session) => {
			held.set(threadId, session);
			return session;
		})
		.finally(() => {
			minting.delete(threadId);
		});

	minting.set(threadId, request);
	return request;
}

async function mint(
	threadId: string,
	options: { locale?: string; persona?: string | null; deviceId?: string },
): Promise<GraphSession> {
	const response = await fetch(`${API_URL}/v2/session`, {
		method: "POST",
		headers: { "Content-Type": "application/json", ...authHeaders() },
		body: JSON.stringify({
			session_id: threadId,
			locale: options.locale ?? "en",
			device_id: options.deviceId ?? "browser",
			...(options.persona ? { persona: options.persona } : {}),
		}),
	});

	if (!response.ok) {
		throw new Error(`Could not start a session (${response.status})`);
	}

	const body = (await response.json()) as {
		token: string;
		session_id: string;
		persona?: string;
		age_band?: string;
		account_status?: string;
		locale?: string;
		persona_refused?: boolean;
	};

	const granted = body.persona ?? "stella";

	// Announced before the session is returned, so the control is corrected in the same tick the token arrives rath…
	if (body.persona_refused && options.persona && refusedListener) {
		refusedListener({ requested: options.persona, granted });
	}

	return {
		token: body.token,
		sessionId: body.session_id,
		// Defaulted to the NARROWEST values, not the widest.
		persona: granted,
		ageBand: body.age_band ?? "5-8",
		accountStatus: body.account_status ?? "prospect",
		locale: body.locale ?? options.locale ?? "en",
		personaRefused: body.persona_refused ?? false,
	};
}
