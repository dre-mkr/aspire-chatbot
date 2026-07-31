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
} from "#/components/icons";
import type { Source } from "#/lib/aspire/api";
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
import { PlayingStars } from "./Voice";

/** Read-aloud controls, threaded down to each finished answer. */
export interface Playback {
	available: boolean;
	playingId: number | null;
	pausedId: number | null;
	play: (id: number, text: string) => void;
}

interface TranscriptProps {
	messages: Array<ChatMessage>;
	/** The answer still being revealed, if there is one. */
	streaming: Streaming | null;
	isThinking: boolean;
	followUps: Array<string>;
	onRegenerate: () => void;
	onAsk: (question: string) => void;
	playback: Playback;
}

export function Transcript({
	messages,
	streaming,
	isThinking,
	followUps,
	onRegenerate,
	onAsk,
	playback,
}: TranscriptProps) {
	return (
		<div className="transcript">
			{messages.map((message) => {
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
							onRetry={onRegenerate}
						/>
					);
				}

				return (
					<Answer
						key={message.id}
						message={message}
						onRegenerate={onRegenerate}
						playback={playback}
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
}: {
	message: Extract<ChatMessage, { role: "assistant" }>;
	onRegenerate: () => void;
	playback: Playback;
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
		<details className="sources">
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
	onRetry,
}: {
	text: string;
	canRetry: boolean;
	onRetry: () => void;
}) {
	return (
		<div className="turn turn--assistant">
			<div className="orb orb--muted" aria-hidden="true" />
			<div className="answer">
				<p className="failure" role="alert">
					<AlertIcon />
					<span>{text}</span>
				</p>
				{canRetry ? (
					<div className="answer-actions">
						<button type="button" className="text-btn" onClick={onRetry}>
							<RetryIcon />
							Try again
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
}: {
	text: string;
	onRegenerate: () => void;
	playback: Playback;
	messageId: number;
}) {
	const [copied, setCopied] = useState(false);
	const playing = playback.playingId === messageId;
	const paused = playback.pausedId === messageId;

	useEffect(() => {
		if (!copied) return;
		const timer = setTimeout(() => setCopied(false), 2000);
		return () => clearTimeout(timer);
	}, [copied]);

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

			<button type="button" className="text-btn" onClick={onRegenerate}>
				<RetryIcon />
				Try again
			</button>
		</div>
	);
}
