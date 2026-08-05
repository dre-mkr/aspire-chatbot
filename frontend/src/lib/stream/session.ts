/**
 * The graph session token, and where it comes from.
 *
 * Two tokens exist in this client and they authorise different things:
 *
 *   `lib/aspire/session`  — the ACCOUNT token. Proves who you are. Sent to the
 *                           REST endpoints, which ask "may this caller read
 *                           this row?".
 *   this module           — the GRAPH token. Carries persona, age band and
 *                           account status, which decide which agents may run
 *                           and how a reply is gated.
 *
 * The second is minted from the first by `POST /v2/session`, server-side, from
 * the account record. Nothing here chooses any of those claims — the endpoint
 * ignores a body field that tries, and the only two it honours are `locale`
 * (which grants nothing) and a persona that is *narrower* than the derived one.
 *
 * ## One token per thread, held in memory only
 *
 * Keyed by thread id because the token names the conversation: `session_id` is
 * the checkpointer's thread key, so a token minted for one conversation cannot
 * be reused to turn in another.
 *
 * Deliberately NOT in `localStorage` or `sessionStorage`. It is short-lived,
 * cheap to re-mint, and carries an age band — the one claim in this product
 * worth the least effort to steal off a shared school tablet.
 */
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

/**
 * The token for this thread, minting one if there is not one already.
 *
 * `persona` is a REQUEST, not an instruction. The server grants it only when it
 * is no broader than what the account record implies, so passing the picker's
 * current value here is safe by construction: a six-year-old's client asking
 * for Aurora gets Stella and a line in the server log.
 */
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
	};

	return {
		token: body.token,
		sessionId: body.session_id,
		// Defaulted to the NARROWEST values, not the widest. These only decide
		// what the client draws — the server re-reads its own claims from the
		// token on every request — but a client that guessed "adult" would draw
		// an adult's interface for a child while the server served a child's.
		persona: body.persona ?? "stella",
		ageBand: body.age_band ?? "5-8",
		accountStatus: body.account_status ?? "prospect",
		locale: body.locale ?? options.locale ?? "en",
	};
}
