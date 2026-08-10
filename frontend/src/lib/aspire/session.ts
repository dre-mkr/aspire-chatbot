/**
 * This browser's session, and the only thing that proves who it is.
 *
 * Replaces `device.ts`, which sent a device id as a header and let the server
 * treat it as identity. That was an IDOR: the id is not a secret — it goes out
 * on every request and sits in this same storage — so anyone holding somebody
 * else's could read their conversations.
 *
 * The device id survives, with a much smaller job. It is a **seed**: posted once
 * to ask for an anonymous identity, recorded server-side so a burst of sessions
 * can be attributed to one browser, and never again offered as proof of
 * anything. Authorisation is the signed token and only the signed token.
 *
 * A consequence worth being honest about: a browser that loses its token loses
 * its anonymous history even if it still has the device id, because there is no
 * credential left to present. That is the real cost of having no account, and
 * it is exactly what registering fixes.
 */

const DEVICE_KEY = "aspire.device.v1";
const TOKEN_KEY = "aspire.session.v1";

export interface Session {
	token: string;
	userId: string;
	accountType: "anonymous" | "registered";
	email: string | null;
	displayName: string | null;
	avatarUrl: string | null;
	/** Who the account is for, as chosen at sign-up. */
	role?: "participant" | "guardian" | "educator";
	/**
	 * The persona this account resolves to, derived server-side.
	 *
	 * Display only, and stored here so the picker can show the right assistant
	 * on first paint rather than sitting on "Everyone" until somebody guesses.
	 * It authorises nothing: the claims that do are signed into a separate token
	 * by `POST /v2/session`, and editing this value in storage changes which
	 * name is drawn in a menu and nothing else.
	 *
	 * Derived on the server rather than computed here from a date of birth,
	 * because a second implementation of `DEFAULT_PERSONA` in the browser is
	 * exactly what locked the 9-12 band out of the product once already — see
	 * the note in `personas.ts`.
	 */
	persona?: string;
	/**
	 * When this token stops being accepted, in epoch milliseconds.
	 *
	 * Recorded so renewal can be decided without asking the server whether it
	 * is needed. Absent on a session stored before this existed, which is read
	 * as "unknown" and simply means the first renewal waits for a 401.
	 */
	expiresAt?: number;
}

const API_URL = (
	import.meta.env.VITE_ASPIRE_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

/**
 * Storage that degrades instead of throwing.
 *
 * Private browsing and blocked cookies both make `localStorage` unavailable, and
 * a child in that mode must still be able to ask a question. The session then
 * lives in memory for the tab and disappears with it, which is the correct
 * behaviour rather than a failure.
 */
const memory = new Map<string, string>();

function read(key: string): string | null {
	try {
		return window.localStorage.getItem(key) ?? memory.get(key) ?? null;
	} catch {
		return memory.get(key) ?? null;
	}
}

function write(key: string, value: string) {
	memory.set(key, value);
	try {
		window.localStorage.setItem(key, value);
	} catch {
		// Ephemeral for this tab. Nothing else changes.
	}
}

function forget(key: string) {
	memory.delete(key);
	try {
		window.localStorage.removeItem(key);
	} catch {
		// Already gone as far as anyone can tell.
	}
}

function mintDeviceId(): string {
	const uuid = globalThis.crypto?.randomUUID?.();
	if (uuid) return uuid;
	// `randomUUID` needs a secure context, which a plain-HTTP staging box is
	// not. This is not a cryptographic fallback and does not need to be: the
	// value is a seed and a label, never a secret.
	return `t-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** The seed, minted once per browser and kept. */
export function deviceId(): string | null {
	if (typeof window === "undefined") return null;
	const existing = read(DEVICE_KEY);
	if (existing) return existing;
	const fresh = mintDeviceId();
	write(DEVICE_KEY, fresh);
	return fresh;
}

let current: Session | null = null;

/** The session in hand, if one has been established this page load. */
export function currentSession(): Session | null {
	if (current) return current;
	if (typeof window === "undefined") return null;
	const raw = read(TOKEN_KEY);
	if (!raw) return null;
	try {
		current = JSON.parse(raw) as Session;
		return current;
	} catch {
		forget(TOKEN_KEY);
		return null;
	}
}

export function storeSession(session: Session) {
	current = session;
	write(TOKEN_KEY, JSON.stringify(session));
	notify();
}

export function clearSession() {
	current = null;
	forget(TOKEN_KEY);
	notify();
}

/**
 * Subscribers, so every surface agrees about who is signed in.
 *
 * `storage` events are included, which is what stops a second tab signing in
 * and leaving this one rendering a stale signed-out state indefinitely.
 */
type Listener = () => void;
const listeners = new Set<Listener>();

function notify() {
	for (const listener of listeners) listener();
}

export function subscribeToSession(listener: Listener): () => void {
	listeners.add(listener);
	return () => {
		listeners.delete(listener);
	};
}

if (typeof window !== "undefined") {
	window.addEventListener("storage", (event) => {
		if (event.key !== TOKEN_KEY) return;
		// Another tab signed in, signed out, or was issued a new identity.
		current = null;
		notify();
	});
}

/**
 * A session, asking for an anonymous one if this browser has none.
 *
 * Deduplicated by the module-level promise: a page that mounts three things
 * needing identity makes one request, not three, and a race between them cannot
 * mint two identities and strand the conversations of the loser.
 */
let inFlight: Promise<Session | null> | null = null;

export function ensureSession(): Promise<Session | null> {
	const existing = currentSession();
	if (existing) return Promise.resolve(existing);
	if (typeof window === "undefined") return Promise.resolve(null);
	if (inFlight) return inFlight;

	inFlight = fetch(`${API_URL}/api/auth/anonymous`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ device_id: deviceId() }),
	})
		.then(async (response) => {
			if (!response.ok) return null;
			const body = await response.json();
			const session: Session = {
				token: body.token,
				userId: body.user_id,
				accountType: body.account_type,
				email: body.email ?? null,
				displayName: body.display_name ?? null,
				avatarUrl: body.avatar_url ?? null,
				expiresAt: body.expires_in
					? Date.now() + Number(body.expires_in) * 1000
					: undefined,
			};
			storeSession(session);
			return session;
		})
		// An identity that cannot be obtained must not stop anyone asking a
		// question. The turn is answered and stored unowned; the rail is empty,
		// which is honest, and the next load tries again.
		.catch(() => null)
		.finally(() => {
			inFlight = null;
		});

	return inFlight;
}

/** Discards the current identity and takes a brand-new anonymous one. */
export async function resetToFreshAnonymous(): Promise<Session | null> {
	clearSession();
	// A new seed as well as a new token. Reusing the old device id would tie the
	// new identity to the previous one in the abuse log for no benefit, and
	// signing out should not leave a thread back to who you were.
	forget(DEVICE_KEY);
	return ensureSession();
}

/** The header that proves identity. Empty when there is nothing to prove. */
export function authHeaders(): Record<string, string> {
	const session = currentSession();
	return session ? { Authorization: `Bearer ${session.token}` } : {};
}
