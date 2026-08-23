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
 * The landing's microphone, which had no wire behind it.
 *
 * The button was drawn, labelled "Voice input", and given no handler — the one
 * defect worth more than any amount of polish, because a control that looks
 * live and does nothing teaches the reader that nothing on the page is live.
 * Voice belongs to the chat page, which owns the recorder, the consent panel
 * and the language. So the landing does what it can honestly do: it opens a
 * conversation and says "this one started by tapping the microphone".
 *
 * Its own slot rather than a field on `PendingTurn`: that carries a question,
 * and this arrival has none — the reader is about to speak it.
 */
let listenOnArrival: string | null = null;

export function stageVoiceStart(threadId: string): void {
	if (!clientSide) return;
	listenOnArrival = threadId;
}

/** Reads and clears together, so a re-run of the effect cannot open the mic twice. */
export function takeVoiceStart(threadId: string): boolean {
	if (listenOnArrival !== threadId) return false;
	listenOnArrival = null;
	return true;
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
