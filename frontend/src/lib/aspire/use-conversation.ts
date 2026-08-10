import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import type {
	Directive,
	GameResultPayload,
	UploadResult,
	WidgetInteraction,
} from "../stream/types";
import { type AskResult, AspireError, type Source } from "./api";
import {
	claimConversations,
	deleteConversation,
	HttpError,
	renameConversation,
} from "./conversations";
import {
	forgetLocalConversation,
	loadConversations,
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
import {
	clearTitleLockInCache,
	conversationQuery,
	conversationsQuery,
	keys,
	readConversation,
	removeConversationFromCache,
	retitleInCache,
	titleSnapshot,
	upsertConversation,
} from "./queries";
import { ensureSession } from "./session";
import { blockIsClosed, settledBlocks } from "./settled";
import { streamAspire } from "./stream";
import { requestTitle } from "./title";
import { useSession } from "./use-session";

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
			/** "stopped" is the reader's own decision, not a fault, and is drawn accordingly — the same reason a wrong game… */
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

export type Phase = "landing" | "chat";

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
	return block.items.reduce(
		(total, item) => total + (item ? item.split(" ").length : 0),
		0,
	);
}

/** A block cut to its first `words` words. */
function sliceBlock(block: AnswerBlock, words: number): AnswerBlock {
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

/** Mints the id for a conversation, in the browser, before anything is sent. */
function newThreadId(): string {
	const uuid = globalThis.crypto?.randomUUID?.();
	if (uuid) return uuid;
	return `t-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** What to call a conversation that opened with a game. */
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
	/** Fired the moment a reply lands, with the whole text — before the typewriter starts revealing it. */
	onAnswer?: (id: number, text: string) => void;
	/** Who is talking. Null means unknown, which the service treats as permissive. */
	persona?: string | null;
	/** Fired synchronously inside `send`, the instant a conversation is minted. */
	onThreadStart?: (threadId: string) => void;
	/** Fired when a turn started a game instead of answering. Carries the directive's game name and concept. */
	onGameStart?: (threadId: string, gameType: string, concept: string) => void;
	/** Fired when a turn opened the eligibility check instead of answering. */
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

	// Subscribed to the session, so a sign-in or sign-out re-renders this and the query picks up the new owner's ke…
	const { session } = useSession();
	const [threadId, setThreadId] = useState<string | null>(null);

	/** What this hook needs from the conversation list, and nothing more. */
	const ownerId = session?.userId ?? "anon";
	// Drives the layout: whether there is anything for the rail to offer at all.
	const { data: hasHistory = false } = useQuery({
		...conversationsQuery(ownerId),
		select: (rows) => rows.length > 0,
	});
	/** The open conversation's stored name, as the title bar's change trigger. */
	const { data: activeStoredTitle } = useQuery({
		...conversationsQuery(ownerId),
		select: (rows) => rows.find((row) => row.threadId === threadId)?.title,
	});
	/** The oldest message id allowed to play its entry animation. */
	const [animateAfterId, setAnimateAfterId] = useState(0);

	const nextId = useRef(0);
	const streamTimer = useRef<ReturnType<typeof setInterval>>(undefined);
	const cursor = useRef<StreamCursor | undefined>(undefined);
	/** Last question asked, so "Try again" can re-ask it. */
	const lastQuestion = useRef("");
	/** Guards against a reply from an abandoned turn landing in the transcript — "New chat" or a second question whi… */
	const turnToken = useRef(0);
	/** Cancels the request behind the turn in flight. */
	const inFlight = useRef<AbortController | null>(null);

	/** Ends the request in flight, if there is one. Safe to call twice. */
	const abortInFlight = useCallback(() => {
		inFlight.current?.abort();
		inFlight.current = null;
	}, []);
	/** Threads this session has already tried to name. */
	const titledThreads = useRef(new Set<string>());
	/** Mirrors `isThinking` for the in-flight guard in `send`. */
	const isThinkingRef = useRef(false);
	// Held in a ref so a changing callback never re-creates the send pipeline.
	const onAnswerRef = useRef(onAnswer);
	useEffect(() => {
		onAnswerRef.current = onAnswer;
	}, [onAnswer]);

	// Same reason as onAnswer: the voice layer is created after this hook (it needs the thread id this hook owns),…
	const getLanguageRef = useRef(getLanguage);
	useEffect(() => {
		getLanguageRef.current = getLanguage;
	}, [getLanguage]);

	// Same again: `send` has to stay stable, and the shell's navigate callback is not.
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

	/** The thread the next request belongs to, readable synchronously. */
	const threadRef = useRef<string | null>(null);

	// Commits before any later click can be dispatched, so the guard in `send` never reads a stale value.
	useEffect(() => {
		isThinkingRef.current = isThinking;
	}, [isThinking]);

	/** Adopt the conversations this browser started before ownership existed. */
	// biome-ignore lint/correctness/useExhaustiveDependencies: once, on mount
	useEffect(() => {
		// An identity first, because everything user-scoped is gated on having one.
		void ensureSession()
			.then(async (session) => {
				if (!session) return;
				// The queries were disabled while there was no session.
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

	/** Names a conversation, in the cache and on the server. */
	const renameMutation = useMutation({
		mutationFn: ({
			id,
			title,
			source,
		}: {
			id: string;
			title: string;
			source: "generated" | "manual";
		}) => renameConversation(id, title, source),
		onMutate: ({ id, title, source }) => {
			const previous = titleSnapshot(queryClient, id);
			retitleInCache(queryClient, id, title, source);
			return { id, previous };
		},
		onError: (_error, _variables, context) => {
			if (!context) return;
			retitleInCache(
				queryClient,
				context.id,
				context.previous.title,
				context.previous.titleSource,
			);
		},
		// Runs on success and on failure alike.
		onSettled: () =>
			queryClient.invalidateQueries({ queryKey: keys.allConversations() }),
	});

	// Still fire-and-forget at the call sites, and deliberately so: a name that fails to save is worth strictly les…
	const nameConversation = useCallback(
		(id: string, title: string, source: "generated" | "manual") => {
			renameMutation.mutate({ id, title, source });
		},
		[renameMutation.mutate],
	);

	/** Deletes a conversation, for good. */
	const deleteMutation = useMutation({
		mutationFn: (id: string) => deleteConversation(id),
		onMutate: (id: string) => ({
			removed: removeConversationFromCache(queryClient, id),
		}),
		onSuccess: (_result, id) => {
			// The device-local copy, which nothing writes any more but which still holds whole transcripts from before hist…
			forgetLocalConversation(id);
		},
		onError: (error, _id, context) => {
			if (error instanceof HttpError && error.status === 404) return;
			if (context?.removed) upsertConversation(queryClient, context.removed);
		},
		// Ordering after a rollback comes from here rather than from the restore: `upsertConversation` puts a row at th…
		onSettled: () =>
			queryClient.invalidateQueries({ queryKey: keys.allConversations() }),
	});

	/** Deletes one conversation. */
	const deleteChat = useCallback(
		(id: string) => {
			deleteMutation.mutate(id);
		},
		[deleteMutation.mutate],
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

			// Reduced motion still skips the reveal, but only once the answer is whole -- settling a half-delivered stream…
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
				// Only ever grows, and only over settled text, so `built` indices stay valid and the reveal is never rewound.
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
					if (named && !titledThreads.current.has(result.threadId)) {
						titledThreads.current.add(result.threadId);
						nameConversation(result.threadId, named, "generated");
					}

					onGameStartRef.current?.(
						result.threadId,
						result.startedGame.gameType,
						result.startedGame.concept,
					);
					return;
				}

				// An eligibility turn is the card and nothing else, for the same reason and by the same mechanism as a game tur…
				if (result.startedEligibility) {
					setIsThinking(false);
					setMessages((current) => [
						...current,
						{ id: nextId.current++, role: "eligibility" },
					]);

					// Name the chat now, while we know what it is.
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

				// The payload is authoritative, not the accumulated deltas: on a card turn the service deliberately sends an em…
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
					// Nothing was ever revealed -- a reply with no newline in it, or the non-streaming fallback inside `streamAspir…
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
					// Read at call time for the same reason the title call does: the voice layer that owns this setting is built af…
					language: getLanguageRef.current(),
				});

				// Usually a no-op by now: `onTurn` settled this when the service announced the turn, which on a streamed reply…
				settleTurn(result);
				applyFollowUps(result.followUps);
			} catch (error) {
				if (turnToken.current !== token) return;

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
		// `nameConversation`, `queryClient` and `settleRevealed` are all stable references, so naming them here does no…
		[beginStream, persona, nameConversation, settleRevealed],
	);

	const send = useCallback(
		(raw: string, simpleMode = false) => {
			const text = raw.trim();
			if (!text) return;
			// A second question while the first is still in flight used to bump the turn token, so the first reply was disc…
			if (isThinkingRef.current || cursor.current) return;

			dropStream();
			lastQuestion.current = text;
			const token = ++turnToken.current;

			// The first message of a conversation is the moment it becomes real: it gets an id, an address, and a row in th…
			const opening = !threadRef.current;
			if (opening) {
				const minted = newThreadId();
				threadRef.current = minted;
				setThreadId(minted);

				// Committed now, not when the answer settles.
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

	/** Re-asks the question behind one specific answer, replacing that answer. */
	const regenerate = useCallback(
		(messageId: number, simpleMode = false) => {
			const index = messages.findIndex((m) => m.id === messageId);
			if (index === -1) return;

			// The question this answer came from is the nearest user turn above it, not the newest one in the transcript.
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

			// Re-found inside the updater so a turn that settled between the click and this point cannot make the index cut…
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

		// Keep whatever is already on screen — the words are there to be read, and deleting them as you read is its own…
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

		// Whatever this conversation is already called wins over a fresh truncation: a generated or hand-typed title mu…
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
		if (!threadId || titledThreads.current.has(threadId)) return;

		const tail = messages.at(-1);
		if (tail?.role !== "assistant") return;

		const firstQuestion = messages.find((m) => m.role === "user");
		if (firstQuestion?.role !== "user") return;

		// Only the opening exchange names the chat, so a conversation that already has more than one answer was restore…
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
			// Null means the service declined — a greeting, gibberish, or a failed call.
			if (!title) return;
			nameConversation(threadId, title, "generated");
		});
	}, [messages, threadId, queryClient, nameConversation]);

	/** Renames a conversation by hand. */
	const renameChat = useCallback(
		(id: string, title: string) => {
			titledThreads.current.add(id);
			nameConversation(id, title, "manual");
		},
		[nameConversation],
	);

	/** Asks for a fresh title for one conversation. */
	const regenerateTitle = useCallback(
		(id: string) => {
			// The rail's rows carry no transcripts, so the opening exchange is fetched rather than read off the row.
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

			// A conversation whose last stored turn is the question is one whose first send failed: the chat was committed…
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

	// Follow-ups belong to the answer that has settled — never to one still being revealed, where they would appear…
	const tail = messages.at(-1);
	const followUps =
		!streaming && tail?.role === "assistant" ? tail.followUps : [];

	return {
		phase,
		messages,
		streaming,
		isThinking,
		followUps,
		hasHistory,
		activeStoredTitle,
		threadId,
		animateAfterId,
		send,
		sendInteraction,
		sendUploadResult,
		sendGameResult,
		regenerate,
		stop,
		openPast,
		reset,
		renameChat,
		regenerateTitle,
		deleteChat,
	};
}
