/**
 * What the landing page leaves behind for the chat page to pick up.
 *
 * The two are separate pages now, so the first question cannot ride a mounted
 * component across the navigation. The landing page mints the id, commits the
 * rail row, and stages the question here; the chat page mounts and sends it.
 * In memory only, and deliberately: a reload between the two is a lost turn,
 * which `openPast` already renders as a send that failed after the commit.
 *
 * One slot, not a map. There is one landing page and one first send, and a map
 * would only let a stale entry fire much later.
 */

export interface PendingTurn {
	threadId: string;
	question: string;
	simple: boolean;
	/**
	 * Captured on the landing, where it is correct. The voice layer reads its
	 * stored preference in an effect, so on the chat page's first tick it still
	 * says "en" — and this turn is sent inside exactly that tick.
	 */
	language: string;
}

/** Under SSR this module is shared by every request, so it is never written to there. */
const clientSide = typeof window !== "undefined";

let pending: PendingTurn | null = null;

export function stageFirstTurn(turn: PendingTurn): void {
	if (!clientSide) return;
	pending = turn;
}

/** Non-destructive, for the loader: is this an address the server has never heard of? */
export function peekPendingTurn(threadId: string): boolean {
	return pending?.threadId === threadId;
}

/** Reads and clears together, so a re-run of the effect cannot send it twice. */
export function takePendingTurn(threadId: string): PendingTurn | null {
	if (pending?.threadId !== threadId) return null;
	const turn = pending;
	pending = null;
	return turn;
}

/**
 * A thread the landing page just minted and deliberately left EMPTY.
 *
 * Choosing a guide opens a conversation with nothing staged, so the guide can
 * speak first (see `startConversation`). That leaves the chat page holding a
 * UUID with no pending turn and no cached rows -- which is character for
 * character what an address from another device looks like, and that path ends
 * in `fetchConversation`, a 404, and a redirect back here.
 *
 * So the guide cards would bounce straight off the chat page and back to the
 * landing. Not a backend outage: the conversation genuinely does not exist yet,
 * because an empty one is never written. The 404 is correct and the conclusion
 * drawn from it was wrong.
 *
 * This is the one bit ofledger that tells the two cases apart. The landing knows
 * it minted the id a tick ago; nothing else in the system can know that.
 *
 * Read without clearing, unlike `takePendingTurn`. That one clears because
 * sending twice is the failure it guards; here a re-run must reach the SAME
 * answer, and a second effect pass that found the slot empty would fall through
 * to the fetch and bounce the reader after all.
 */
let freshThread: string | null = null;

export function markFreshThread(threadId: string): void {
	if (!clientSide) return;
	freshThread = threadId;
}

export function isFreshThread(threadId: string): boolean {
	return freshThread === threadId;
}

/**
 * The landing composer's unsent text. The page unmounts on the way to a chat,
 * so without this a draft typed at `/` would not survive coming back to it.
 */
let landingDraft = "";

export function stashLandingDraft(text: string): void {
	if (!clientSide) return;
	landingDraft = text;
}

export function readLandingDraft(): string {
	return landingDraft;
}
