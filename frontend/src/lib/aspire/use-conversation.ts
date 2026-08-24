import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import type {
	Directive,
	GameResultPayload,
	UploadResult,
	WidgetInteraction,
} from "../stream/types";
import { type AskResult, AspireError, type Source } from "./api";
import { gameTitleFor } from "./game-kinds";
import {
	type StoredConversation,
	type StoredMessage,
	titleFor,
} from "./history";
import {
	type Answer,
	type AnswerBlock,
	answerToText,
	parseAnswer,
} from "./knowledge";
import { readConversation, upsertConversation } from "./queries";
import { blockIsClosed, settledBlocks } from "./settled";
import { streamAspire } from "./stream";
import { requestTitle } from "./title";
import { useConversationList } from "./use-conversation-list";

export type ChatMessage =
	| { id: number; role: "user"; text: string }
	| {
			id: number;
			role: "assistant";
			blocks: Array<AnswerBlock>;
			followUps: Array<string>;
			sources: Array<Source>;
			/** Rendered under the prose by `DirectiveView`, in the order the turn emitted them. */
			directives?: Array<Directive>;
	  }
	/** A turn that started a game. */
	| { id: number; role: "game"; gameType: string }
	/** A turn that opened the eligibility check. */
	| { id: number; role: "eligibility" }
	| {
			id: number;
			role: "error";
			text: string;
			canRetry: boolean;
			/** "stopped" is the reader's own choice, not a fault, and is drawn accordingly. */
			tone?: "stopped";
	  };

/** The answer currently being revealed, held apart from `messages`. */
export interface StreamingAnswer {
	id: number;
	blocks: Array<AnswerBlock>;
	/** The finished answer's evidence and suggestions, carried from the first tick. */
	sources: Array<Source>;
	followUps: Array<string>;
}

/** Pacing of the typewriter reveal. Tuned to read as thinking, not as lag. */
const TICK_MS = 40;

/** How the reveal decides how much to draw, and why it is not a constant. */
const SMOOTH_TICKS = 8;
/** Words per tick, floor and ceiling. */
const MIN_RATE = 0.3;
const MAX_RATE = 5;
/** The same, once the turn is over. */
const MIN_RATE_ENDED = 2.5;
const MAX_RATE_ENDED = 8;

/** Words in a block. Lists count every word of every item, not the items. */
function blockWords(block: AnswerBlock): number {
	if (block.kind === "paragraph")
		return block.text ? block.text.split(" ").length : 0;
	// A table reveals whole -- a half-drawn grid is unreadable -- so it counts
	// as one word to the pacer and is never sliced.
	if (block.kind === "table") return 1;
	return block.items.reduce(
		(total, item) => total + (item ? item.split(" ").length : 0),
		0,
	);
}

/** A block cut to its first `words` words. */
function sliceBlock(block: AnswerBlock, words: number): AnswerBlock {
	// Atomic: it has no words to slice, and appears whole once revealed at all.
	if (block.kind === "table") return block;
	if (block.kind === "paragraph") {
		return {
			kind: "paragraph",
			text: block.text.split(" ").slice(0, words).join(" "),
		};
	}

	const items: Array<string> = [];
	let left = words;
	for (const item of block.items) {
		if (left <= 0) break;
		const parts = item.split(" ");
		items.push(left >= parts.length ? item : parts.slice(0, left).join(" "));
		left -= parts.length;
	}
	return { kind: "list", items, ordered: block.ordered };
}

interface StreamCursor {
	/** The answer as far as it is known, reparsed as more of it arrives. */
	answer: Answer;
	sources: Array<Source>;
	id: number;
	/** Whether the service has said the turn is over. */
	ended: boolean;
	/** Whether the prose is final, which happens earlier. */
	textEnded: boolean;
	blockIndex: number;
	/** Words revealed within the current block. */
	wordIndex: number;
	/** Fractional words carried between ticks. */
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

/** What to call a conversation that opened with a game. See `game-kinds`. */
function gameTitle(gameType: string, language: string): string | null {
	return gameTitleFor(gameType, language);
}

/** What to call a conversation that opened with the eligibility check. */
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
		directives: answer.directives,
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
	/** Which language to name the conversation in. */
	getLanguage?: () => string;
	/** False when the reader has pinned a language. Read at call time, like `getLanguage`. */
	getAutoLanguage?: () => boolean;
	/** Fired the moment a reply lands, with the whole text, before the reveal starts. */
	onAnswer?: (id: number, text: string) => void;
	/** Who is talking. Null means unknown, which the service treats as permissive. */
	persona?: string | null;
	/**
	 * Which of the persona's own bands to answer at.
	 *
	 * Skye and Kaleb are both `stella`; this is the only thing that tells them
	 * apart, so without it the picker offers Kaleb and the turn answers as Skye.
	 */
	band?: string | null;
	/** Fired when a turn started a game instead of answering; carries game name and concept. */
	onGameStart?: (threadId: string, gameType: string, concept: string) => void;
	/** Fired when a turn opened the eligibility check instead of answering. */
	onEligibilityStart?: (threadId: string, language: string) => void;
}

export function useConversation({
	onAnswer,
	persona = null,
	band = null,
	getLanguage = () => "en",
	getAutoLanguage = () => true,
	onGameStart,
	onEligibilityStart,
}: UseConversationOptions = {}) {
	const [messages, setMessages] = useState<Array<ChatMessage>>([]);
	const [streaming, setStreaming] = useState<StreamingAnswer | null>(null);
	const [isThinking, setIsThinking] = useState(false);
	const queryClient = useQueryClient();

	const [threadId, setThreadId] = useState<string | null>(null);

	/** The rail's list and its row actions, which the landing page shares. */
	const {
		hasHistory,
		activeStoredTitle,
		nameConversation,
		markTitled,
		hasTitled,
		renameChat,
		regenerateTitle,
		deleteChat,
	} = useConversationList({ activeThreadId: threadId, getLanguage });
	/** The oldest message id allowed to play its entry animation. */
	const [animateAfterId, setAnimateAfterId] = useState(0);

	const nextId = useRef(0);
	const streamTimer = useRef<ReturnType<typeof setInterval>>(undefined);
	const cursor = useRef<StreamCursor | undefined>(undefined);
	/** Last question asked, so "Try again" can re-ask it. */
	const lastQuestion = useRef("");
	/** Drops replies from a turn the reader abandoned. */
	const turnToken = useRef(0);
	/** Cancels the request behind the turn in flight. */
	const inFlight = useRef<AbortController | null>(null);

	/** Ends the request in flight, if there is one. Safe to call twice. */
	const abortInFlight = useCallback(() => {
		inFlight.current?.abort();
		inFlight.current = null;
	}, []);
	/** Mirrors `isThinking` for the in-flight guard in `send`. */
	const isThinkingRef = useRef(false);
	// Held in a ref so a changing callback never re-creates the send pipeline.
	const onAnswerRef = useRef(onAnswer);
	useEffect(() => {
		onAnswerRef.current = onAnswer;
	}, [onAnswer]);

	// Same reason as onAnswer: the voice layer is created after this hook.
	const getAutoLanguageRef = useRef(getAutoLanguage);
	useEffect(() => {
		getAutoLanguageRef.current = getAutoLanguage;
	}, [getAutoLanguage]);

	const getLanguageRef = useRef(getLanguage);
	useEffect(() => {
		getLanguageRef.current = getLanguage;
	}, [getLanguage]);

	const onGameStartRef = useRef(onGameStart);
	useEffect(() => {
		onGameStartRef.current = onGameStart;
	}, [onGameStart]);

	const onEligibilityStartRef = useRef(onEligibilityStart);
	useEffect(() => {
		onEligibilityStartRef.current = onEligibilityStart;
	}, [onEligibilityStart]);

	/** The thread the next request belongs to, readable synchronously. */
	const threadRef = useRef<string | null>(null);

	// Commits before any later click, so the guard in `send` never reads a stale value.
	useEffect(() => {
		isThinkingRef.current = isThinking;
	}, [isThinking]);

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

	// Leaving the page is the clearest possible signal that nobody is waiting for this answer.
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

	/** Settles only what has actually been revealed. */
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

	/**
	 * Lets go of a reveal whose turn has been superseded.
	 *
	 * Only ever its own: `cursor.current` may already belong to a newer turn,
	 * and there is a single `streamTimer` behind all of them, so settling the
	 * wrong one stops the reveal that is legitimately running.
	 */
	const releaseAbandoned = useCallback(
		(streamingId: number) => {
			const live = cursor.current;
			if (live && live.id === streamingId) settleRevealed();
		},
		[settleRevealed],
	);

	const tick = useCallback(() => {
		const state = cursor.current;
		if (!state) return;

		const pending = pendingWords(state);
		if (pending === 0) {
			// Caught up.
			if (state.ended) finishStream();
			return;
		}

		state.credit += paceFor(pending, state.textEnded);
		const budget = Math.floor(state.credit);
		// Less than a whole word owed.
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
			// This block is fully drawn.
			if (
				!blockIsClosed(state.blockIndex, state.answer.blocks, state.textEnded)
			)
				break;
			state.blockIndex += 1;
			state.wordIndex = 0;
		}

		setStreaming({
			id: state.id,
			blocks: [...state.built],
			sources: state.sources,
			followUps: state.answer.followUps,
			// No directives.
		});
	}, [finishStream]);

	/** Starts revealing an answer. */
	const beginStream = useCallback(
		(answer: Answer, sources: Array<Source>, ended = true) => {
			setIsThinking(false);
			const id = nextId.current++;

			// Reduced motion skips the reveal, but only once the answer is whole.
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

	/** Asks the service and reveals the reply. */
	const ask = useCallback(
		async (
			question: string,
			simpleMode: boolean,
			token: number,
			interaction?: WidgetInteraction,
			uploadResult?: UploadResult,
			gameResult?: GameResultPayload,
			/**
			 * The language to ask in, when the caller knows it better than the
			 * voice layer does. It reads its stored preference in an effect, so
			 * on this page's first tick it still says "en" — and the handoff's
			 * first turn happens inside exactly that tick.
			 */
			language?: string,
		) => {
			const controller = new AbortController();
			inFlight.current?.abort(); // a previous turn should never outlive this one
			inFlight.current = controller;
			/** Feeds the reveal from the wire, without letting the wire pace it. */
			let buffer = "";
			let streamingId = -1;
			const onDelta = (delta: string) => {
				if (turnToken.current !== token) return;
				buffer += delta;

				const blocks = settledBlocks(buffer, false);
				if (streamingId === -1) {
					// Nothing settles until the first newline lands, which on a real reply is one line.
					if (blocks.length === 0) return;
					streamingId = beginStream({ blocks, followUps: [] }, [], false);
					return;
				}

				const state = cursor.current;
				if (!state) return;
				// Only grows, over settled text: `built` indices stay valid and the reveal never rewinds.
				state.answer = { ...state.answer, blocks };
			};

			/** The model has stopped writing. */
			const onTextEnd = () => {
				if (turnToken.current !== token) return;
				const state = cursor.current;
				if (!state) return;
				state.answer = { ...state.answer, blocks: settledBlocks(buffer, true) };
				state.textEnded = true;
			};

			/** Everything that happens once the service has said what the turn is. */
			let settled = false;
			const settleTurn = (result: AskResult) => {
				if (settled) return;
				settled = true;
				if (turnToken.current !== token) return; // the turn was abandoned

				// Adopt the server's id only when we had none to begin with.
				if (!threadRef.current) {
					threadRef.current = result.threadId;
					setThreadId(result.threadId);
				}

				// A game turn is the card and nothing else.
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

					// Name the chat now, while we know what it is.
					const named = gameTitle(
						result.startedGame.gameType,
						getLanguageRef.current(),
					);
					if (named && !hasTitled(result.threadId)) {
						markTitled(result.threadId);
						nameConversation(result.threadId, named, "generated");
					}

					onGameStartRef.current?.(
						result.threadId,
						result.startedGame.gameType,
						result.startedGame.concept,
					);
					return;
				}

				// An eligibility turn is the card and nothing else, exactly like a game turn.
				if (result.startedEligibility) {
					setIsThinking(false);
					setMessages((current) => [
						...current,
						{ id: nextId.current++, role: "eligibility" },
					]);

					// Name the chat now, while we know what it is.
					const named = eligibilityTitle(result.startedEligibility.language);
					if (!hasTitled(result.threadId)) {
						markTitled(result.threadId);
						nameConversation(result.threadId, named, "generated");
					}

					onEligibilityStartRef.current?.(
						result.threadId,
						result.startedEligibility.language,
					);
					return;
				}

				// The payload wins over the deltas: a card turn deliberately sends empty prose.
				const finalAnswer: Answer = {
					blocks: parseAnswer(result.reply),
					followUps: result.followUps,
					directives: result.directives,
				};

				const live = cursor.current;
				if (live && live.id === streamingId) {
					// A reveal is already running.
					live.answer = finalAnswer;
					live.sources = result.sources;
					live.ended = true;
					// Usually already true, from `TEXT_MESSAGE_END`.
					live.textEnded = true;
				} else {
					// Nothing was revealed: a reply with no newline, or the non-streaming fallback.
					streamingId = beginStream(finalAnswer, result.sources, true);
				}
				onAnswerRef.current?.(streamingId, result.reply);
			};

			/** The chips, which arrive after the turn has already settled. */
			const applyFollowUps = (followUps: Array<string>) => {
				if (turnToken.current !== token || followUps.length === 0) return;

				const live = cursor.current;
				if (live && live.id === streamingId) {
					live.answer = { ...live.answer, followUps };
					return;
				}

				setMessages((current) =>
					current.map((message) =>
						message.id === streamingId && message.role === "assistant"
							? { ...message, followUps }
							: message,
					),
				);
			};

			try {
				const result: AskResult = await streamAspire({
					message: question,
					// Present only on a widget turn.
					interaction,
					// Present only on the turn that answers a paused upload.
					uploadResult,
					// Present only on the turn that reports a finished game.
					gameResult,
					onDelta,
					onTextEnd,
					onTurn: settleTurn,
					signal: controller.signal,
					// Read now, not closed over: see `threadRef`.
					threadId: threadRef.current,
					simpleMode,
					persona,
					band,
					// Read at call time: the voice layer is built after this hook.
					language: language ?? getLanguageRef.current(),
					autoLanguage: getAutoLanguageRef.current(),
				});

				if (turnToken.current !== token) {
					// Abandoned while it was still being revealed. `settleTurn` latches
					// before it checks the token, so `ended` was never set on this
					// cursor and `tick` will spin at `pending === 0` forever. Nothing
					// else will clear it either: `sendUploadResult` and
					// `sendGameResult` bump the token WITHOUT the `cursor.current`
					// guard the other turn-starters have. The reader is then locked
					// out for good -- the composer stays on Stop generating and `send`
					// is refused by that same guard, which is what a registration that
					// paused on a document upload actually did.
					//
					// `id === streamingId` keeps this to OUR cursor: if a newer turn
					// has already begun revealing, it owns both the cursor and the
					// single `streamTimer`, and clearing those here would freeze it.
					releaseAbandoned(streamingId);
					return;
				}

				// Usually a no-op: `onTurn` already settled this when the turn was announced.
				settleTurn(result);
				applyFollowUps(result.followUps);
			} catch (error) {
				if (turnToken.current !== token) {
					releaseAbandoned(streamingId);
					return;
				}

				// A reveal may still be running against a stream that has died.
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
		// `nameConversation` and `settleRevealed` are stable, so listing them costs no rebuilds.
		[
			beginStream,
			persona,
			band,
			nameConversation,
			releaseAbandoned,
			settleRevealed,
			hasTitled,
			markTitled,
		],
	);

	/** Puts the question on screen and starts the turn. The thread must exist. */
	const dispatch = useCallback(
		(text: string, simpleMode: boolean, language?: string) => {
			dropStream();
			lastQuestion.current = text;
			const token = ++turnToken.current;

			setIsThinking(true);
			setMessages((current) => [
				...current,
				{ id: nextId.current++, role: "user", text },
			]);

			void ask(
				text,
				simpleMode,
				token,
				undefined,
				undefined,
				undefined,
				language,
			);
		},
		[ask, dropStream],
	);

	/**
	 * Returns whether the question was accepted.
	 *
	 * It returned nothing, and the composer cleared the box on every call — so
	 * a question typed while a reply was still streaming, or before the thread
	 * had an id, was silently deleted. The reader watched their own sentence
	 * vanish and had to retype it from memory. The three guarded exits below
	 * are the three ways that happened.
	 */
	const send = useCallback(
		(raw: string, simpleMode = false): boolean => {
			const text = raw.trim();
			if (!text) return false;
			// Ignore a second question while one is in flight, rather than discarding the first reply.
			if (isThinkingRef.current || cursor.current) return false;
			// Conversations are opened at `/`, which mints the id; this hook only continues them.
			if (!threadRef.current) return false;

			dispatch(text, simpleMode);
			return true;
		},
		[dispatch],
	);

	/**
	 * Take up an id the caller minted, without sending anything into it.
	 *
	 * `send` refuses when `threadRef` is empty -- "this hook only continues
	 * conversations" -- and that ref is set in exactly three places: a reply
	 * coming back, `resumeFirstTurn`, and opening a past conversation. A guide
	 * card opens an EMPTY conversation, so it reaches none of them, and every
	 * later send returns at that guard. Silently: no error, no request, no
	 * state change. The composer accepts the text and nothing happens to it.
	 *
	 * So the conversation has to be adopted at the point the reader enters it.
	 * Unconditional, like `openPast`: the caller names the thread it is opening,
	 * and a ref still holding the previous one is the case this has to fix.
	 */
	const adoptThread = useCallback((id: string) => {
		threadRef.current = id;
		setThreadId(id);
	}, []);

	/**
	 * Sends the question the landing page staged, into the conversation it
	 * already minted and committed. The user's message is appended here and
	 * nowhere else, which is why the chat page must take the pending turn
	 * before it reads the cache.
	 */
	const resumeFirstTurn = useCallback(
		(id: string, question: string, simpleMode: boolean, language: string) => {
			const text = question.trim();
			if (!text) return;
			if (isThinkingRef.current || cursor.current) return;

			threadRef.current = id;
			setThreadId(id);
			dispatch(text, simpleMode, language);
		},
		[dispatch],
	);

	/** Re-asks the question behind one specific answer, replacing that answer. */
	const regenerate = useCallback(
		(messageId: number, simpleMode = false) => {
			const index = messages.findIndex((m) => m.id === messageId);
			if (index === -1) return;

			// The question is the nearest user turn above this answer, not the newest one.
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

			// Re-found inside the updater: a turn settling since the click would shift the index.
			setMessages((current) => {
				const at = current.findIndex((m) => m.id === messageId);
				return at === -1 ? current : current.slice(0, at);
			});
			setIsThinking(true);

			void ask(question, simpleMode, token);
		},
		[ask, dropStream, messages],
	);

	/** Abandons the turn in flight. */
	const stop = useCallback(() => {
		turnToken.current += 1;
		// The half that was missing. Without this, Stop only hid the answer.
		abortInFlight();

		// Keep whatever is already on screen: those words are there to be read.
		if (cursor.current) settleRevealed();
		setIsThinking(false);

		// Then say what happened, in both branches.
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

	/** Keep the rail's row in step with the exchange that just settled. */
	useEffect(() => {
		if (!threadId) return;

		const tail = messages.at(-1);
		// A game or eligibility turn settles the exchange just as an answer does.
		if (
			tail?.role !== "assistant" &&
			tail?.role !== "game" &&
			tail?.role !== "eligibility"
		)
			return;

		const firstQuestion = messages.find((m) => m.role === "user");
		if (firstQuestion?.role !== "user") return;

		// An existing title beats a fresh truncation: generated and manual names must survive.
		const existing = readConversation(queryClient, threadId);

		upsertConversation(queryClient, {
			threadId,
			title: existing?.title || titleFor(firstQuestion.text),
			titleSource: existing?.titleSource,
			updatedAt: Date.now(),
			messages: toStored(messages),
		});
	}, [messages, threadId, queryClient]);

	/** Name the conversation, once, after its first answer has landed. */
	useEffect(() => {
		if (!threadId || hasTitled(threadId)) return;

		const tail = messages.at(-1);
		if (tail?.role !== "assistant") return;

		const firstQuestion = messages.find((m) => m.role === "user");
		if (firstQuestion?.role !== "user") return;

		// Only the opening exchange names the chat; more than one answer means it was restored.
		const answers = messages.filter((m) => m.role === "assistant");
		if (answers.length !== 1) return;

		const stored = readConversation(queryClient, threadId);
		if (stored?.titleSource) return; // already named, or named by hand

		markTitled(threadId);

		void requestTitle({
			message: firstQuestion.text,
			answer: answerToText(tail.blocks),
			language: getLanguageRef.current(),
		}).then((title) => {
			// Null means the service declined — a greeting, gibberish, or a failed call.
			if (!title) return;
			nameConversation(threadId, title, "generated");
		});
	}, [
		messages,
		threadId,
		queryClient,
		nameConversation,
		hasTitled,
		markTitled,
	]);

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

			// A transcript ending on the question means the first send failed after the commit.
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
			setIsThinking(false);
			setMessages(restored);
			// Everything just restored is older than this, so none of it animates.
			setAnimateAfterId(nextId.current);
		},
		[dropStream, abortInFlight],
	);

	/** A widget interaction, sent as a turn. */
	const sendInteraction = useCallback(
		(interaction: WidgetInteraction) => {
			if (isThinkingRef.current || cursor.current) return;
			if (!threadRef.current) return;
			const token = ++turnToken.current;
			setIsThinking(true);
			void ask("", false, token, interaction);
		},
		[ask],
	);

	/** Continue a registration that is paused on a document. */
	const sendUploadResult = useCallback(
		(uploadResult: UploadResult) => {
			if (!threadRef.current) return;
			const token = ++turnToken.current;
			setIsThinking(true);
			void ask("", false, token, undefined, uploadResult);
		},
		[ask],
	);

	/** A finished game's score, sent as a turn. */
	const sendGameResult = useCallback(
		(gameResult: GameResultPayload) => {
			if (!threadRef.current) return;
			const token = ++turnToken.current;
			setIsThinking(true);
			void ask("", false, token, undefined, undefined, gameResult);
		},
		[ask],
	);

	// Follow-ups belong to the settled answer, never to one still being revealed.
	const tail = messages.at(-1);
	const followUps =
		!streaming && tail?.role === "assistant" ? tail.followUps : [];

	return {
		adoptThread,
		messages,
		streaming,
		isThinking,
		followUps,
		hasHistory,
		activeStoredTitle,
		threadId,
		animateAfterId,
		send,
		resumeFirstTurn,
		sendInteraction,
		sendUploadResult,
		sendGameResult,
		regenerate,
		stop,
		openPast,
		renameChat,
		regenerateTitle,
		deleteChat,
	};
}
