import { useCallback, useEffect, useRef, useState } from "react";
import { type AskResult, AspireError, askAspire, type Source } from "./api";
import {
	groupByRecency,
	type HistoryGroup,
	loadConversations,
	type StoredConversation,
	type StoredMessage,
	saveConversation,
	titleFor,
} from "./history";
import { type Answer, type AnswerBlock, parseAnswer } from "./knowledge";

export type ChatMessage =
	| { id: number; role: "user"; text: string }
	| {
			id: number;
			role: "assistant";
			blocks: Array<AnswerBlock>;
			followUps: Array<string>;
			sources: Array<Source>;
	  }
	| { id: number; role: "error"; text: string; canRetry: boolean };

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
}

export type Phase = "landing" | "chat";

/** Pacing of the typewriter reveal. Tuned to read as thinking, not as lag. */
const TICK_MS = 40;
const WORDS_PER_TICK = 4;
/** Ticks between list items — bullets land slower than prose reads. */
const TICKS_PER_ITEM = 3;

interface StreamCursor {
	answer: Answer;
	sources: Array<Source>;
	id: number;
	blockIndex: number;
	wordIndex: number;
	holdTicks: number;
	built: Array<AnswerBlock>;
}

function prefersReducedMotion() {
	return (
		typeof window !== "undefined" &&
		window.matchMedia("(prefers-reduced-motion: reduce)").matches
	);
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
	 * Fired the moment a reply lands, with the whole text — before the
	 * typewriter starts revealing it. Read-aloud uses this so audio begins as
	 * the answer arrives rather than after it has finished being drawn.
	 */
	onAnswer?: (id: number, text: string) => void;
	/** Who is talking. Null means unknown, which the service treats as permissive. */
	persona?: string | null;
}

export function useConversation({
	onAnswer,
	persona = null,
}: UseConversationOptions = {}) {
	const [phase, setPhase] = useState<Phase>("landing");
	const [messages, setMessages] = useState<Array<ChatMessage>>([]);
	const [streaming, setStreaming] = useState<StreamingAnswer | null>(null);
	const [isThinking, setIsThinking] = useState(false);
	const [history, setHistory] = useState<Array<HistoryGroup>>([]);
	const [threadId, setThreadId] = useState<string | null>(null);

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
	// Held in a ref so a changing callback never re-creates the send pipeline.
	const onAnswerRef = useRef(onAnswer);
	useEffect(() => {
		onAnswerRef.current = onAnswer;
	}, [onAnswer]);

	// localStorage is unavailable during SSR, so history loads after mount.
	useEffect(() => setHistory(groupByRecency(loadConversations())), []);

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

	const tick = useCallback(() => {
		const state = cursor.current;
		if (!state) return;

		const block = state.answer.blocks[state.blockIndex];
		if (!block) {
			finishStream();
			return;
		}

		if (block.kind === "paragraph") {
			const words = block.text.split(" ");
			state.wordIndex = Math.min(
				words.length,
				state.wordIndex + WORDS_PER_TICK,
			);
			state.built[state.blockIndex] = {
				kind: "paragraph",
				text: words.slice(0, state.wordIndex).join(" "),
			};
			if (state.wordIndex >= words.length) {
				state.blockIndex += 1;
				state.wordIndex = 0;
			}
		} else {
			state.built[state.blockIndex] ??= { kind: "list", items: [] };
			state.holdTicks += 1;
			if (state.holdTicks >= TICKS_PER_ITEM) {
				state.holdTicks = 0;
				state.wordIndex = Math.min(block.items.length, state.wordIndex + 1);
				state.built[state.blockIndex] = {
					kind: "list",
					items: block.items.slice(0, state.wordIndex),
				};
				if (state.wordIndex >= block.items.length) {
					state.blockIndex += 1;
					state.wordIndex = 0;
				}
			}
		}

		setStreaming({ id: state.id, blocks: [...state.built] });
	}, [finishStream]);

	/** Starts revealing the answer. Returns its message id. */
	const beginStream = useCallback(
		(answer: Answer, sources: Array<Source>) => {
			setIsThinking(false);
			const id = nextId.current++;

			if (prefersReducedMotion()) {
				setMessages((current) => [...current, completed(answer, sources, id)]);
				return id;
			}

			cursor.current = {
				answer,
				sources,
				id,
				blockIndex: 0,
				wordIndex: 0,
				holdTicks: 0,
				built: [],
			};
			setStreaming({ id, blocks: [] });
			streamTimer.current = setInterval(tick, TICK_MS);
			return id;
		},
		[tick],
	);

	/**
	 * Asks the service and streams the reply in.
	 *
	 * There is no artificial thinking delay any more: the request itself takes
	 * real time, and the thinking orb covers exactly that.
	 */
	const ask = useCallback(
		async (question: string, simpleMode: boolean, token: number) => {
			try {
				const result: AskResult = await askAspire({
					message: question,
					threadId,
					simpleMode,
					persona,
				});

				if (turnToken.current !== token) return; // the turn was abandoned

				setThreadId(result.threadId);
				const id = beginStream(
					{ blocks: parseAnswer(result.reply), followUps: result.followUps },
					result.sources,
				);
				onAnswerRef.current?.(id, result.reply);
			} catch (error) {
				if (turnToken.current !== token) return;

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
		[beginStream, persona, threadId],
	);

	const send = useCallback(
		(raw: string, simpleMode = false) => {
			const text = raw.trim();
			if (!text) return;

			dropStream();
			lastQuestion.current = text;
			const token = ++turnToken.current;

			setPhase("chat");
			setIsThinking(true);
			setMessages((current) => [
				...current,
				{ id: nextId.current++, role: "user", text },
			]);

			void ask(text, simpleMode, token);
		},
		[ask, dropStream],
	);

	/** Drops the last answer and asks the same question again. */
	const regenerate = useCallback(
		(simpleMode = false) => {
			if (!lastQuestion.current) return;

			dropStream();
			const token = ++turnToken.current;

			setMessages((current) => {
				const tail = current.at(-1);
				return tail?.role === "assistant" || tail?.role === "error"
					? current.slice(0, -1)
					: current;
			});
			setIsThinking(true);

			void ask(lastQuestion.current, simpleMode, token);
		},
		[ask, dropStream],
	);

	/** Persist a finished exchange so the rail can reopen it. */
	useEffect(() => {
		if (!threadId) return;

		const tail = messages.at(-1);
		if (tail?.role !== "assistant") return;

		const firstQuestion = messages.find((m) => m.role === "user");
		if (firstQuestion?.role !== "user") return;

		setHistory(
			groupByRecency(
				saveConversation({
					threadId,
					title: titleFor(firstQuestion.text),
					updatedAt: Date.now(),
					messages: toStored(messages),
				}),
			),
		);
	}, [messages, threadId]);

	/** Reopens a stored conversation; everything lands already finished. */
	const openPast = useCallback(
		(conversation: StoredConversation) => {
			dropStream();
			turnToken.current += 1;

			const restored: Array<ChatMessage> = conversation.messages.map(
				(message) =>
					message.role === "user"
						? { id: nextId.current++, role: "user", text: message.text }
						: {
								id: nextId.current++,
								role: "assistant",
								blocks: message.blocks,
								followUps: message.followUps,
								sources: message.sources,
							},
			);

			const lastUser = [...conversation.messages]
				.reverse()
				.find((m) => m.role === "user");
			lastQuestion.current = lastUser?.role === "user" ? lastUser.text : "";

			setThreadId(conversation.threadId);
			setPhase("chat");
			setIsThinking(false);
			setMessages(restored);
		},
		[dropStream],
	);

	const reset = useCallback(() => {
		dropStream();
		lastQuestion.current = "";
		turnToken.current += 1;
		setThreadId(null);
		setPhase("landing");
		setMessages([]);
		setIsThinking(false);
	}, [dropStream]);

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
		send,
		regenerate,
		openPast,
		reset,
	};
}
