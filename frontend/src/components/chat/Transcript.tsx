import { useEffect, useState } from "react";
import {
	AlertIcon,
	CheckIcon,
	ChevronDownIcon,
	CopyIcon,
	PauseIcon,
	RetryIcon,
	SourcesIcon,
	SparkIcon,
	SpeakerIcon,
	StopIcon,
} from "#/components/icons";
import type { Source } from "#/lib/aspire/api";
import type { EligibilityState } from "#/lib/aspire/eligibility";
import type { GameState } from "#/lib/aspire/games";
import {
	type AnswerBlock,
	answerToText,
	type InlineNode,
	parseInline,
} from "#/lib/aspire/knowledge";
import type {
	ChatMessage,
	StreamingAnswer as Streaming,
} from "#/lib/aspire/use-conversation";
import { EligibilityCheck } from "./EligibilityCheck";
import { TrueFalse } from "./TrueFalse";
import { PlayingStars } from "./Voice";
import { WordScramble } from "./WordScramble";

/** Read-aloud controls, threaded down to each finished answer. */
export interface Playback {
	available: boolean;
	playingId: number | null;
	pausedId: number | null;
	play: (id: number, text: string) => void;
}

/**
 * A running game, threaded down so the card renders inside the conversation.
 *
 * It sits in the transcript rather than on a screen of its own because that is
 * the whole point of it: the lesson happens where the talking happens, and a
 * question mid-word is still just the next message.
 */
export interface ActiveGame {
	threadId: string;
	state: GameState;
	onChanged: (state: GameState | null) => void;
}

/**
 * A running or finished eligibility check, threaded down the same way.
 *
 * Unlike a game, this one can be finished and still worth showing: the verdict,
 * the document checklist and the application steps are the whole point, and
 * they are read over days rather than in one sitting. So the card stays until
 * it is closed, and its state comes from device storage once the server-side
 * flow is over.
 */
export interface ActiveEligibility {
	threadId: string;
	state: EligibilityState;
	onChanged: (state: EligibilityState | null) => void;
	onSpeak?: (text: string) => void;
	speakAvailable: boolean;
}

interface TranscriptProps {
	messages: Array<ChatMessage>;
	/** The answer still being revealed, if there is one. */
	streaming: Streaming | null;
	isThinking: boolean;
	followUps: Array<string>;
	/** Takes the id of the message being retried, so it replaces that one. */
	onRegenerate: (messageId: number) => void;
	onAsk: (question: string) => void;
	playback: Playback;
	game: ActiveGame | null;
	eligibility: ActiveEligibility | null;
	/**
	 * Below this id, a message is being read back rather than arriving.
	 *
	 * Entry animations belong to messages that were just sent. Restoring a
	 * conversation used to replay `rise` across every turn in it, so opening a
	 * chat from last week looked like it was being delivered live.
	 */
	animateAfterId: number;
}

export function Transcript({
	messages,
	streaming,
	isThinking,
	followUps,
	onRegenerate,
	onAsk,
	playback,
	game,
	eligibility,
	animateAfterId,
}: TranscriptProps) {
	// There is only ever one live session, so only the NEWEST game turn can show
	// it. Without this, leaving a game and starting another rendered the same
	// card twice -- once at each game turn's position -- because both asked the
	// same `game` prop for their content.
	//
	// Older game turns render nothing at all: the session they belonged to is
	// finished, and there is no server state left to draw.
	const liveGameIndex = messages.reduce(
		(latest, message, index) => (message.role === "game" ? index : latest),
		-1,
	);

	// Same rule, same reason: one check per conversation, drawn at the newest
	// turn that opened one.
	const liveCheckIndex = messages.reduce(
		(latest, message, index) =>
			message.role === "eligibility" ? index : latest,
		-1,
	);

	return (
		<div className="transcript">
			{messages.map((message, index) => {
				const arriving = message.id >= animateAfterId;

				if (message.role === "user") {
					return (
						<div
							key={message.id}
							className="turn turn--user"
							data-enter={arriving || undefined}
						>
							<p className="bubble">{message.text}</p>
						</div>
					);
				}

				// A game turn is the card and nothing else. It renders HERE, at its
				// own place in the conversation, rather than being appended after
				// the transcript — a card pinned to the end floated below every
				// question asked after it.
				//
				// `game` is the live session from the server and there is only ever
				// one, so an older game turn in a long conversation has nothing
				// left to show and renders nothing. That is correct: the session it
				// belonged to is over.
				if (message.role === "game") {
					if (!game || index !== liveGameIndex) return null;
					return (
						<div
							key={message.id}
							className="turn turn--assistant"
							data-enter={arriving || undefined}
						>
							<div className="orb" aria-hidden="true" />
							<div className="answer">
								<h2 className="sr-only">ASPIRE AI</h2>
								{game.state.prompt.kind === "statement" ? (
									<TrueFalse
										threadId={game.threadId}
										state={game.state}
										onChanged={game.onChanged}
									/>
								) : (
									<WordScramble
										threadId={game.threadId}
										state={game.state}
										onChanged={game.onChanged}
									/>
								)}
							</div>
						</div>
					);
				}

				// An eligibility turn is the card and nothing else — no prose, no
				// copy / Play / Ask again row. "Ask again" in particular would
				// restart a flow someone is part-way through, and there is nothing
				// to copy: the card is the answer.
				if (message.role === "eligibility") {
					if (!eligibility || index !== liveCheckIndex) return null;
					return (
						<div
							key={message.id}
							className="turn turn--assistant"
							data-enter={arriving || undefined}
						>
							<div className="orb" aria-hidden="true" />
							<div className="answer">
								<h2 className="sr-only">ASPIRE AI</h2>
								<EligibilityCheck
									threadId={eligibility.threadId}
									state={eligibility.state}
									onChanged={eligibility.onChanged}
									onSpeak={eligibility.onSpeak}
									speakAvailable={eligibility.speakAvailable}
								/>
							</div>
						</div>
					);
				}

				if (message.role === "error") {
					return (
						<Failure
							key={message.id}
							text={message.text}
							canRetry={message.canRetry}
							tone={message.tone}
							arriving={arriving}
							onRetry={() => onRegenerate(message.id)}
						/>
					);
				}

				return (
					<Answer
						key={message.id}
						message={message}
						onRegenerate={onRegenerate}
						playback={playback}
						arriving={arriving}
						// How much of the conversation asking again would discard.
						// The reveal always renders at the tail, so re-asking an
						// older question necessarily drops what came after it —
						// that is coherent, but it has to be consented to.
						discards={messages.length - index - 1}
					/>
				);
			})}

			{streaming ? <StreamingAnswer answer={streaming} /> : null}

			{isThinking ? (
				<div className="thinking">
					<div className="orb orb--thinking" />
					<div className="thinking__dots" aria-hidden="true">
						<i />
						<i />
						<i />
					</div>
				</div>
			) : null}

			{followUps.length > 0 ? (
				<div className="follow-ups">
					{followUps.map((prompt) => (
						<button
							key={prompt}
							type="button"
							className="follow-up"
							onClick={() => onAsk(prompt)}
						>
							<SparkIcon size={14} />
							{prompt}
						</button>
					))}
				</div>
			) : null}
		</div>
	);
}

/**
 * The answer mid-reveal. The only component that re-renders on a typewriter
 * tick — everything above it is settled and keeps its identity.
 */
function StreamingAnswer({ answer }: { answer: Streaming }) {
	return (
		<article className="turn turn--assistant" data-enter aria-busy="true">
			<div className="orb" aria-hidden="true" />
			<div className="answer">
				<h2 className="sr-only">ASPIRE AI</h2>
				{answer.blocks.map((block, index) => (
					// Blocks are a fixed, ordered script; index is their identity.
					// biome-ignore lint/suspicious/noArrayIndexKey: positional by design
					<Block key={index} block={block} />
				))}
			</div>
		</article>
	);
}

function Answer({
	message,
	onRegenerate,
	playback,
	discards,
	arriving,
}: {
	message: Extract<ChatMessage, { role: "assistant" }>;
	onRegenerate: (messageId: number) => void;
	playback: Playback;
	discards: number;
	arriving: boolean;
}) {
	return (
		<article
			className="turn turn--assistant"
			data-enter={arriving || undefined}
		>
			<div className="orb" aria-hidden="true" />
			<div className="answer">
				<h2 className="sr-only">ASPIRE AI</h2>
				{message.blocks.map((block, index) => (
					// biome-ignore lint/suspicious/noArrayIndexKey: positional by design
					<Block key={index} block={block} />
				))}
				<Sources sources={message.sources} />
				<AnswerActions
					text={answerToText(message.blocks)}
					onRegenerate={onRegenerate}
					playback={playback}
					messageId={message.id}
					discards={discards}
				/>
			</div>
		</article>
	);
}

/** Renders one block, promoting `**...**` runs to real emphasis. */
function Block({ block }: { block: AnswerBlock }) {
	if (block.kind === "paragraph") {
		return (
			<p>
				<Rich text={block.text} />
			</p>
		);
	}
	return (
		<ul>
			{block.items.map((item) => (
				<li key={item}>
					<Rich text={item} />
				</li>
			))}
		</ul>
	);
}

function Rich({ text }: { text: string }) {
	return <Inline nodes={parseInline(text)} />;
}

function Inline({ nodes }: { nodes: Array<InlineNode> }) {
	return (
		<>
			{nodes.map((node, index) => {
				// Runs are positional within a fixed string.
				if (node.kind === "bold") {
					return (
						// biome-ignore lint/suspicious/noArrayIndexKey: positional by design
						<strong key={index}>
							<Inline nodes={node.children} />
						</strong>
					);
				}

				if (node.kind === "link") {
					const external = node.href.startsWith("http");
					return (
						<a
							// biome-ignore lint/suspicious/noArrayIndexKey: positional by design
							key={index}
							className="answer-link"
							href={node.href}
							// noopener/noreferrer matter here: the target comes from a
							// language model, not from us.
							{...(external
								? { target: "_blank", rel: "noopener noreferrer" }
								: {})}
						>
							{node.text}
						</a>
					);
				}

				// biome-ignore lint/suspicious/noArrayIndexKey: positional by design
				return <span key={index}>{node.text}</span>;
			})}
		</>
	);
}

/**
 * The knowledge-base extracts behind an answer.
 *
 * Collapsed by default: it is the evidence, not the answer. Open it and you can
 * check the assistant's work against what it actually read.
 */
function Sources({ sources }: { sources: Array<Source> }) {
	if (sources.length === 0) return null;

	return (
		// Opening this grows the thread by the height of the panel, and the
		// transcript's scroll-follow only runs when a message settles — so the
		// evidence appears and pushes the answer's action row and the follow-up
		// chips under the composer with nothing to say they moved.
		//
		// Scrolling the panel itself is no help: `block: "nearest"` does nothing
		// when the panel is already on screen, which is the usual case, and the
		// content that got displaced is what fell off. So scroll the end of the
		// transcript instead — the follow-ups when there are any, the answer's
		// own last row otherwise.
		<details
			className="sources"
			onToggle={(event) => {
				if (!event.currentTarget.open) return;
				const end =
					event.currentTarget.closest(".transcript")?.lastElementChild;
				end?.scrollIntoView({ block: "end", behavior: "smooth" });
			}}
		>
			<summary className="sources__toggle">
				<SourcesIcon />
				<span>
					{sources.length} {sources.length === 1 ? "source" : "sources"}
				</span>
				<ChevronDownIcon size={14} className="sources__chevron" />
			</summary>

			<ul className="sources__list">
				{sources.map((source, index) => {
					const label = source.metadata.question ?? source.metadata.category;
					return (
						// Snippets can repeat text; position is their identity.
						// biome-ignore lint/suspicious/noArrayIndexKey: positional by design
						<li key={index} className="source">
							{label ? <p className="source__label">{String(label)}</p> : null}
							<p className="source__text">{source.content}</p>
						</li>
					);
				})}
			</ul>
		</details>
	);
}

function Failure({
	text,
	canRetry,
	tone,
	onRetry,
	arriving,
}: {
	text: string;
	canRetry: boolean;
	tone?: "stopped";
	onRetry: () => void;
	arriving: boolean;
}) {
	const stopped = tone === "stopped";
	return (
		<div className="turn turn--assistant" data-enter={arriving || undefined}>
			<div className="orb orb--muted" aria-hidden="true" />
			<div className="answer">
				{/* Every other assistant turn carries this, so heading navigation
				    skipped precisely the turns where "who is speaking" is least
				    obvious. */}
				<h2 className="sr-only">ASPIRE AI</h2>
				{/* No role="alert" here. AspireChat already routes the newest error
				    into the transcript's own live region, and a role="alert" on the
				    same text makes a screen reader read every failure twice. */}
				<p className="failure" data-tone={tone}>
					{stopped ? <StopIcon /> : <AlertIcon />}
					<span>{text}</span>
				</p>
				{canRetry ? (
					<div className="answer-actions">
						<button type="button" className="text-btn" onClick={onRetry}>
							<RetryIcon />
							{/* Nothing went wrong, so it is not "Try again" — the
							    question is simply still there to be asked. */}
							{stopped ? "Ask again" : "Try again"}
						</button>
					</div>
				) : null}
			</div>
		</div>
	);
}

function AnswerActions({
	text,
	onRegenerate,
	playback,
	messageId,
	discards,
}: {
	text: string;
	onRegenerate: (messageId: number) => void;
	playback: Playback;
	messageId: number;
	discards: number;
}) {
	const [copied, setCopied] = useState(false);
	// Two-step only when something would actually be lost. Asking again on the
	// newest answer discards nothing, so it stays a single press.
	const [confirming, setConfirming] = useState(false);
	const playing = playback.playingId === messageId;
	const paused = playback.pausedId === messageId;

	useEffect(() => {
		if (!copied) return;
		const timer = setTimeout(() => setCopied(false), 2000);
		return () => clearTimeout(timer);
	}, [copied]);

	// A confirm left armed is a trap for the next person to press the button.
	useEffect(() => {
		if (!confirming) return;
		const timer = setTimeout(() => setConfirming(false), 5000);
		return () => clearTimeout(timer);
	}, [confirming]);

	function askAgain() {
		if (discards > 0 && !confirming) {
			setConfirming(true);
			return;
		}
		setConfirming(false);
		onRegenerate(messageId);
	}

	async function copy() {
		try {
			await navigator.clipboard.writeText(text);
			setCopied(true);
		} catch {
			// Clipboard access can be denied outright; the answer stays selectable.
		}
	}

	return (
		<div className="answer-actions">
			{playback.available ? (
				<>
					<button
						type="button"
						className="play-btn"
						data-state={playing ? "playing" : paused ? "paused" : "idle"}
						onClick={() => playback.play(messageId, text)}
					>
						{playing ? <PauseIcon /> : <SpeakerIcon />}
						{playing ? "Playing" : paused ? "Paused" : "Play"}
					</button>
					{playing ? <PlayingStars /> : null}
				</>
			) : null}

			<button type="button" className="icon-btn icon-btn--sm" onClick={copy}>
				{copied ? <CheckIcon /> : <CopyIcon />}
				<span className="sr-only">
					{copied ? "Answer copied" : "Copy answer"}
				</span>
			</button>

			{/* "Ask again", not "Try again": under a successful answer the latter
			    reads as "you got it wrong", which is the last thing a child sees
			    on every correct answer. "Try again" now belongs to the error
			    state only, where it means what it says. */}
			<button
				type="button"
				className="text-btn"
				data-confirming={confirming || undefined}
				onClick={askAgain}
			>
				<RetryIcon />
				{confirming
					? `Ask again and drop the ${discards} ${discards === 1 ? "message" : "messages"} after it?`
					: "Ask again"}
			</button>
		</div>
	);
}
