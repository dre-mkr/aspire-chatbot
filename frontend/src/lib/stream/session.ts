/** The graph session token, and where it comes from. */
import { authHeaders } from "../aspire/session";
import { API_URL } from "../config";

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

/**
 * In-memory, per tab, per thread AND per identity asked for. Cleared by a
 * reload, which is correct.
 *
 * Keyed on the thread alone, this cache silently outranked the picker. The
 * token carries the persona and the locale, and the graph reads both off it --
 * but `graphSession` returned the held session whatever was asked for, and
 * `forget` was called from exactly one place, on an `unauthenticated` error. So
 * switching persona mid-conversation changed the URL and the UI and nothing
 * else, and switching language did the same: the turns kept running as whoever
 * the first mint had been, in whatever language it had been minted in. That is
 * the "URL flips back" report, and no backend change could have fixed it.
 *
 * Keying on the request rather than clearing on change also settles the refusal
 * case without a loop: asking for a persona the account cannot have returns a
 * session marked `personaRefused`, and because the same request maps to the
 * same key, the next turn reuses it instead of asking again forever.
 */
const held = new Map<string, GraphSession>();
/** In-flight mints, so twelve chips tapped quickly mint one token, not twelve. */
const minting = new Map<string, Promise<GraphSession>>();

/** One cache entry per (thread, persona asked for, language asked for). */
function keyFor(
	threadId: string,
	options: { locale?: string; persona?: string | null },
): string {
	return `${threadId}|${options.persona ?? ""}|${options.locale ?? ""}`;
}

export function forget(threadId: string): void {
	// Every identity minted for this thread, not just the last one.
	const prefix = `${threadId}|`;
	for (const key of [...held.keys()]) {
		if (key.startsWith(prefix)) held.delete(key);
	}
	for (const key of [...minting.keys()]) {
		if (key.startsWith(prefix)) minting.delete(key);
	}
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
	const key = keyFor(threadId, options);

	const existing = held.get(key);
	if (existing) return existing;

	const pending = minting.get(key);
	if (pending) return pending;

	const request = mint(threadId, options)
		.then((session) => {
			held.set(key, session);
			return session;
		})
		.finally(() => {
			minting.delete(key);
		});

	minting.set(key, request);
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

	// Announced before returning, so the control corrects in the token's tick.
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
