/**
 * This browser's anonymous identity.
 *
 * The product has no accounts and must keep working without them: a child can
 * open it and ask a question, and nothing may stand between them and that. So
 * "who are you" is answered by an opaque id this browser mints for itself the
 * first time it needs one, and keeps.
 *
 * It is a bearer credential and nothing else. Whoever holds it can read that
 * browser's conversations — which is exactly the trust boundary that already
 * applied when those conversations lived in this same localStorage. It says
 * nothing about a person, is never displayed, and is never used as a name.
 *
 * When real accounts arrive this becomes the fallback rather than the answer:
 * the server's principal is `user:…` if you are signed in and `device:…` if you
 * are not, and nothing here changes.
 */

const DEVICE_KEY = "aspire.device.v1";

/** Same shape the service validates against; see `identity.py`. */
function mint(): string {
	const uuid = globalThis.crypto?.randomUUID?.();
	if (uuid) return uuid;
	// `randomUUID` needs a secure context, which a plain-HTTP staging box is
	// not. This is not a cryptographic fallback — it only has to be unguessable
	// enough that two browsers never collide, and it is never a secret worth
	// more than the chats behind it.
	return `t-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

let cached: string | null = null;

/**
 * The id, minting one if this browser has never had it.
 *
 * Returns null during SSR rather than inventing one: an id minted on the server
 * would be a different id for every render, would be attached to nothing, and
 * would overwrite the real one on hydration.
 */
export function deviceId(): string | null {
	if (typeof window === "undefined") return null;
	if (cached) return cached;

	try {
		const existing = window.localStorage.getItem(DEVICE_KEY);
		if (existing) {
			cached = existing;
			return existing;
		}
		const fresh = mint();
		window.localStorage.setItem(DEVICE_KEY, fresh);
		cached = fresh;
		return fresh;
	} catch {
		// Storage can be denied outright (private mode, blocked cookies). The
		// product still works; this browser is simply anonymous for the session
		// and its conversations are stored unowned.
		return null;
	}
}

/** The header every owner-scoped request carries. Empty when there is no id. */
export function deviceHeaders(): Record<string, string> {
	const id = deviceId();
	return id ? { "X-Aspire-Device": id } : {};
}
