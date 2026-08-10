/**
 * The chat transport. One turn, streamed, through the graph.
 *
 * ## What changed, and what deliberately did not
 *
 * The wire is now `POST /v2/chat/stream` and the events are ASPIRE's own
 * (`token`, `directive`, `done`, `error`) rather than AG-UI's. What is
 * unchanged is this function's shape: it still resolves to the same
 * `AskResult`, so the typewriter, the cards, the sources and the chips cannot
 * tell which backend produced it. `use-conversation.ts` did not have to change
 * to switch transports, which is the whole point of keeping this seam.
 *
 * `@tanstack/ai-client` is gone with AG-UI. It was used for one thing — an SSE
 * connection adapter — and `lib/stream/client.ts` reads the body itself, with a
 * frame splitter that is tested directly under `node --test`.
 *
 * ## Where the v1 concepts went
 *
 *   `sources`      ← the `citations` directive
 *   `followUps`    ← the `quick_replies` directive. NOT a second model call any
 *                    more: the agents emit chips from what they actually did,
 *                    so a turn no longer pays for two questions to put under
 *                    itself. They arrive with the turn rather than seconds
 *                    after it, which is why there is no late `follow_ups`
 *                    event to wait for.
 *   `startedGame`  ← the `game` directive
 *   `startedEligibility` ← the `eligibility` directive
 *   `directives`   ← everything else, in ordinal order, for the transcript to
 *                    render inline. New, and additive: a caller that ignores it
 *                    behaves exactly as it did.
 *
 * Both card directives are REMOVED from `directives` once mapped. That is what
 * stops a game being mounted twice — once by the transcript's card row and once
 * by the directive renderer — which is a failure that would only show up as two
 * server-side game sessions racing over one thread.
 *
 * ## Falling back
 *
 * There is nothing to fall back to. `/chat` and `/chat/stream` are gone, and a
 * second path that answered the same question differently is how a streaming
 * transport quietly becomes a second product. A stream that never opened and a
 * stream that broke are both failed turns, reported as such — the service
 * records the question before it answers, so retrying would ask the model twice
 * and append a second copy of the turn.
 */

import { streamTurn } from "../stream/client";
import { forget, graphSession } from "../stream/session";
import type {
	CitationsDirective,
	Directive,
	EligibilityDirective,
	GameDirective,
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
	// Older Safari on a school tablet. Not a security value — it names a
	// conversation — so `Math.random` is adequate and `crypto` is preferred
	// only because it is there.
	return `t-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
}

/** One turn, streamed. Resolves with the whole answer. */
export async function streamAspire(
	input: AskInput & {
		onDelta?: (delta: string) => void;
		onTextEnd?: () => void;
		onTurn?: (result: AskResult) => void;
		/**
		 * A widget interaction instead of a typed message.
		 *
		 * Same transport, same result shape, a different endpoint: what a child
		 * did with a widget is a turn the agent has to answer referencing their
		 * actual numbers, not an event to be counted. The interaction rides on
		 * `safety_flags` server-side rather than in `messages`, so it never
		 * enters the transcript the model reads back.
		 */
		interaction?: WidgetInteraction;
		/**
		 * The answer to a document upload the graph is PAUSED on.
		 *
		 * Not prose, and it cannot be. A document slot suspends the graph inside
		 * `interrupt()`, and the only thing that continues a suspended node is
		 * `Command(resume=...)`. An ordinary message re-enters at START, re-runs
		 * `resume_or_start` and asks for the first slot again -- so a parent who
		 * answered every question reached the ID photo and was sent back to
		 * "What is your full name?" forever. The server reads this off
		 * `__upload_result` and hands it to the paused node; see the note in
		 * `api/stream.py`.
		 */
		uploadResult?: UploadResult;
	},
): Promise<AskResult> {
	const {
		message,
		threadId,
		persona,
		language = "en",
		interaction,
		uploadResult,
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
		// The ordinary chat path, unlike an interaction: this IS the turn that
		// answers the upload the graph is waiting on, so it carries the message
		// field the endpoint always reads, plus the resume payload beside it.
		...(uploadResult
			? {
					body: {
						message,
						__upload_result: uploadResult as unknown as Record<
							string,
							unknown
						>,
					},
				}
			: {}),
		onToken: (text) => onDelta?.(text),
		onDirective: (directive) => {
			// Directives close the prose in this protocol: the server emits them
			// from the settled state, after the last token. Worth signalling
			// separately from `done`, because `done` is also behind the turn's
			// persistence and the reveal should not hold its last word for that.
			closeProse();

			// Cast per branch rather than relying on narrowing. `Directive` is an
			// OPEN union -- it ends in `UnknownDirective { t: string }` so a
			// backend that ships a new type before this build knows about it is a
			// normal deploy rather than a crash -- and an open union widens `t` to
			// `string`, which defeats discrimination. The cast is safe because the
			// server's union is closed and discriminated on the same field.
			switch (directive.t) {
				case "citations":
					for (const ref of (directive as CitationsDirective).refs) {
						sources.push({
							content: ref.title || ref.kb_id,
							metadata: { kb_id: ref.kb_id, title: ref.title },
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
						displayName: game.replace(/_/g, " "),
						// The transcript picks its component from this. The graph
						// names the game, not the item, so `true_false` is the one
						// that renders a statement and everything else renders a
						// scramble — same rule the v1 payload carried.
						kind: game === "true_false" ? "statement" : "scramble",
						total: 0,
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
			// The token expired mid-conversation. Dropped so the next turn mints
			// a fresh one rather than failing identically forever.
			forget(thread);
		}
		throw new AspireError(result.error.message, true);
	}

	const answer: AskResult = {
		// A card turn produces no prose at all — the server never asks a model
		// to write any — so an empty reply here is correct and not a fault.
		reply: startedGame || startedEligibility ? "" : result.text,
		threadId: thread,
		sources,
		followUps,
		startedGame,
		startedEligibility,
		directives: directives.filter((d) => !CARD_TYPES.has(d.t)),
	};

	// Handed over before this function resolves, matching the old contract:
	// the caller settles the turn on this rather than on the promise, so the
	// sources and the action row appear with the last word.
	onTurn?.(answer);
	return answer;
}
