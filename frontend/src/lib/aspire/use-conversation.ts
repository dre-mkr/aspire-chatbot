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

	// Commits before any later click can be dispatched, so the guard in `send`
	// never reads a stale value.
	useEffect(() => {
		isThinkingRef.current = isThinking;
	}, [isThinking]);

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
			// A second question while the first is still in flight used to bump
			// the turn token, so the first reply was discarded on arrival and its
			// user bubble sat in the transcript forever with no answer and no
			// error. The composer disables send while busy; this is the guard
			// behind it.
			if (isThinkingRef.current || cursor.current) return;

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
	/**
	 * Settles only what has actually been revealed.
	 *
	 * Deliberately not `finishStream`, which appends `state.answer` — the whole
	 * reply, including the words the reveal had not reached. Calling that from
	 * `stop` made the stop button a reveal-everything button for the entire
	 * length of the typewriter, which is the opposite of what it says.
	 *
	 * Follow-ups are dropped: they belong to an answer that finished.
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

	const stop = useCallback(() => {
		turnToken.current += 1;

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
	}, [settleRevealed]);

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
		stop,
		openPast,
		reset,
	};
}
