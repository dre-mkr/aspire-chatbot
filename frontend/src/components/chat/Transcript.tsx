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
import type { GamePersona, GameState } from "#/lib/aspire/games";
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
	persona: GamePersona | null;
	state: GameState;
	onChanged: (state: GameState | null) => void;
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
}: TranscriptProps) {
	return (
		<div className="transcript">
			{messages.map((message, index) => {
				if (message.role === "user") {
					return (
						<div key={message.id} className="turn turn--user">
							<p className="bubble">{message.text}</p>
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
						// How much of the conversation asking again would discard.
						// The reveal always renders at the tail, so re-asking an
						// older question necessarily drops what came after it —
						// that is coherent, but it has to be consented to.
						discards={messages.length - index - 1}
					/>
				);
			})}

			{streaming ? <StreamingAnswer answer={streaming} /> : null}

			{/* The card is an assistant turn: same orb, same column, so a game
			    reads as something the assistant is doing with you rather than a
			    mode the conversation switched into.

			    Which card is decided by the prompt's kind, not by the game's
			    name, so a third game type slots in here without the transcript
			    learning anything about it. */}
			{game ? (
				<div className="turn turn--assistant">
					<div className="orb" aria-hidden="true" />
					<div className="answer">
						{game.state.prompt.kind === "statement" ? (
							<TrueFalse
								threadId={game.threadId}
								persona={game.persona}
								state={game.state}
								onChanged={game.onChanged}
							/>
						) : (
							<WordScramble
								threadId={game.threadId}
								persona={game.persona}
								state={game.state}
								onChanged={game.onChanged}
							/>
						)}
					</div>
				</div>
			) : null}

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
		<article className="turn turn--assistant" aria-busy="true">
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
}: {
	message: Extract<ChatMessage, { role: "assistant" }>;
	onRegenerate: (messageId: number) => void;
	playback: Playback;
	discards: number;
}) {
	return (
		<article className="turn turn--assistant">
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
}: {
	text: string;
	canRetry: boolean;
	tone?: "stopped";
	onRetry: () => void;
}) {
	const stopped = tone === "stopped";
	return (
		<div className="turn turn--assistant">
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
