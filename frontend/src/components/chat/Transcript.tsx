import { useVirtualizer } from "@tanstack/react-virtual";
import {
	lazy,
	type RefObject,
	Suspense,
	useCallback,
	useEffect,
	useLayoutEffect,
	useRef,
	useState,
} from "react";
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
import type { GameState, GameSummary } from "#/lib/aspire/games";
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
import type { DirectiveContext } from "./DirectiveRegistry";
import { DirectiveView } from "./DirectiveRegistry";
import { PlayingStars } from "./Voice";

/** The card surfaces, fetched when one is actually started. */
const EligibilityCheck = lazy(() =>
	import("./EligibilityCheck").then((m) => ({ default: m.EligibilityCheck })),
);
const TrueFalse = lazy(() =>
	import("./TrueFalse").then((m) => ({ default: m.TrueFalse })),
);
const WordScramble = lazy(() =>
	import("./WordScramble").then((m) => ({ default: m.WordScramble })),
);

/** Held space, not a spinner. */
function CardLoading() {
	return <div className="card-loading" aria-hidden="true" />;
}

/** Read-aloud controls, threaded down to each finished answer. */
export interface Playback {
	available: boolean;
	playingId: number | null;
	pausedId: number | null;
	play: (id: number, text: string) => void;
}

/** A running game, threaded down so the card renders inside the conversation. */
export interface ActiveGame {
	threadId: string;
	state: GameState;
	onChanged: (state: GameState | null) => void;
	/** The final numbers, the moment the set resolves. */
	onSummary?: (summary: GameSummary) => void;
}

/** A running or finished eligibility check, threaded down the same way. */
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
	/** What a directive needs in order to be interactive. */
	directiveContext: DirectiveContext;
	/** Below this id, a message is being read back rather than arriving. */
	animateAfterId: number;
	/** The scrolling ancestor, so the window can be measured against it. */
	scrollRef: RefObject<HTMLDivElement | null>;
}

/** Below this many turns the list renders whole, exactly as it always did. */
const VIRTUALIZE_ABOVE = 60;

/** Starting guess for a turn's height, refined by measurement. */
const ESTIMATED_TURN_PX = 220;

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
	directiveContext,
	animateAfterId,
	scrollRef,
}: TranscriptProps) {
	/** The answer being revealed, rendered as the message it is about to become. */
	const turns: Array<ChatMessage> = streaming
		? [
				...messages,
				{
					id: streaming.id,
					role: "assistant",
					blocks: streaming.blocks,
					followUps: streaming.followUps,
					sources: streaming.sources,
					// Deliberately absent mid-reveal.
				},
			]
		: messages;

	// There is only ever one live session, so only the NEWEST game turn can show it.
	const liveGameIndex = turns.reduce(
		(latest, message, index) => (message.role === "game" ? index : latest),
		-1,
	);

	// Same rule, same reason: one check per conversation, drawn at the newest turn that opened one.
	const liveCheckIndex = turns.reduce(
		(latest, message, index) =>
			message.role === "eligibility" ? index : latest,
		-1,
	);

	/** The suggestions belonging to the answer at the tail, revealed or not. */
	const chips = streaming ? streaming.followUps : followUps;

	/** What a screen reader is told, and when. */
	const settled = streaming ? undefined : messages.at(-1);
	const announcement = streaming
		? ""
		: isThinking
			? "Finding an answer."
			: settled?.role === "assistant"
				? `Answer ready. ${answerToText(settled.blocks)}`
				: settled?.role === "error"
					? settled.text
					: "";

	/** Windowing, and how far down the scroller this list starts. */
	const listRef = useRef<HTMLDivElement>(null);
	const [scrollMargin, setScrollMargin] = useState(0);
	const windowed = turns.length > VIRTUALIZE_ABOVE;

	useLayoutEffect(() => {
		if (!windowed) return;
		const list = listRef.current;
		const scroller = scrollRef.current;
		if (!list || !scroller) return;

		const measure = () => {
			setScrollMargin(
				list.getBoundingClientRect().top -
					scroller.getBoundingClientRect().top +
					scroller.scrollTop,
			);
		};
		measure();

		// The hero's collapse changes the offset without resizing the list, so watching the list alone would miss it.
		const observer = new ResizeObserver(measure);
		observer.observe(scroller);
		return () => observer.disconnect();
	}, [windowed, scrollRef]);

	const virtualizer = useVirtualizer({
		// Zero while the list renders whole, so the virtualizer does no work at all on the common case rather than meas…
		count: windowed ? turns.length : 0,
		getScrollElement: () => scrollRef.current,
		estimateSize: () => ESTIMATED_TURN_PX,
		// Keyed by message id, not by index.
		getItemKey: useCallback(
			(index: number) => turns[index]?.id ?? index,
			[turns],
		),
		scrollMargin,
		// Turns are tall — roughly 1.5 fit a 662px viewport — so 3 either side is already a screen and a half of runway.
		overscan: 3,
	});

	/** One turn, wherever it is being drawn from. */
	const renderTurn = (message: ChatMessage, index: number) => {
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

		// A game turn is the card and nothing else.
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
						<Suspense fallback={<CardLoading />}>
							{game.state.prompt.kind === "statement" ? (
								<TrueFalse
									threadId={game.threadId}
									state={game.state}
									onChanged={game.onChanged}
									onSummary={game.onSummary}
								/>
							) : (
								<WordScramble
									threadId={game.threadId}
									state={game.state}
									onChanged={game.onChanged}
									onSummary={game.onSummary}
								/>
							)}
						</Suspense>
					</div>
				</div>
			);
		}

		// An eligibility turn is the card and nothing else — no prose, no copy / Play / Ask again row.
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
						<Suspense fallback={<CardLoading />}>
							<EligibilityCheck
								threadId={eligibility.threadId}
								state={eligibility.state}
								onChanged={eligibility.onChanged}
								onSpeak={eligibility.onSpeak}
								speakAvailable={eligibility.speakAvailable}
							/>
						</Suspense>
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
				directiveContext={directiveContext}
				onRegenerate={onRegenerate}
				playback={playback}
				arriving={arriving}
				// The same component draws the answer mid-reveal and the answer that has settled.
				revealing={message.id === streaming?.id}
				// How much of the conversation asking again would discard.
				discards={messages.length - index - 1}
			/>
		);
	};

	return (
		<div className="transcript" ref={listRef}>
			{/* `<output>` is a status region by definition, so the role is implicit. */}
			<output className="sr-only" aria-live="polite" aria-atomic="true">
				{announcement}
			</output>

			{windowed ? (
				<div
					className="transcript__window"
					style={{ height: virtualizer.getTotalSize() }}
				>
					{virtualizer.getVirtualItems().map((row) => (
						<div
							key={row.key}
							data-index={row.index}
							ref={virtualizer.measureElement}
							className="transcript__row"
							style={{ transform: `translateY(${row.start - scrollMargin}px)` }}
						>
							{renderTurn(turns[row.index], row.index)}
						</div>
					))}
				</div>
			) : (
				turns.map(renderTurn)
			)}

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

			{chips.length > 0 ? (
				// Present and laid out for the whole of the reveal, inert and invisible until the answer settles.
				<div
					className="follow-ups"
					data-pending={streaming ? "" : undefined}
					inert={!!streaming || undefined}
				>
					{chips.map((prompt) => (
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

/** One assistant turn, mid-reveal or settled. */
function Answer({
	message,
	directiveContext,
	onRegenerate,
	playback,
	discards,
	arriving,
	revealing,
}: {
	message: Extract<ChatMessage, { role: "assistant" }>;
	directiveContext: DirectiveContext;
	onRegenerate: (messageId: number) => void;
	playback: Playback;
	discards: number;
	arriving: boolean;
	revealing: boolean;
}) {
	return (
		<article
			className="turn turn--assistant"
			data-enter={arriving || undefined}
			aria-busy={revealing || undefined}
		>
			<div className="orb" aria-hidden="true" />
			<div className="answer">
				<h2 className="sr-only">ASPIRE AI</h2>
				{message.blocks.map((block, index) => (
					// biome-ignore lint/suspicious/noArrayIndexKey: positional by design
					<Block key={index} block={block} revealing={revealing} />
				))}
				{/* Between the prose and the tail, which is where the turn put them: a widget answers the question the paragraph… */}
				{!revealing && message.directives?.length
					? message.directives.map((directive, index) => (
							<DirectiveView
								// biome-ignore lint/suspicious/noArrayIndexKey: positional by design
								key={index}
								directive={directive}
								context={directiveContext}
							/>
						))
					: null}
				{/* Laid out from the first frame of the reveal and revealed when the answer settles, rather than mounting at com… */}
				<div
					className="answer__tail"
					data-pending={revealing ? "" : undefined}
					inert={revealing || undefined}
				>
					<Sources sources={message.sources} />
					<AnswerActions
						text={answerToText(message.blocks)}
						onRegenerate={onRegenerate}
						playback={playback}
						messageId={message.id}
						discards={discards}
					/>
				</div>
			</div>
		</article>
	);
}

/** Renders one block, promoting `**...**` runs to real emphasis. */
function Block({
	block,
	revealing,
}: {
	block: AnswerBlock;
	revealing: boolean;
}) {
	if (block.kind === "paragraph") {
		return (
			<p>
				<Rich text={block.text} revealing={revealing} />
			</p>
		);
	}

	// `<ol>` when the model numbered it.
	const List = block.ordered ? "ol" : "ul";
	return (
		<List>
			{block.items.map((item, index) => (
				// biome-ignore lint/suspicious/noArrayIndexKey: positional by design
				<li key={index}>
					<Rich text={item} revealing={revealing} />
				</li>
			))}
		</List>
	);
}

function Rich({ text, revealing }: { text: string; revealing: boolean }) {
	return <Inline nodes={parseInline(text, revealing)} />;
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
							// noopener/noreferrer matter here: the target comes from a language model, not from us.
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

/** The knowledge-base extracts behind an answer. */
function Sources({ sources }: { sources: Array<Source> }) {
	if (sources.length === 0) return null;

	return (
		// Opening this grows the thread by the height of the panel, and the transcript's scroll-follow only runs when a…
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
					const label = source.metadata?.question ?? source.metadata?.category;
					const reference = source.metadata?.kb_id;
					// The snippet only earns its space when it says something the
					// label does not; on a short row the two can be the same text.
					const snippet =
						source.content && source.content !== String(label ?? "")
							? source.content
							: null;
					return (
						// biome-ignore lint/suspicious/noArrayIndexKey: snippets can repeat text; position is their identity
						<li key={index} className="source">
							<p className="source__head">
								{reference ? (
									<span className="source__ref">{String(reference)}</span>
								) : null}
								{label ? (
									<span className="source__label">{String(label)}</span>
								) : null}
							</p>
							{snippet ? <p className="source__text">{snippet}</p> : null}
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
				{/* Every other assistant turn carries this, so heading navigation skipped precisely the turns where "who is spea… */}
				<h2 className="sr-only">ASPIRE AI</h2>
				{/* No role="alert" here. */}
				<p className="failure" data-tone={tone}>
					{stopped ? <StopIcon /> : <AlertIcon />}
					<span>{text}</span>
				</p>
				{canRetry ? (
					<div className="answer-actions">
						<button type="button" className="text-btn" onClick={onRetry}>
							<RetryIcon />
							{/* Nothing went wrong, so it is not "Try again" — the question is simply still there to be asked. */}
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
	// Two-step only when something would actually be lost.
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

			{/* Labelled like the two either side of it: one bare icon in a row of
			    named actions is the only one a reader has to guess at. */}
			<button type="button" className="text-btn" onClick={copy}>
				{copied ? <CheckIcon /> : <CopyIcon />}
				{copied ? "Copied" : "Copy"}
			</button>

			{/* "Ask again", not "Try again": under a successful answer the latter reads as "you got it wrong", which is the… */}
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
