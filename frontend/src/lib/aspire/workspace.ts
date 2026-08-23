/**
 * Where a signed-in reader belongs, and which guide is waiting for them.
 *
 * THE MENTAL MODEL, and the thing the wiring was missing: the landing page is
 * somewhere you can VISIT; the chat is where the ASPIRE experience LIVES.
 * Authentication connects the two. Signing in should feel like gaining
 * continuity, not being sent back to the front door -- which is exactly what
 * `navigate({ to: "/" })` after a successful login felt like.
 */

import { markFreshThread } from "./handoff";
import { loadConversations } from "./history";
import { type AgeBand, GUIDES, type PersonaId } from "./personas";

/** A guide's id. `Guide.guideId` is a string, so this is documentation
 * rather than a constraint -- the union lives in `LandingScreen`. */
type GuideId = string;

import type { Session } from "./session";

const GUIDE_KEY = "aspire.preferred-guide";

function canStore(): boolean {
	try {
		return typeof window !== "undefined" && !!window.localStorage;
	} catch {
		// Private browsing throws on access, not on use.
		return false;
	}
}

/**
 * Remember the guide this reader chose.
 *
 * A signed-in reader's real preference lives on their account -- the server
 * derives `session.persona` from it and that is what `preferredGuide` reads
 * first. This is the fallback, and the only store an anonymous reader has.
 *
 * Written for BOTH, deliberately: a visitor who picks Kaleb and then creates an
 * account must not lose Kaleb between the two pages, and the account cannot
 * know about him until it exists.
 */
export function rememberGuide(guideId: GuideId | null): void {
	if (!canStore()) return;
	try {
		if (guideId) window.localStorage.setItem(GUIDE_KEY, guideId);
		else window.localStorage.removeItem(GUIDE_KEY);
	} catch {
		// A preference is a convenience, not a feature.
	}
}

function storedGuide(): GuideId | null {
	if (!canStore()) return null;
	try {
		const raw = window.localStorage.getItem(GUIDE_KEY);
		return GUIDES.some((guide) => guide.guideId === raw)
			? (raw as GuideId)
			: null;
	} catch {
		return null;
	}
}

/**
 * The guide to open with: the account first, then the last local choice.
 *
 * The account wins because it is the one that followed the reader to this
 * device. A `persona` alone cannot name a guide -- `stella` is Skye at 5-8 and
 * Kaleb at 9-12 -- so the band decides, and `session.ageBand` carries it.
 *
 * Null means Guest, and Guest is a real answer rather than a gap. Nobody is
 * ever held at the door because they have not chosen yet.
 */
export function preferredGuide(session: Session | null): GuideId | null {
	if (session?.accountType === "registered" && session.persona) {
		const band = session.ageBand ?? null;
		const match = GUIDES.find(
			(guide) =>
				guide.persona === (session.persona as PersonaId) &&
				(guide.band ?? null) === band,
		);
		// Bandless personas -- Zion, Imani, Azuri -- are the only guide on their
		// key, so the key alone identifies them.
		const byKey = GUIDES.find(
			(guide) => guide.persona === (session.persona as PersonaId),
		);
		if (match ?? byKey) return (match ?? byKey)?.guideId ?? null;
	}
	return storedGuide();
}

/**
 * The chat address to send a reader to, and the guide riding with it.
 *
 * Their LAST conversation when they have one, because a returning reader is
 * returning to something -- their history is the point of having an account.
 * A fresh thread otherwise, marked so the chat page knows it is new rather than
 * unreachable (see `markFreshThread`).
 */
export function workspaceDestination(session: Session | null): {
	chatId: string;
	search: { persona?: PersonaId; band?: AgeBand };
} {
	const guideId = preferredGuide(session);
	const guide = GUIDES.find((entry) => entry.guideId === guideId);
	const search = guide
		? { persona: guide.persona, ...(guide.band ? { band: guide.band } : {}) }
		: {};

	const [latest] = loadConversations();
	if (latest?.threadId) return { chatId: latest.threadId, search };

	const chatId = crypto.randomUUID();
	markFreshThread(chatId);
	return { chatId, search };
}

/**
 * The guide a persona and band identify, for writing a preference back.
 *
 * The inverse of what `preferredGuide` reads. Band first, because it is the
 * only thing that tells Skye from Kaleb; then the key alone, which is enough
 * for the three guides that are the only one on theirs.
 */
export function guideIdFor(
	persona: string | null | undefined,
	band: string | null | undefined,
): GuideId | null {
	if (!persona) return null;
	const exact = GUIDES.find(
		(guide) =>
			guide.persona === persona && (guide.band ?? null) === (band ?? null),
	);
	const byKey = GUIDES.find((guide) => guide.persona === persona);
	return (exact ?? byKey)?.guideId ?? null;
}
