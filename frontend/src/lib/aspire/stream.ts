/** The chat transport. */

import { streamTurn } from "../stream/client";
import { displayNameFor, promptKindFor } from "./game-kinds";
import { forget, graphSession } from "../stream/session";
import type {
	CitationsDirective,
	Directive,
	EligibilityDirective,
	GameDirective,
	GameResultPayload,
	QuickRepliesDirective,
	UploadResult,
	WidgetInteraction,
} from "../stream/types";
import {
	type AskInput,
	type AskResult,
	AspireError,
	type Source,
	type StartedEligibility,
	type StartedGame,
} from "./api";

/** Directive types the transcript renders through its own card row, not inline. */
const CARD_TYPES = new Set(["game", "eligibility"]);

/** A new conversation needs an id before the first request, not after it. */
function newThreadId(): string {
	if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
		return crypto.randomUUID();
	}
	// Older Safari on a school tablet.
	return `t-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
}

/** One turn, streamed. Resolves with the whole answer. */
export async function streamAspire(
	input: AskInput & {
		onDelta?: (delta: string) => void;
		onTextEnd?: () => void;
		onTurn?: (result: AskResult) => void;
		/** A widget interaction instead of a typed message. */
		interaction?: WidgetInteraction;
		/** The answer to a document upload the graph is PAUSED on. */
		uploadResult?: UploadResult;
		/** A finished game's score instead of a typed message. */
		gameResult?: GameResultPayload;
		/**
		 * False when the reader has PINNED a language from the menu.
		 *
		 * Only the pin is sent. Absent means Automatic on the server too, so
		 * every caller that never passes it — and every older client — keeps the
		 * detection that has always run.
		 */
		autoLanguage?: boolean;
	},
): Promise<AskResult> {
	const {
		message,
		threadId,
		persona,
		language = "en",
		simpleMode,
		interaction,
		uploadResult,
		gameResult,
		autoLanguage = true,
		onDelta,
		onTextEnd,
		onTurn,
		signal,
	} = input;

	const thread = threadId ?? newThreadId();

	let session: Awaited<ReturnType<typeof graphSession>>;
	try {
		session = await graphSession(thread, { locale: language, persona });
	} catch {
		throw new AspireError(
			"The assistant could not be reached. Please try again.",
			true,
		);
	}

	const sources: Array<Source> = [];
	const followUps: Array<string> = [];
	const directives: Array<Directive> = [];
	let startedGame: StartedGame | null = null;
	let startedEligibility: StartedEligibility | null = null;
	/** The prose is final once anything that is not a token arrives. */
	let proseClosed = false;

	const closeProse = () => {
		if (proseClosed) return;
		proseClosed = true;
		onTextEnd?.();
	};

	const result = await streamTurn({
		message,
		token: session.token,
		signal,
		...(interaction
			? {
					path: "/v2/widget/interaction",
					body: interaction as unknown as Record<string, unknown>,
				}
			: {}),
		...(gameResult
			? {
					path: "/v2/game/result",
					body: gameResult as unknown as Record<string, unknown>,
				}
			: {}),
		// The ordinary chat path: this IS the turn answering the upload the graph awaits.
		...(uploadResult
			? {
					body: {
						message,
						...(simpleMode ? { simple_mode: true } : {}),
						...(autoLanguage ? {} : { auto_language: false }),
						__upload_result: uploadResult as unknown as Record<string, unknown>,
					},
				}
			: {}),
		// "Explain it simply" shapes an ANSWER, so it rides the chat path only.
		//
		// This was the one place the flag was lost: every layer above carried it
		// correctly and the destructure above dropped it, so the toggle showed a
		// pressed state and changed nothing on the wire. The widget-interaction
		// and game-result branches post typed bodies to their own endpoints and
		// must not gain a key those schemas do not declare.
		//
		// `auto_language: false` rides the same path for the same reason: it
		// shapes the ANSWER. It is sent only when the reader has pinned a
		// language, because absent means Automatic on the server, and the two
		// typed endpoints above must not gain a key their schemas do not declare.
		...((simpleMode || !autoLanguage) &&
		!interaction &&
		!gameResult &&
		!uploadResult
			? {
					body: {
						message,
						...(simpleMode ? { simple_mode: true } : {}),
						...(autoLanguage ? {} : { auto_language: false }),
					},
				}
			: {}),
		onToken: (text) => onDelta?.(text),
		onDirective: (directive) => {
			// Directives close the prose: the server emits them after the last token.
			closeProse();

			// Cast per branch rather than relying on narrowing.
			switch (directive.t) {
				case "citations":
					for (const ref of (directive as CitationsDirective).refs) {
						sources.push({
							// The row's own text, so the panel shows evidence, not the title again.
							content: ref.snippet || ref.title || ref.kb_id,
							metadata: {
								kb_id: ref.kb_id,
								title: ref.title,
								question: ref.question || ref.title,
							},
						});
					}
					return;

				case "quick_replies":
					for (const option of (directive as QuickRepliesDirective).options) {
						followUps.push(option.value);
					}
					return;

				case "game": {
					const game = (directive as GameDirective).game;
					startedGame = {
						gameType: game,
						displayName: displayNameFor(game),
						// The transcript picks its component from this.
						kind: promptKindFor(game),
						total: 0,
						concept: (directive as GameDirective).concept ?? "saving_basics",
					};
					return;
				}

				case "eligibility": {
					const check = directive as EligibilityDirective;
					startedEligibility = {
						check: check.check,
						language: check.language,
					};
					return;
				}

				default:
					directives.push(directive);
			}
		},
		onDone: () => closeProse(),
		onError: () => closeProse(),
	});

	if (result.error) {
		if (result.error.code === "unauthenticated") {
			// The token expired mid-conversation.
			forget(thread);
		}
		throw new AspireError(result.error.message, true);
	}

	const answer: AskResult = {
		// A card turn produces no prose at all, so an empty reply here is correct.
		reply: startedGame || startedEligibility ? "" : result.text,
		threadId: thread,
		sources,
		followUps,
		startedGame,
		startedEligibility,
		directives: directives.filter((d) => !CARD_TYPES.has(d.t)),
	};

	// Handed over before this resolves: the caller settles on this, not on the return.
	onTurn?.(answer);
	return answer;
}
