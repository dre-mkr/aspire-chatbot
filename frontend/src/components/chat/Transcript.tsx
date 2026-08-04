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
import { PlayingStars } from "./Voice";

/**
 * The card surfaces, fetched when one is actually started.
 *
 * All three shipped in `_shell` eagerly: WordScramble 10.3KB, EligibilityCheck
 * 10.3KB, TrueFalse 10.2KB — 30.8KB raw carried by every user on every cold
 * load, for surfaces most sessions never open.
 *
 * Splitting them costs nothing perceptible because of where they appear. A card
 * only renders when the *server* says a game or a check has started, which is
 * already the far side of a network round trip; a chunk fetch that begins at
 * that moment lands well inside the reveal that follows it.
 *
 * Never rendered during SSR. `game` and `eligibility` come from queries gated on
 * a client-only session, so they are null on the server and these are not
 * reached — which is why suspending here cannot hold up the document.
 */
const EligibilityCheck = lazy(() =>
	import("./EligibilityCheck").then((m) => ({ default: m.EligibilityCheck })),
);
const TrueFalse = lazy(() =>
	import("./TrueFalse").then((m) => ({ default: m.TrueFalse })),
);
const WordScramble = lazy(() =>
	import("./WordScramble").then((m) => ({ default: m.WordScramble })),
);

/**
 * Held space, not a spinner.
 *
 * The card is about to occupy this room; a spinner that is replaced by content
 * of a different height is a layout shift, and the thread is pinned to the
 * bottom so a shift here moves everything above it. `aria-hidden` because there
 * is nothing to say yet — the card announces itself when it arrives.
 */
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
	/**
	 * The scrolling ancestor, so the window can be measured against it.
	 *
	 * `.thread` in `AspireChat` owns the overflow, the remembered offset and the
	 * follow-the-reveal effect. The virtualizer needs the same element, and
	 * passing the ref down is cheaper than moving all of that in here.
	 */
	scrollRef: RefObject<HTMLDivElement | null>;
}

/**
 * Below this many turns the list renders whole, exactly as it always did.
 *
 * Windowing is not free: it positions rows absolutely and sizes the container
 * from estimates until the real heights are measured, which is a layout jump on
 * first paint. Paying that on a three-turn conversation — the overwhelmingly
 * common case, and the one where `.thread__inner`'s `margin-top: auto` bottom
 * anchoring matters — would trade a measured problem nobody has for a visible
 * one everybody has.
 *
 * 60 sits above the measured clean point (0 long tasks at 50 messages) and well
 * below where it degrades (76ms at 200). By the time it engages the reader is
 * deep in a conversation and pinned to the bottom, which is the cheapest moment
 * to change strategy.
 */
const VIRTUALIZE_ABOVE = 60;

/**
 * Starting guess for a turn's height, refined by measurement.
 *
 * A question bubble is short and an answer with sources is tall; 220px is
 * roughly their mean in the recorded conversations. Only unmeasured rows use
 * it, so it decides how accurate the scrollbar is before you reach a row, not
 * how anything renders.
 */
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
	animateAfterId,
	scrollRef,
}: TranscriptProps) {
	/**
	 * The answer being revealed, rendered as the message it is about to become.
	 *
	 * It carries the id `finishStream` will settle it under, and it lives in this
	 * array rather than in a slot after it, so React reconciles the reveal and the
	 * finished answer as ONE element.
	 *
	 * They used to be two: a `StreamingAnswer` rendered after the list, swapped at
	 * completion for an `Answer` inside it. Sibling slots and keyed arrays are
	 * different reconciliation scopes, so React had no way to see them as the same
	 * turn — it destroyed the node and built a fresh one. The answer blanked for a
	 * frame and then played its 400ms entry animation again on the way back, every
	 * single time a reply finished. Nothing about that was a CSS problem; the
	 * element the CSS applied to was new.
	 */
	const turns: Array<ChatMessage> = streaming
		? [
				...messages,
				{
					id: streaming.id,
					role: "assistant",
					blocks: streaming.blocks,
					followUps: streaming.followUps,
					sources: streaming.sources,
				},
			]
		: messages;

	// There is only ever one live session, so only the NEWEST game turn can show
	// it. Without this, leaving a game and starting another rendered the same
	// card twice -- once at each game turn's position -- because both asked the
	// same `game` prop for their content.
	//
	// Older game turns render nothing at all: the session they belonged to is
	// finished, and there is no server state left to draw.
	const liveGameIndex = turns.reduce(
		(latest, message, index) => (message.role === "game" ? index : latest),
		-1,
	);

	// Same rule, same reason: one check per conversation, drawn at the newest
	// turn that opened one.
	const liveCheckIndex = turns.reduce(
		(latest, message, index) => (message.role === "eligibility" ? index : latest),
		-1,
	);

	/**
	 * The suggestions belonging to the answer at the tail, revealed or not.
	 *
	 * Taken from the reveal while one is running so the chips are laid out from
	 * the start and merely become visible when the answer settles. Mounting them
	 * at completion moved the whole transcript under the reader — the thread is
	 * pinned to the bottom, so content appearing at the end pushes everything
	 * above it up.
	 */
	const chips = streaming ? streaming.followUps : followUps;

	/**
	 * What a screen reader is told, and when.
	 *
	 * There was no live region anywhere in the product, so the answer a child
	 * waits for was announced exactly never: the reveal painted four words at a
	 * time and assistive technology heard silence throughout. WCAG 4.1.3, on the
	 * primary interaction.
	 *
	 * Announced on settle rather than per tick, deliberately. `aria-live="polite"`
	 * over the revealing text would re-announce on every one of the 25 updates a
	 * second the typewriter makes — the "spamming a token at a time" failure — so
	 * this reports the transition instead: thinking, then the finished answer
	 * once, then nothing until the next turn.
	 *
	 * Visually hidden, and empty while a reveal is running, so nothing is
	 * announced twice and nothing renders.
	 */
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

	/**
	 * Windowing, and how far down the scroller this list starts.
	 *
	 * Rows are positioned relative to the scroll container, not to `.transcript`,
	 * so everything above it — the thread's top padding, the hero on the landing
	 * phase — has to be subtracted or every row sits that much too low. Measured
	 * rather than assumed: the hero collapses on the way into a conversation, so
	 * the offset is not a constant.
	 */
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

		// The hero's collapse changes the offset without resizing the list, so
		// watching the list alone would miss it.
		const observer = new ResizeObserver(measure);
		observer.observe(scroller);
		return () => observer.disconnect();
	}, [windowed, scrollRef]);

	const virtualizer = useVirtualizer({
		// Zero while the list renders whole, so the virtualizer does no work at
		// all on the common case rather than measuring a window nobody reads.
		count: windowed ? turns.length : 0,
		getScrollElement: () => scrollRef.current,
		estimateSize: () => ESTIMATED_TURN_PX,
		// Keyed by message id, not by index. The reveal and the answer it settles
		// into are one element (see `turns` above); an index key would let a row
		// be reused for a different turn and undo that.
		getItemKey: useCallback((index: number) => turns[index]?.id ?? index, [turns]),
		scrollMargin,
		// Turns are tall — roughly 1.5 fit a 662px viewport — so 3 either side is
		// already a screen and a half of runway. More is just DOM back again.
		overscan: 3,
	});

	/**
	 * One turn, wherever it is being drawn from.
	 *
	 * Extracted so the whole list and the windowed list render turns through the
	 * same code. Two copies of this would drift, and the one that drifted would
	 * be the windowed path — the one nobody looks at until a conversation is
	 * sixty turns long.
	 */
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
						<Suspense fallback={<CardLoading />}>
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
						</Suspense>
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
				onRegenerate={onRegenerate}
				playback={playback}
				arriving={arriving}
				// The same component draws the answer mid-reveal and the
				// answer that has settled. Never two behind a conditional:
				// that is the whole of the bug this replaced.
				revealing={message.id === streaming?.id}
				// How much of the conversation asking again would discard.
				// The reveal always renders at the tail, so re-asking an
				// older question necessarily drops what came after it —
				// that is coherent, but it has to be consented to.
				discards={messages.length - index - 1}
			/>
		);
	};

	return (
		<div className="transcript" ref={listRef}>
			<p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
				{announcement}
			</p>

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
				// Present and laid out for the whole of the reveal, inert and
				// invisible until the answer settles. It is the same element
				// throughout, so nothing mounts at completion and nothing animates.
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

/**
 * One assistant turn, mid-reveal or settled.
 *
 * `revealing` is a prop rather than a second component on purpose. The reveal
 * and the finished answer are one message at two ages, and the moment they were
 * two components they became two DOM nodes — which is what made a finished
 * answer blink out and re-enter.
 */
function Answer({
	message,
	onRegenerate,
	playback,
	discards,
	arriving,
	revealing,
}: {
	message: Extract<ChatMessage, { role: "assistant" }>;
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
				{/* Laid out from the first frame of the reveal and revealed when the
				    answer settles, rather than mounting at completion. The evidence
				    chip and the action row are 95px between them, and the thread is
				    pinned to the bottom — so appending them shunted the answer being
				    read upwards by that much, at the exact moment it finished. The
				    space is theirs from the start; only their visibility changes.

				    `inert` and not merely transparent: an invisible Copy button that
				    still takes Tab is worse than one that moves. */}
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
function Block({ block, revealing }: { block: AnswerBlock; revealing: boolean }) {
	if (block.kind === "paragraph") {
		return (
			<p>
				<Rich text={block.text} revealing={revealing} />
			</p>
		);
	}

	// `<ol>` when the model numbered it. Application steps are the case that
	// matters — "How do I apply for ASPIRE?" is a landing starter and its answer
	// is a procedure, which a child follows in order and a screen reader
	// announces as "list item 2 of 5" only if the element says so.
	const List = block.ordered ? "ol" : "ul";
	return (
		<List>
			{block.items.map((item, index) => (
				// Positional, not keyed by text: the last item grows word by word
				// while it is being revealed, and keying by content would make
				// every word a new <li> — remounting the node, replaying its
				// entrance, and throwing away the selection inside it.
				// biome-ignore lint/suspicious/noArrayIndexKey: append-only by construction
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
