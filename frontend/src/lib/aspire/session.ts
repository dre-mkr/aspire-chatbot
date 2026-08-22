/** This browser's session, and the only thing that proves who it is. */
import { API_URL } from "../config";

const DEVICE_KEY = "aspire.device.v1";
const TOKEN_KEY = "aspire.session.v1";

export interface Session {
	token: string;
	userId: string;
	accountType: "anonymous" | "registered";
	email: string | null;
	displayName: string | null;
	/**
	 * The given name the reader typed at sign-up.
	 *
	 * Its own field because `displayName` is `first last` joined, and splitting
	 * that back apart is a guess -- see `readerGivenName`.
	 */
	firstName: string | null;
	avatarUrl: string | null;
	/** Who the account is for, as chosen at sign-up. */
	role?: "participant" | "guardian" | "educator";
	/** The persona this account resolves to, derived server-side. */
	persona?: string;
	/**
	 * The band that persona answers at, and the only way to tell its voices apart.
	 *
	 * `stella` is Skye at 5-8 and Kaleb at 9-12. The persona alone cannot say
	 * which, and `bandForPersona` answers "5-8" for both, so without this a
	 * twelve-year-old was shown the five-year-old's face.
	 */
	ageBand?: string;
	/** When this token stops being accepted, in epoch milliseconds. */
	expiresAt?: number;
}

/** Storage that degrades instead of throwing. */
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
	// `randomUUID` needs a secure context, which a plain-HTTP staging box is not.
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

/** Subscribers, so every surface agrees about who is signed in. */
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

/** A session, asking for an anonymous one if this browser has none. */
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
				firstName: body.first_name ?? null,
				avatarUrl: body.avatar_url ?? null,
				persona: body.persona ?? undefined,
				ageBand: body.age_band ?? undefined,
				expiresAt: body.expires_in
					? Date.now() + Number(body.expires_in) * 1000
					: undefined,
			};
			storeSession(session);
			return session;
		})
		// An identity that cannot be obtained must not stop anyone asking a question.
		.catch(() => null)
		.finally(() => {
			inFlight = null;
		});

	return inFlight;
}

/** Discards the current identity and takes a brand-new anonymous one. */
export async function resetToFreshAnonymous(): Promise<Session | null> {
	clearSession();
	// A new seed as well as a new token.
	forget(DEVICE_KEY);
	return ensureSession();
}

/** The header that proves identity. Empty when there is nothing to prove. */
export function authHeaders(): Record<string, string> {
	const session = currentSession();
	return session ? { Authorization: `Bearer ${session.token}` } : {};
}
