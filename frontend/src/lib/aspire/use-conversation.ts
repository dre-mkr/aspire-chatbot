import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { type AskResult, AspireError, type Source } from "./api";
import { blockIsClosed, settledBlocks } from "./settled";
import { streamAspire } from "./stream";
import { claimConversations, renameConversation } from "./conversations";
import { ensureSession } from "./session";
import { useSession } from "./use-session";
import {
	groupByRecency,
	loadConversations,
	type StoredConversation,
	type StoredMessage,
	titleFor,
} from "./history";
import {
	clearTitleLockInCache,
	conversationQuery,
	keys,
	conversationsQuery,
	readConversation,
	retitleInCache,
	upsertConversation,
} from "./queries";
import {
	type Answer,
	type AnswerBlock,
	answerToText,
	parseAnswer,
} from "./knowledge";
import { requestTitle } from "./title";

export type ChatMessage =
	| { id: number; role: "user"; text: string }
	| {
			id: number;
			role: "assistant";
			blocks: Array<AnswerBlock>;
			followUps: Array<string>;
			sources: Array<Source>;
	  }
	/**
	 * A turn that started a game. The card is its entire content.
	 *
	 * A real position in the array rather than something appended after it: a
	 * conversation carries on past a game, and a card pinned to the end would
	 * float below every later question.
	 */
	| { id: number; role: "game"; gameType: string }
	/**
	 * A turn that opened the eligibility check. The card is its entire content.
	 *
	 * A real position in the array for the same reason a game turn is: the
	 * conversation carries on past it, and a card pinned to the end would float
	 * below every later question.
	 */
	| { id: number; role: "eligibility" }
	| {
			id: number;
			role: "error";
			text: string;
			canRetry: boolean;
			/**
			 * "stopped" is the reader's own decision, not a fault, and is drawn
			 * accordingly — the same reason a wrong game answer is amber and not
			 * red. Absent means a real failure.
			 */
			tone?: "stopped";
	  };

/**
 * The answer currently being revealed, held apart from `messages`.
 *
 * The typewriter ticks 25 times a second. If the growing answer lived in the
 * messages array, every tick would hand the whole settled transcript a new
 * identity and React would re-create an element per turn — work that grows with
 * the length of the conversation, for a change confined to its last few words.
 * Keeping it separate means `messages` changes only when a turn actually
 * settles, and only this one component re-renders on a tick.
 */
export interface StreamingAnswer {
	id: number;
	blocks: Array<AnswerBlock>;
	/**
	 * The finished answer's evidence and suggestions, carried from the first tick.
	 *
	 * Not drawn while the reveal runs — they belong to an answer that has landed,
	 * and follow-ups in particular would appear above the text they follow. They
	 * are here so the transcript can *lay them out* from the start and reveal
	 * them in place, rather than mounting them at completion and growing the turn
	 * by 53px (95px with a sources chip) under whoever is reading it.
	 */
	sources: Array<Source>;
	followUps: Array<string>;
}

export type Phase = "landing" | "chat";

/** Pacing of the typewriter reveal. Tuned to read as thinking, not as lag. */
const TICK_MS = 40;

/**
 * How the reveal decides how much to draw, and why it is not a constant.
 *
 * It was a constant — four words every tick, about a hundred words a second.
 * No model writes that fast. The typewriter therefore drained whatever had
 * arrived almost instantly and then sat frozen waiting for more, which is the
 * stutter this pacing exists to remove: `reveal-sim.mjs` measured a 2.16-second
 * freeze in the middle of a perfectly ordinary answer.
 *
 * So the rate is a fraction of the backlog instead. That one change makes the
 * reveal self-tuning, because it is a proportional controller: draw
 * `pending / SMOOTH_TICKS` words a tick and, in the steady state, the reveal
 * rate converges on whatever rate the words are arriving at, whatever that
 * happens to be. The reader sees an even cadence without anything having to
 * know or measure how fast the model is.
 *
 * What it converges to is a constant *lag* rather than a constant speed:
 * roughly `SMOOTH_TICKS` ticks of text held in hand at any moment. That reserve
 * is the entire point — it is what a pause in generation is spent against, so a
 * hitch on the wire costs a slightly slower reveal instead of a dead screen.
 */
const SMOOTH_TICKS = 8;
/**
 * Words per tick, floor and ceiling.
 *
 * The floor keeps a nearly-caught-up reveal visibly moving. The ceiling is what
 * stops a burst — a reconnect, a proxy flushing, the whole reply arriving at
 * once — from dumping a paragraph into one frame.
 */
const MIN_RATE = 0.3;
const MAX_RATE = 5;
/**
 * The same, once the turn is over.
 *
 * Nothing more is coming, so there is no reserve worth keeping and the only job
 * left is to finish at a speed that still reads as typing. Without a raised
 * floor the proportional term decays toward zero and the last few words crawl.
 */
const MIN_RATE_ENDED = 2.5;
const MAX_RATE_ENDED = 8;

/** Words in a block. Lists count every word of every item, not the items. */
function blockWords(block: AnswerBlock): number {
	if (block.kind === "paragraph") return block.text ? block.text.split(" ").length : 0;
	return block.items.reduce(
		(total, item) => total + (item ? item.split(" ").length : 0),
		0,
	);
}

/**
 * A block cut to its first `words` words.
 *
 * A list is cut across its items rather than at an item boundary, so a long
 * bullet types itself out instead of appearing whole after a wait. The items
 * before the cut are complete; the one containing it is a prefix of itself,
 * which is the same append-only growth a paragraph has.
 */
function sliceBlock(block: AnswerBlock, words: number): AnswerBlock {
	if (block.kind === "paragraph") {
		return { kind: "paragraph", text: block.text.split(" ").slice(0, words).join(" ") };
	}

	const items: Array<string> = [];
	let left = words;
	for (const item of block.items) {
		if (left <= 0) break;
		const parts = item.split(" ");
		items.push(left >= parts.length ? item : parts.slice(0, left).join(" "));
		left -= parts.length;
	}
	return { kind: "list", items };
}

interface StreamCursor {
	/**
	 * The answer as far as it is known, reparsed as more of it arrives.
	 *
	 * Only ever grows, and only over settled text — see `settled.ts` — so the
	 * indices below stay valid and the reveal is never rewound.
	 */
	answer: Answer;
	sources: Array<Source>;
	id: number;
	/**
	 * Whether the service has said the turn is over.
	 *
	 * The reveal runs alongside the wire, so reaching the end of `answer` does
	 * not mean the answer is finished -- it usually means the typewriter has
	 * caught up and should wait. Only `ended` settles the turn, because only the
	 * final payload carries the sources and follow-ups that settle with it.
	 */
	ended: boolean;
	/**
	 * Whether the prose is final, which happens earlier.
	 *
	 * These are two different questions and were one flag. The text stops
	 * growing when the model stops writing; the *turn* stops when the follow-ups
	 * have been generated and the transcript persisted, which is seconds later.
	 * Conflating them meant the reveal spent those seconds treating a finished
	 * answer as one that might still grow — holding back its last word, since
	 * `settledText` cannot know a word is complete until something says so.
	 *
	 * So this governs everything about *drawing*: the pacing, whether the last
	 * block may be stepped past, and whether the trailing word is safe. `ended`
	 * governs only when the turn leaves the typewriter and joins the transcript.
	 */
	textEnded: boolean;
	blockIndex: number;
	/** Words revealed within the current block. */
	wordIndex: number;
	/**
	 * Fractional words carried between ticks.
	 *
	 * The controller's rate is usually well under one word per tick — at a
	 * realistic 25 tokens a second it is about 0.7 — and truncating that every
	 * tick would floor it to zero and stall outright. Carrying the remainder is
	 * what turns a fractional rate into "a word every tick and a half".
	 */
	credit: number;
	built: Array<AnswerBlock>;
}

/** Words to draw this tick, given how much is waiting. */
function paceFor(pending: number, ended: boolean): number {
	const rate = pending / SMOOTH_TICKS;
	return ended
		? Math.min(MAX_RATE_ENDED, Math.max(MIN_RATE_ENDED, rate))
		: Math.min(MAX_RATE, Math.max(MIN_RATE, rate));
}

/** Words known but not yet drawn. The controller's only input. */
function pendingWords(state: StreamCursor): number {
	let total = -state.wordIndex;
	for (let i = state.blockIndex; i < state.answer.blocks.length; i += 1) {
		total += blockWords(state.answer.blocks[i]);
	}
	return Math.max(0, total);
}

function prefersReducedMotion() {
	return (
		typeof window !== "undefined" &&
		window.matchMedia("(prefers-reduced-motion: reduce)").matches
	);
}

/**
 * Mints the id for a conversation, in the browser, before anything is sent.
 *
 * This used to come back on the `/chat` response, which made the id an outcome
 * of the round trip — and a URL cannot become `/chat/:id` a beat before an id
 * exists. Minting here is what lets the address bar, the sidebar row and the
 * title bar all arrive with the user's own message rather than trailing the
 * server by a second or more.
 *
 * Safe to do: the backend takes `thread_id or uuid4()`, so a supplied id is
 * already authoritative, and the games endpoints accept any string. Nothing
 * downstream ever parsed this value.
 *
 * `randomUUID` needs a secure context, which a plain-HTTP staging box is not.
 * The fallback is not for cryptography — it only has to not collide inside one
 * browser's history.
 */
function newThreadId(): string {
	const uuid = globalThis.crypto?.randomUUID?.();
	if (uuid) return uuid;
	return `t-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * What to call a conversation that opened with a game.
 *
 * A game turn has no assistant prose, so there is nothing for the title model to
 * read and the chat would keep the truncated question ("Can we play the word
 * scramble?") forever. These are deterministic rather than generated: the title
 * is known the moment the game starts, so a model call would add a failure mode
 * and a delay for a string we can already write correctly.
 *
 * The server's `display_name` is not used because it is authored per set and is
 * currently English in every language directory — deriving the title from it
 * would put an English name on a Spanish chat.
 */
const GAME_TITLES: Record<string, Record<string, string>> = {
	word_scramble: {
		en: "Word scramble practice",
		es: "Práctica de palabras revueltas",
		fr: "Entraînement de mots mêlés",
	},
	true_false: {
		en: "True or false round",
		es: "Ronda de verdadero o falso",
		fr: "Tour de vrai ou faux",
	},
};

function gameTitle(gameType: string, language: string): string | null {
	const byLanguage = GAME_TITLES[gameType];
	if (!byLanguage) return null;
	return byLanguage[language] ?? byLanguage.en;
}

/**
 * What to call a conversation that opened with the eligibility check.
 *
 * Same problem as a game turn: no assistant prose means nothing for the title
 * model to read, so the chat would keep the truncated question ("Am I too old
 * for ASPIRE?") for good. Deterministic rather than generated — the title is
 * known the moment the card opens, and it must never be derived from the
 * answers.
 */
const ELIGIBILITY_TITLES: Record<string, string> = {
	en: "ASPIRE eligibility check",
	es: "Consulta de elegibilidad de ASPIRE",
	fr: "Vérification d'admissibilité ASPIRE",
};

function eligibilityTitle(language: string): string {
	return ELIGIBILITY_TITLES[language] ?? ELIGIBILITY_TITLES.en;
}

function completed(
	answer: Answer,
	sources: Array<Source>,
	id: number,
): ChatMessage {
	return {
		id,
		role: "assistant",
		blocks: answer.blocks,
		followUps: answer.followUps,
		sources,
	};
}

/** Transcript shape the rail persists, dropping ids. */
function toStored(messages: Array<ChatMessage>): Array<StoredMessage> {
	const stored: Array<StoredMessage> = [];
	for (const message of messages) {
		if (message.role === "user")
			stored.push({ role: "user", text: message.text });
		else if (message.role === "game")
			stored.push({ role: "game", gameType: message.gameType });
		else if (message.role === "eligibility")
			stored.push({ role: "eligibility" });
		else if (message.role === "assistant") {
			stored.push({
				role: "assistant",
				blocks: message.blocks,
				sources: message.sources,
				followUps: message.followUps,
			});
		}
		// Errors are transient and are not worth reopening later.
	}
	return stored;
}

export interface UseConversationOptions {
	/**
	 * Which language to name the conversation in.
	 *
	 * A getter because the voice layer that owns this setting is constructed
	 * after this hook. Read at call time, once, when a title is requested.
	 */
	getLanguage?: () => string;
	/**
	 * Fired the moment a reply lands, with the whole text — before the
	 * typewriter starts revealing it. Read-aloud uses this so audio begins as
	 * the answer arrives rather than after it has finished being drawn.
	 */
	onAnswer?: (id: number, text: string) => void;
	/** Who is talking. Null means unknown, which the service treats as permissive. */
	persona?: string | null;
	/**
	 * Fired synchronously inside `send`, the instant a conversation is minted.
	 *
	 * Carries the brand-new thread id, in the same commit as the optimistic user
	 * bubble and the storage write. The shell uses it to replace `/` with
	 * `/chat/:id`, which is why the address bar never lags the message.
	 */
	onThreadStart?: (threadId: string) => void;
	/**
	 * Fired when a turn started a game instead of answering.
	 *
	 * The shell responds by loading the game's authoritative state. Separate
	 * from `onAnswer` on purpose: this turn has no text, and everything hung off
	 * `onAnswer` (read-aloud, most obviously) must not run for it.
	 */
	onGameStart?: (threadId: string) => void;
	/**
	 * Fired when a turn opened the eligibility check instead of answering.
	 *
	 * Separate from `onAnswer` for the same reason `onGameStart` is: this turn
	 * has no text, so read-aloud must not fire for it. The card speaks its own
	 * question when asked to.
	 */
	onEligibilityStart?: (threadId: string, language: string) => void;
}

export function useConversation({
	onAnswer,
	persona = null,
	getLanguage = () => "en",
	onThreadStart,
	onGameStart,
	onEligibilityStart,
}: UseConversationOptions = {}) {
	const [phase, setPhase] = useState<Phase>("landing");
	const [messages, setMessages] = useState<Array<ChatMessage>>([]);
	const [streaming, setStreaming] = useState<StreamingAnswer | null>(null);
	const [isThinking, setIsThinking] = useState(false);
	const queryClient = useQueryClient();

	/**
	 * Every conversation this browser owns.
	 *
	 * Server state now, not device state. It used to be read out of localStorage,
	 * which quietly made a conversation a property of a browser: the transcripts
	 * were already in Postgres, but nothing recorded whose they were, so nothing
	 * could read them back.
	 */
	// Subscribed to the session, so a sign-in or sign-out re-renders this and
	// the query picks up the new owner's key. Without it the hook would keep
	// asking for the previous identity's list.
	const { session } = useSession();
	const conversations = useQuery(conversationsQuery(session?.userId ?? "anon"));
	const history = useMemo(
		() => groupByRecency(conversations.data ?? []),
		[conversations.data],
	);
	const [threadId, setThreadId] = useState<string | null>(null);
	/**
	 * The oldest message id allowed to play its entry animation.
	 *
	 * `.turn` animates `rise` on mount, which is right for a message that was
	 * just sent and wrong for forty that were just read out of storage —
	 * reopening a conversation replayed the whole transcript's arrival, so a
	 * chat from last week looked like it was being typed at you again.
	 *
	 * Ids are monotonic, so "everything from here up is new" is a single number.
	 * Restoring parks it past the restored block; sending leaves it alone,
	 * because the message being sent is always above it.
	 */
	const [animateAfterId, setAnimateAfterId] = useState(0);

	const nextId = useRef(0);
	const streamTimer = useRef<ReturnType<typeof setInterval>>(undefined);
	const cursor = useRef<StreamCursor | undefined>(undefined);
	/** Last question asked, so "Try again" can re-ask it. */
	const lastQuestion = useRef("");
	/**
	 * Guards against a reply from an abandoned turn landing in the transcript —
	 * "New chat" or a second question while the first is still in flight.
	 */
	const turnToken = useRef(0);
	/**
	 * Cancels the request behind the turn in flight.
	 *
	 * `turnToken` already stopped an abandoned reply from being *rendered*, but
	 * the work carried on regardless: the model finished generating, the service
	 * persisted the turn, and the programme was billed for an answer nobody would
	 * ever see. Bumping a number cannot stop a fetch; only aborting it can.
	 */
	const inFlight = useRef<AbortController | null>(null);

	/** Ends the request in flight, if there is one. Safe to call twice. */
	const abortInFlight = useCallback(() => {
		inFlight.current?.abort();
		inFlight.current = null;
	}, []);
	/**
	 * Threads this session has already tried to name.
	 *
	 * A ref, not state, so a re-render cannot fire a second call. Keyed by
	 * thread so reopening a past conversation never re-titles it.
	 */
	const titledThreads = useRef(new Set<string>());
	/**
	 * Mirrors `isThinking` for the in-flight guard in `send`.
	 *
	 * A ref rather than the state value because `send` is deliberately stable —
	 * depending on `isThinking` would rebuild the whole send pipeline on every
	 * turn.
	 */
	const isThinkingRef = useRef(false);
	// Held in a ref so a changing callback never re-creates the send pipeline.
	const onAnswerRef = useRef(onAnswer);
	useEffect(() => {
		onAnswerRef.current = onAnswer;
	}, [onAnswer]);

	// Same reason as onAnswer: the voice layer is created after this hook (it
	// needs the thread id this hook owns), so the language reaches the title
	// call through a ref rather than a prop.
	const getLanguageRef = useRef(getLanguage);
	useEffect(() => {
		getLanguageRef.current = getLanguage;
	}, [getLanguage]);

	// Same again: `send` has to stay stable, and the shell's navigate callback
	// is not.
	const onThreadStartRef = useRef(onThreadStart);
	useEffect(() => {
		onThreadStartRef.current = onThreadStart;
	}, [onThreadStart]);

	const onGameStartRef = useRef(onGameStart);
	useEffect(() => {
		onGameStartRef.current = onGameStart;
	}, [onGameStart]);

	const onEligibilityStartRef = useRef(onEligibilityStart);
	useEffect(() => {
		onEligibilityStartRef.current = onEligibilityStart;
	}, [onEligibilityStart]);

	/**
	 * The thread the next request belongs to, readable synchronously.
	 *
	 * `send` mints an id and `ask` runs in the same tick, so the state setter has
	 * not landed yet and a closure over `threadId` would still say null — which
	 * would have the backend mint a *second* conversation for a chat the URL was
	 * already pointing at. The ref is the value; the state is for rendering.
	 */
	const threadRef = useRef<string | null>(null);

	// Commits before any later click can be dispatched, so the guard in `send`
	// never reads a stale value.
	useEffect(() => {
		isThinkingRef.current = isThinking;
	}, [isThinking]);

	/**
	 * Adopt the conversations this browser started before ownership existed.
	 *
	 * Runs once. Every transcript written before the owner column is readable by
	 * nobody, and this browser is the only thing left that knows their ids —
	 * presenting one is the strongest claim available in a product with no
	 * accounts. The service only ever adopts rows that are currently unowned, so
	 * replaying somebody else's ids takes nothing.
	 *
	 * Failure is silent and harmless: those conversations stay unreadable, which
	 * is exactly where they were a moment ago.
	 */
	// biome-ignore lint/correctness/useExhaustiveDependencies: once, on mount
	useEffect(() => {
		// An identity first, because everything user-scoped is gated on having
		// one. Anonymous and free: nobody is asked to sign up, and a failure here
		// costs the rail its contents and nothing else — the chat still works.
		void ensureSession()
			.then(async (session) => {
				if (!session) return;
				// The queries were disabled while there was no session. Now there
				// is one, so they may run.
				await queryClient.invalidateQueries({
					queryKey: conversationsQuery().queryKey,
				});

				const stranded = loadConversations().map((c) => c.threadId);
				if (stranded.length === 0) return;
				const claimed = await claimConversations(stranded).catch(() => 0);
				if (claimed > 0) {
					await queryClient.invalidateQueries({
						queryKey: conversationsQuery().queryKey,
					});
				}
			})
			.catch(() => undefined);
	}, []);

	/**
	 * Names a conversation, in the cache and on the server.
	 *
	 * Cache first so the rail changes now rather than after a round trip — a
	 * title crossfading in is a deliberate moment in this product, and putting a
	 * network hop in front of it would turn it into a stutter. The PATCH is
	 * fire-and-forget for the same reason every title path here is: a name that
	 * fails to save is worth strictly less than the answer the reader is looking
	 * at, and must never interrupt it.
	 */
	const nameConversation = useCallback(
		(id: string, title: string, source: "generated" | "manual") => {
			retitleInCache(queryClient, id, title, source);
			void renameConversation(id, title, source)
				// Only once the service has it. The completion handoff invalidates
				// the list at almost exactly this moment, and a refetch that started
				// before the rename landed answers with the old name — which would
				// put the truncated question back a beat after the generated title
				// crossfaded in. Re-asking after the write is what settles it.
				.then(() => queryClient.invalidateQueries({ queryKey: keys.allConversations() }))
				.catch(() => undefined);
		},
		[queryClient],
	);

	const clearTimers = useCallback(() => {
		clearInterval(streamTimer.current);
		streamTimer.current = undefined;
	}, []);

	/** Abandons whatever is being revealed without settling it. */
	const dropStream = useCallback(() => {
		clearTimers();
		cursor.current = undefined;
		setStreaming(null);
	}, [clearTimers]);

	useEffect(() => clearTimers, [clearTimers]);

	// Leaving the page is the clearest possible signal that nobody is waiting for
	// this answer. Before this, closing the tab mid-reply left the model
	// generating to the end and the turn billed in full.
	useEffect(() => abortInFlight, [abortInFlight]);

	/** The reveal reached the end: the answer joins the settled transcript. */
	const finishStream = useCallback(() => {
		clearTimers();
		const state = cursor.current;
		cursor.current = undefined;
		setStreaming(null);
		if (!state) return;
		setMessages((current) => [
			...current,
			completed(state.answer, state.sources, state.id),
		]);
	}, [clearTimers]);

	/**
	 * Settles only what has actually been revealed.
	 *
	 * Deliberately not `finishStream`, which appends `state.answer` — the whole
	 * reply, including the words the reveal had not reached. Calling that from
	 * `stop` made the stop button a reveal-everything button for the entire
	 * length of the typewriter, which is the opposite of what it says.
	 *
	 * Follow-ups are dropped: they belong to an answer that finished.
	 *
	 * Used by the two ways a turn can end early — the reader pressing Stop, and
	 * the stream dying mid-flight. Defined here rather than beside `stop` because
	 * `ask` needs it too, and a `useCallback` cannot depend on one declared
	 * further down the component.
	 */
	const settleRevealed = useCallback(() => {
		clearTimers();
		const state = cursor.current;
		cursor.current = undefined;
		setStreaming(null);
		if (!state) return;

		const revealed = state.built.filter(Boolean);
		if (revealed.length === 0) return;

		setMessages((current) => [
			...current,
			{
				id: state.id,
				role: "assistant",
				blocks: revealed,
				followUps: [],
				sources: state.sources,
			},
		]);
	}, [clearTimers]);

	const tick = useCallback(() => {
		const state = cursor.current;
		if (!state) return;

		const pending = pendingWords(state);
		if (pending === 0) {
			// Caught up. Everything written has been drawn; the turn settles only
			// once the payload has arrived, because the sources and follow-ups
			// have to appear in the same commit as the answer they belong to.
			// Finishing before that would truncate the answer mid-sentence.
			if (state.ended) finishStream();
			return;
		}

		state.credit += paceFor(pending, state.textEnded);
		const budget = Math.floor(state.credit);
		// Less than a whole word owed. The remainder carries; drawing nothing is
		// correct and costs one frame, not a stall.
		if (budget < 1) return;
		state.credit -= budget;

		let left = budget;
		while (left > 0) {
			const block = state.answer.blocks[state.blockIndex];
			if (!block) break;

			const total = blockWords(block);
			const take = Math.min(left, total - state.wordIndex);
			if (take > 0) {
				state.wordIndex += take;
				left -= take;
				state.built[state.blockIndex] = sliceBlock(block, state.wordIndex);
			}

			if (state.wordIndex < total) break;
			// This block is fully drawn. Stepping past it is only safe once it can
			// no longer grow -- otherwise the words that arrive next are written
			// into a block the typewriter has already left behind, and never
			// appear until the finished answer replaces the revealed one.
			if (!blockIsClosed(state.blockIndex, state.answer.blocks, state.textEnded))
				break;
			state.blockIndex += 1;
			state.wordIndex = 0;
		}

		setStreaming({
			id: state.id,
			blocks: [...state.built],
			sources: state.sources,
			followUps: state.answer.followUps,
		});
	}, [finishStream]);

	/**
	 * Starts revealing an answer. Returns its id.
	 *
	 * `ended` says whether the whole reply is already in hand. When it is — the
	 * non-streaming fallback, a restored turn — the typewriter simply plays it
	 * out. When it is not, the same loop runs against an answer that is still
	 * growing, and the pacing controller above is what keeps the cadence even
	 * across the difference.
	 */
	const beginStream = useCallback(
		(answer: Answer, sources: Array<Source>, ended = true) => {
			setIsThinking(false);
			const id = nextId.current++;

			// Reduced motion still skips the reveal, but only once the answer is
			// whole -- settling a half-delivered stream would drop the rest of it.
			if (ended && prefersReducedMotion()) {
				setMessages((current) => [...current, completed(answer, sources, id)]);
				return id;
			}

			cursor.current = {
				answer,
				sources,
				id,
				ended,
				// A reply handed over whole is finished in both senses at once.
				textEnded: ended,
				blockIndex: 0,
				wordIndex: 0,
				credit: 0,
				built: [],
			};
			setStreaming({
				id,
				blocks: [],
				sources,
				followUps: answer.followUps,
			});
			streamTimer.current = setInterval(tick, TICK_MS);
			return id;
		},
		[tick],
	);

	/**
	 * Asks the service and reveals the reply.
	 *
	 * There is no artificial thinking delay any more: the request itself takes
	 * real time, and the thinking orb covers exactly that.
	 */
	const ask = useCallback(
		async (question: string, simpleMode: boolean, token: number) => {
			const controller = new AbortController();
			inFlight.current?.abort(); // a previous turn should never outlive this one
			inFlight.current = controller;
			/**
			 * Feeds the reveal from the wire, without letting the wire pace it.
			 *
			 * Two separate things have to be true at once, and they pull against
			 * each other. Nothing may be shown before it is safe to show —
			 * `settledBlocks` owns that, and holds back only an ambiguous prefix
			 * and a partial word. And the reveal has to advance evenly whatever
			 * the model is doing — the controller above owns that, by drawing a
			 * fraction of the backlog rather than a fixed number of words.
			 *
			 * Neither alone is enough. Safe-but-unpaced empties its buffer and
			 * freezes; paced-but-unsafe rewrites lines that have already been
			 * read. Together they are a reveal that starts within a word or two
			 * of the first token and keeps moving until the last one.
			 */
			let buffer = "";
			let streamingId = -1;
			const onDelta = (delta: string) => {
				if (turnToken.current !== token) return;
				buffer += delta;

				const blocks = settledBlocks(buffer, false);
				if (streamingId === -1) {
					// Nothing settles until the first newline lands, which on a real
					// reply is one line. The thinking orb covers exactly that gap;
					// starting the reveal on an empty block list would replace it
					// with an empty bubble.
					if (blocks.length === 0) return;
					streamingId = beginStream({ blocks, followUps: [] }, [], false);
					return;
				}

				const state = cursor.current;
				if (!state) return;
				// Only ever grows, and only over settled text, so `built` indices
				// stay valid and the reveal is never rewound.
				state.answer = { ...state.answer, blocks };
			};

			/**
			 * The model has stopped writing. The turn has not finished.
			 *
			 * Re-settles the buffer with nothing held back — the trailing word is
			 * safe now, and it is the one `settledText` was keeping — and lets the
			 * reveal draw to the end at its finishing pace. The turn itself still
			 * waits for the payload, so the sources and follow-ups appear in the
			 * same commit as the answer settling, exactly as before.
			 */
			const onTextEnd = () => {
				if (turnToken.current !== token) return;
				const state = cursor.current;
				if (!state) return;
				state.answer = { ...state.answer, blocks: settledBlocks(buffer, true) };
				state.textEnded = true;
			};

			try {
				const result: AskResult = await streamAspire({
					message: question,
					onDelta,
					onTextEnd,
					signal: controller.signal,
					// Read now, not closed over: see `threadRef`. This is also why
					// `ask` no longer depends on `threadId` — the send pipeline used
					// to be rebuilt on every turn for a value it can read directly.
					threadId: threadRef.current,
					simpleMode,
					persona,
					// Read at call time for the same reason the title call does: the
					// voice layer that owns this setting is built after this hook.
					// It decides which language the eligibility card opens in.
					language: getLanguageRef.current(),
				});

				if (turnToken.current !== token) return; // the turn was abandoned

				// Adopt the server's id only when we had none to begin with.
				//
				// Once this browser mints an id, that id *is* the conversation: it
				// is in the address bar, it is the storage key, and it is what the
				// sidebar row and the games session are filed under. Overwriting it
				// with a different value from the response leaves all four pointing
				// at a thread that no longer exists — the reconciler sees the open
				// chat stop matching the URL, reloads the half-written record from
				// storage, and replaces the answer arriving on screen with the
				// never-got-an-answer recovery turn.
				//
				// The real service echoes `request.thread_id`, so this only ever
				// differs if something upstream rewrites it. When it does, the
				// address the user is looking at wins.
				if (!threadRef.current) {
					threadRef.current = result.threadId;
					setThreadId(result.threadId);
				}

				// A game turn is the card and nothing else.
				//
				// No assistant message is created at all — not an empty one, not a
				// placeholder. That is what makes the rest of the requirements fall
				// out rather than needing their own special cases: there is no
				// text to render beside the card, no typewriter, and no copy /
				// Play / Ask again row, because those belong to `Answer` and it
				// never mounts. `onAnswer` never fires either, so read-aloud stays
				// silent on a turn whose only content is a puzzle it must not read
				// out — "Ask again" would reroll the puzzle mid-play, and speaking
				// the word would give it away.
				//
				// The card itself comes from the games endpoint, which is the one
				// authority on the session's state.
				if (result.startedGame) {
					setIsThinking(false);
					setMessages((current) => [
						...current,
						{
							id: nextId.current++,
							role: "game",
							gameType: result.startedGame?.gameType ?? "",
						},
					]);

					// Name the chat now, while we know what it is. With no prose on
					// this turn the title effect below never fires, so without this
					// a chat that opened with a game would keep the truncated
					// question as its name for good.
					//
					// Written as "generated" rather than "manual": an explicit
					// regenerate should still be able to replace it later, once the
					// conversation has some actual content to name it after.
					const named = gameTitle(
						result.startedGame.gameType,
						getLanguageRef.current(),
					);
					if (named && !titledThreads.current.has(result.threadId)) {
						titledThreads.current.add(result.threadId);
						nameConversation(result.threadId, named, "generated");
					}

					onGameStartRef.current?.(result.threadId);
					return;
				}

				// An eligibility turn is the card and nothing else, for the same
				// reason and by the same mechanism as a game turn: no assistant
				// message is created, so there is no text beside the card, no
				// typewriter, and no copy / Play / Ask again row — those belong to
				// `Answer` and it never mounts.
				//
				// `onAnswer` never fires either, which is what keeps read-aloud
				// silent here. That matters more than on a game: "Ask again" would
				// restart a flow someone is part-way through, and speaking a turn
				// with no prose would read out nothing at all. The card speaks its
				// own question and its own verdict, on request.
				if (result.startedEligibility) {
					setIsThinking(false);
					setMessages((current) => [
						...current,
						{ id: nextId.current++, role: "eligibility" },
					]);

					// Name the chat now, while we know what it is. With no prose on
					// this turn the title effect never fires, so without this a chat
					// that opened with the check would keep the truncated question
					// ("Am I too old for ASPIRE?") as its name for good.
					//
					// "generated" rather than "manual", so an explicit regenerate can
					// still improve it once the conversation has more to name it after.
					const named = eligibilityTitle(result.startedEligibility.language);
					if (!titledThreads.current.has(result.threadId)) {
						titledThreads.current.add(result.threadId);
						nameConversation(result.threadId, named, "generated");
					}

					onEligibilityStartRef.current?.(
						result.threadId,
						result.startedEligibility.language,
					);
					return;
				}

				// The payload is authoritative, not the accumulated deltas: on a
				// card turn the service deliberately sends an empty reply, and the
				// final blocks must come from it rather than from whatever text
				// escaped down the wire.
				const finalAnswer: Answer = {
					blocks: parseAnswer(result.reply),
					followUps: result.followUps,
				};

				const live = cursor.current;
				if (live && live.id === streamingId) {
					// A reveal is already running. Hand it the finished answer and
					// let it play out to the end at its own pace.
					live.answer = finalAnswer;
					live.sources = result.sources;
					live.ended = true;
					// Usually already true, from `TEXT_MESSAGE_END`. Not always:
					// the service may end a turn without one — a card turn, or an
					// older deployment that does not send it.
					live.textEnded = true;
				} else {
					// Nothing was ever revealed -- a reply with no newline in it, or
					// the non-streaming fallback inside `streamAspire`. Start whole.
					streamingId = beginStream(finalAnswer, result.sources, true);
				}
				onAnswerRef.current?.(streamingId, result.reply);
			} catch (error) {
				if (turnToken.current !== token) return;

				// A reveal may still be running against a stream that has died.
				// Nothing more is coming, so the typewriter would tick forever
				// waiting for words that will never arrive -- and because the
				// composer is busy for as long as something is being revealed,
				// that left it stuck with no way to ask anything again.
				//
				// Settled rather than dropped, for the same reason `stop` settles
				// it: the words are already on screen and taking them back as the
				// error appears is worse than leaving them.
				//
				// This could not happen before the reveal began mid-line. A
				// dropped connection almost always cut in before the first
				// newline, so there was never anything running to leave behind --
				// the bug was real, and unreachable, and starting sooner is what
				// reached it.
				if (cursor.current) settleRevealed();
				setIsThinking(false);
				setMessages((current) => [
					...current,
					{
						id: nextId.current++,
						role: "error",
						text:
							error instanceof AspireError
								? error.message
								: "Something went wrong. Please try again.",
						canRetry: error instanceof AspireError ? error.canRetry : true,
					},
				]);
			}
		},
		// `nameConversation`, `queryClient` and `settleRevealed` are all stable
		// references, so naming them here does not rebuild the send pipeline every
		// turn — which is the property these dependency lists have always been
		// protecting.
		[beginStream, persona, nameConversation, settleRevealed],
	);

	const send = useCallback(
		(raw: string, simpleMode = false) => {
			const text = raw.trim();
			if (!text) return;
			// A second question while the first is still in flight used to bump
			// the turn token, so the first reply was discarded on arrival and its
			// user bubble sat in the transcript forever with no answer and no
			// error. The composer disables send while busy; this is the guard
			// behind it.
			if (isThinkingRef.current || cursor.current) return;

			dropStream();
			lastQuestion.current = text;
			const token = ++turnToken.current;

			// The first message of a conversation is the moment it becomes real:
			// it gets an id, an address, and a row in the sidebar, all in this one
			// synchronous block, before a single byte has gone to the server.
			//
			// Everything below the branch is deliberately ordered so that one
			// React commit carries the whole change — the user's bubble, the
			// phase morph, the history entry and the URL land together, and the
			// 560ms transition runs through it without a stutter.
			const opening = !threadRef.current;
			if (opening) {
				const minted = newThreadId();
				threadRef.current = minted;
				setThreadId(minted);

				// Committed now, not when the answer settles. It used to be
				// written by the persist effect below, which waits for a settled
				// assistant turn — so the sidebar row for a brand-new chat did not
				// appear until the request had returned *and* the typewriter had
				// finished revealing it, seconds after the message was sent.
				//
				// The label is the truncated question, which is exactly the
				// provisional title the generated one crossfades over later.
				// Optimistic, and that is the whole point: the row has always
				// appeared in the same commit as the user's own bubble, before a
				// byte has gone to the server. The completion handoff invalidates
				// the list a moment later, so the service's version wins.
				upsertConversation(queryClient, {
					threadId: minted,
					title: titleFor(text),
					updatedAt: Date.now(),
					messages: [{ role: "user", text }],
				});

				onThreadStartRef.current?.(minted);
			}

			setPhase("chat");
			setIsThinking(true);
			setMessages((current) => [
				...current,
				{ id: nextId.current++, role: "user", text },
			]);

			void ask(text, simpleMode, token);
		},
		[ask, dropStream, queryClient],
	);

	/**
	 * Re-asks the question behind one specific answer, replacing that answer.
	 *
	 * Takes the id of the message the button was rendered next to. It used to
	 * take no argument at all: it re-asked `lastQuestion` — whatever was asked
	 * most recently — and dropped `messages.at(-1)`. Since the same handler is
	 * rendered under every answer, pressing "Try again" on the first of three
	 * silently destroyed the third and re-ran the third question. There is no
	 * undo, so that was unrecoverable.
	 */
	const regenerate = useCallback(
		(messageId: number, simpleMode = false) => {
			const index = messages.findIndex((m) => m.id === messageId);
			if (index === -1) return;

			// The question this answer came from is the nearest user turn above
			// it, not the newest one in the transcript.
			let question = "";
			for (let i = index - 1; i >= 0; i -= 1) {
				const previous = messages[i];
				if (previous.role === "user") {
					question = previous.text;
					break;
				}
			}
			if (!question) return;

			dropStream();
			const token = ++turnToken.current;
			lastQuestion.current = question;

			// Re-found inside the updater so a turn that settled between the
			// click and this point cannot make the index cut in the wrong place.
			setMessages((current) => {
				const at = current.findIndex((m) => m.id === messageId);
				return at === -1 ? current : current.slice(0, at);
			});
			setIsThinking(true);

			void ask(question, simpleMode, token);
		},
		[ask, dropStream, messages],
	);

	/**
	 * Abandons the turn in flight.
	 *
	 * Bumping the token makes `ask` discard the reply when it lands. A partly
	 * revealed answer is settled rather than thrown away — the words are already
	 * on screen and deleting them as you read is its own small betrayal.
	 */
	const stop = useCallback(() => {
		turnToken.current += 1;
		// The half that was missing. Without this, Stop only hid the answer.
		abortInFlight();

		// Keep whatever is already on screen — the words are there to be read,
		// and deleting them as you read is its own small betrayal — but keep only
		// those, not the rest of the reply.
		if (cursor.current) settleRevealed();
		setIsThinking(false);

		// Then say what happened, in both branches. Without this a stop before
		// the first word left the question sitting there forever with no answer
		// and no explanation: the same orphan this control exists to prevent.
		setMessages((current) => {
			if (current.at(-1)?.role === "error") return current;
			return [
				...current,
				{
					id: nextId.current++,
					role: "error",
					text: "You stopped this answer.",
					canRetry: true,
					tone: "stopped",
				},
			];
		});
	}, [settleRevealed, abortInFlight]);

	/**
	 * Keep the rail's row in step with the exchange that just settled.
	 *
	 * This no longer *persists* anything -- the service wrote the turn as it
	 * answered, which is why a transcript survives a browser being cleared now.
	 * What is left is the optimistic half: move the row to the top with the
	 * turns it has, so the rail is right in the same commit rather than after a
	 * round trip. The completion handoff refetches immediately behind it.
	 */
	useEffect(() => {
		if (!threadId) return;

		const tail = messages.at(-1);
		// A game or eligibility turn settles the exchange just as an answer
		// does. Without it here, a conversation that opened with one was never
		// written at all beyond its first user message -- so reopening it found
		// a question with nothing after it and decorated it with the
		// never-got-an-answer retry, for a card that was running fine.
		if (
			tail?.role !== "assistant" &&
			tail?.role !== "game" &&
			tail?.role !== "eligibility"
		)
			return;

		const firstQuestion = messages.find((m) => m.role === "user");
		if (firstQuestion?.role !== "user") return;

		// Whatever this conversation is already called wins over a fresh
		// truncation: a generated or hand-typed title must survive every later
		// turn, and this effect runs on all of them.
		const existing = readConversation(queryClient, threadId);

		upsertConversation(queryClient, {
			threadId,
			title: existing?.title || titleFor(firstQuestion.text),
			titleSource: existing?.titleSource,
			updatedAt: Date.now(),
			messages: toStored(messages),
		});
	}, [messages, threadId, queryClient]);

	/**
	 * Name the conversation, once, after its first answer has landed.
	 *
	 * Fire-and-forget by construction: nothing awaits it, nothing renders
	 * differently until it resolves, and every failure path ends in the title
	 * staying exactly as it was. `titledThreads` is a ref rather than state so a
	 * re-render cannot fire a second call, and it is keyed by thread so
	 * reopening a past conversation never re-titles it.
	 */
	useEffect(() => {
		if (!threadId || titledThreads.current.has(threadId)) return;

		const tail = messages.at(-1);
		if (tail?.role !== "assistant") return;

		const firstQuestion = messages.find((m) => m.role === "user");
		if (firstQuestion?.role !== "user") return;

		// Only the opening exchange names the chat, so a conversation that
		// already has more than one answer was restored, not just started.
		const answers = messages.filter((m) => m.role === "assistant");
		if (answers.length !== 1) return;

		const stored = readConversation(queryClient, threadId);
		if (stored?.titleSource) return; // already named, or named by hand

		titledThreads.current.add(threadId);

		void requestTitle({
			message: firstQuestion.text,
			answer: answerToText(tail.blocks),
			language: getLanguageRef.current(),
		}).then((title) => {
			// Null means the service declined — a greeting, gibberish, or a
			// failed call. The truncated first message stays.
			if (!title) return;
			nameConversation(threadId, title, "generated");
		});
	}, [messages, threadId, queryClient, nameConversation]);

	/**
	 * Renames a conversation by hand.
	 *
	 * Marks it "manual", which is what stops a generated title from ever
	 * replacing it — including a title already in flight for this thread.
	 */
	const renameChat = useCallback(
		(id: string, title: string) => {
			titledThreads.current.add(id);
			nameConversation(id, title, "manual");
		},
		[nameConversation],
	);

	/**
	 * Asks for a fresh title for one conversation.
	 *
	 * Clears the manual lock first, so an explicit regenerate is the one thing
	 * that may overwrite a hand-typed name — and only for the chat it was asked
	 * for. Reads that conversation's own opening exchange from storage, so it
	 * works on any row in the rail, not just the one that is open.
	 */
	const regenerateTitle = useCallback(
		(id: string) => {
			// The rail's rows carry no transcripts, so the opening exchange is
			// fetched rather than read off the row. Cached afterwards, so asking
			// twice costs one round trip.
			void queryClient
				.ensureQueryData(conversationQuery(id))
				.then((stored) => {
					const question = stored.messages.find((m) => m.role === "user");
					const answer = stored.messages.find((m) => m.role === "assistant");
					if (question?.role !== "user" || answer?.role !== "assistant") return;

					clearTitleLockInCache(queryClient, id);
					titledThreads.current.add(id);

					return requestTitle({
						message: question.text,
						answer: answerToText(answer.blocks),
						language: getLanguageRef.current(),
					}).then((title) => {
						if (!title) return;
						nameConversation(id, title, "generated");
					});
				})
				.catch(() => undefined);
		},
		[queryClient, nameConversation],
	);

	/** Reopens a stored conversation; everything lands already finished. */
	const openPast = useCallback(
		(conversation: StoredConversation) => {
			abortInFlight();
			dropStream();
			turnToken.current += 1;

			const restored: Array<ChatMessage> = conversation.messages.map(
				(message) =>
					message.role === "user"
						? { id: nextId.current++, role: "user", text: message.text }
						: message.role === "game"
							? {
									id: nextId.current++,
									role: "game" as const,
									gameType: message.gameType,
								}
							: message.role === "eligibility"
								? { id: nextId.current++, role: "eligibility" as const }
								: {
										id: nextId.current++,
										role: "assistant",
										blocks: message.blocks,
										followUps: message.followUps,
										sources: message.sources,
									},
			);

			// A conversation whose last stored turn is the question is one whose
			// first send failed: the chat was committed the moment it was sent, so
			// it is in the sidebar, but no answer ever arrived to go under it.
			// Reopening it used to show the question alone, with nothing to say
			// what happened and no way to ask again — a committed chat with no
			// route out, which is exactly what must not exist. This puts the retry
			// back. `regenerate` walks up to the nearest user turn, which is the
			// orphaned question, so the button re-asks the right thing.
			if (conversation.messages.at(-1)?.role === "user") {
				restored.push({
					id: nextId.current++,
					role: "error",
					text: "This question never got an answer.",
					canRetry: true,
				});
			}

			const lastUser = [...conversation.messages]
				.reverse()
				.find((m) => m.role === "user");
			lastQuestion.current = lastUser?.role === "user" ? lastUser.text : "";

			threadRef.current = conversation.threadId;
			setThreadId(conversation.threadId);
			setPhase("chat");
			setIsThinking(false);
			setMessages(restored);
			// Everything just restored is older than this, so none of it animates.
			// The next message sent will be.
			setAnimateAfterId(nextId.current);
		},
		[dropStream, abortInFlight],
	);

	const reset = useCallback(() => {
		abortInFlight();
		dropStream();
		lastQuestion.current = "";
		turnToken.current += 1;
		threadRef.current = null;
		setThreadId(null);
		setPhase("landing");
		setMessages([]);
		setIsThinking(false);
	}, [dropStream, abortInFlight]);

	// Follow-ups belong to the answer that has settled — never to one still
	// being revealed, where they would appear before the text they follow.
	const tail = messages.at(-1);
	const followUps =
		!streaming && tail?.role === "assistant" ? tail.followUps : [];

	return {
		phase,
		messages,
		streaming,
		isThinking,
		followUps,
		history,
		threadId,
		animateAfterId,
		send,
		regenerate,
		stop,
		openPast,
		reset,
		renameChat,
		regenerateTitle,
	};
}
