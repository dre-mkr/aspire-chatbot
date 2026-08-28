import { useVirtualizer } from "@tanstack/react-virtual";
import {
	lazy,
	type ReactNode,
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
	ExternalLinkIcon,
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
import { type GroupedSource, groupSources } from "#/lib/aspire/sources";
import type {
	ChatMessage,
	StreamingAnswer as Streaming,
} from "#/lib/aspire/use-conversation";
import { say, useLocale } from "../../lib/aspire/i18n";
import { AspirePath, type PathState } from "./AspirePath";
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
const Millionaire = lazy(() =>
	import("./Millionaire").then((m) => ({ default: m.Millionaire })),
);
const Hangman = lazy(() =>
	import("./Hangman").then((m) => ({ default: m.Hangman })),
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
	/**
	 * The name the reader knows this assistant by -- Skye, Kaleb, Zion, and so on.
	 *
	 * Every assistant turn used to be announced as "ASPIRE AI" while the composer
	 * chip said Skye, so a screen-reader user never met the guide they chose.
	 * `global_rules.py` settles which is right: "You are called ASPIRE AI; if a
	 * persona below gives you a name, THAT is the name the reader knows you by."
	 */
	guideName: string;
	messages: Array<ChatMessage>;
	/** The answer still being revealed, if there is one. */
	streaming: Streaming | null;
	isThinking: boolean;
	/** ASPIRE Path for the turn in flight, or null. Shown beside the orb. */
	path?: PathState | null;
	followUps: Array<string>;
	/** Takes the id of the message being retried, so it replaces that one. */
	/** `simple` forces the plain-words answer regardless of the composer toggle. */
	onRegenerate: (messageId: number, simple?: boolean) => void;
	onAsk: (question: string) => void;
	playback: Playback;
	game: ActiveGame | null;
	/** The reader's sound preference, from the voice and sound menu. */
	gameSound?: boolean;
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
	guideName,
	messages,
	streaming,
	isThinking,
	path = null,
	followUps,
	onRegenerate,
	onAsk,
	playback,
	game,
	gameSound = true,
	eligibility,
	directiveContext,
	animateAfterId,
	scrollRef,
}: TranscriptProps) {
	// Re-render when the reader changes language: `say` reads storage,
	// and storage changing is not something React can see on its own.
	useLocale();
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

	// A table needs more room than the 660px reading column. Any thread that
	// holds one widens its column for every persona -- prose stays capped at the
	// reading measure (see styles), so only the table takes the extra width.
	const hasTable = turns.some(
		(message) =>
			message.role === "assistant" &&
			message.blocks?.some((block) => block.kind === "table"),
	);

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

	/* What a screen reader is told lives in `ChatScreen`, which owns the app's
	   one status region. This file used to carry a second one saying much the
	   same thing, and the two together read every answer out twice. */

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

		// Watch the scroller: the hero's collapse moves the offset without resizing the list.
		const observer = new ResizeObserver(measure);
		observer.observe(scroller);
		return () => observer.disconnect();
	}, [windowed, scrollRef]);

	const virtualizer = useVirtualizer({
		// Zero while the list renders whole: the virtualizer then does no work on the common case.
		count: windowed ? turns.length : 0,
		getScrollElement: () => scrollRef.current,
		estimateSize: () => ESTIMATED_TURN_PX,
		// Keyed by message id, not by index.
		getItemKey: useCallback(
			(index: number) => turns[index]?.id ?? index,
			[turns],
		),
		scrollMargin,
		// Turns are tall — ~1.5 fit a 662px viewport — so 3 either side is 1.5 screens of runway.
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
						<h2 className="sr-only">{guideName}</h2>
						<Suspense fallback={<CardLoading />}>
							{/*
							  Switched on the prompt kind rather than chained ternaries.
							  The two-way version fell through to the word scramble for
							  anything it did not recognise, which is how `millionaire` --
							  named in the directive union with nothing behind it --
							  rendered as a scramble and then failed against an engine that
							  had never heard of it.
							*/}
							{(() => {
								const shared = {
									threadId: game.threadId,
									state: game.state,
									onChanged: game.onChanged,
									onSummary: game.onSummary,
								};
								switch (game.state.prompt.kind) {
									case "statement":
										return <TrueFalse {...shared} />;
									case "quiz":
										return <Millionaire {...shared} soundOn={gameSound} />;
									case "hangman":
										return <Hangman {...shared} soundOn={gameSound} />;
									default:
										return <WordScramble {...shared} />;
								}
							})()}
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
						<h2 className="sr-only">{guideName}</h2>
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
					guideName={guideName}
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
				guideName={guideName}
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
		<div
			className="transcript"
			data-has-table={hasTable || undefined}
			ref={listRef}
		>
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
				/* The guide's orb stays; what sits beside it depends on whether
				   this turn has anything true to say about its progress.
				   Three dots mean "something is happening". An ASPIRE Path
				   means "here is what is happening", and it belongs HERE --
				   at the foot of the thread, where a reader waiting for an
				   answer is actually looking. Above the transcript it would be
				   off-screen by the third turn of any real conversation. */
				<div className="thinking">
					<div className="orb orb--thinking" />
					{path ? (
						<AspirePath path={path} />
					) : (
						<div className="thinking__dots" aria-hidden="true">
							<i />
							<i />
							<i />
						</div>
					)}
				</div>
			) : null}

			{chips.length > 0 ? (
				// Laid out through the reveal, inert and invisible until the answer settles.
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
	guideName,
	message,
	directiveContext,
	onRegenerate,
	playback,
	discards,
	arriving,
	revealing,
}: {
	guideName: string;
	message: Extract<ChatMessage, { role: "assistant" }>;
	directiveContext: DirectiveContext;
	/** `simple` forces the plain-words answer regardless of the composer toggle. */
	onRegenerate: (messageId: number, simple?: boolean) => void;
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
				<h2 className="sr-only">{guideName}</h2>
				{message.blocks.map((block, index) => (
					// biome-ignore lint/suspicious/noArrayIndexKey: positional by design
					<Block key={index} block={block} revealing={revealing} />
				))}
				{/* Between prose and tail: a widget answers the question the paragraph raises. */}
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
				{/* Laid out from the reveal's first frame rather than mounting when it completes. */}
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

	if (block.kind === "table") {
		return (
			<ResponseTable
				header={block.header}
				rows={block.rows}
				revealing={revealing}
			/>
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

/**
 * A teaching-activity list, one card per activity.
 *
 * The educator answers are sequences -- an activity with a setup, a first step,
 * an outcome, a teaching point -- and a wide table is the wrong shape. The
 * first cell names the activity and becomes the card title; each other cell is
 * a labelled row, so "New base: EC$1,050" reads as a fact about that activity
 * rather than a column a reader tracks across a grid.
 */
function ActivityCards({
	header,
	rows,
	revealing,
}: {
	header: Array<string>;
	rows: Array<Array<string>>;
	revealing: boolean;
}) {
	return (
		<div className="activity-cards">
			{rows.map((row, rowIndex) => (
				// biome-ignore lint/suspicious/noArrayIndexKey: positional by design
				<article className="activity-card" key={rowIndex}>
					<h4 className="activity-card__title">
						<Rich text={row[0] ?? ""} revealing={revealing} />
					</h4>
					<dl className="activity-card__fields">
						{row.slice(1).map((cell, colIndex) => (
							// biome-ignore lint/suspicious/noArrayIndexKey: positional by design
							<div className="activity-card__field" key={colIndex}>
								<dt>
									<Rich
										text={header[colIndex + 1] ?? ""}
										revealing={revealing}
									/>
								</dt>
								<dd>
									<Rich text={cell} revealing={revealing} />
								</dd>
							</div>
						))}
					</dl>
				</article>
			))}
		</div>
	);
}

/**
 * A table that stays readable at any width.
 *
 * THREE BEHAVIOURS, one component. A narrow table (<= 3 columns) is a normal
 * table. A wide one scrolls horizontally inside its own wrap rather than
 * crushing every column -- `.response-table` is `width: max-content`, so the
 * columns take the room they need and the WRAP scrolls. And on a phone or a
 * tablet, the CSS restacks each row into a labelled card, which is why every
 * `<td>` carries its column heading in `data-label`: the heading has to travel
 * with the value once the header row is gone.
 *
 * Cells render through `Rich`, so a currency value inside a cell gets the same
 * `.nowrap` protection it gets in prose, and a link in a cell still links.
 */
function ResponseTable({
	header,
	rows,
	revealing,
}: {
	header: Array<string>;
	rows: Array<Array<string>>;
	revealing: boolean;
}) {
	const columns = Math.max(header.length, ...rows.map((r) => r.length));

	// A complex table -- 4+ columns -- is almost always a teaching activity
	// list, not a data grid: an Azuri "Activity | Setup | Interest | New base |
	// Next step" reads far better as one card per activity than a wide grid
	// squeezed into the chat. Simple 2-3 column data tables stay tables.
	if (columns >= 4 && rows.length > 0) {
		return <ActivityCards header={header} rows={rows} revealing={revealing} />;
	}

	return (
		// A section with a label is an implicit region.
		<section
			className="response-table-wrap"
			aria-label="Table, scroll sideways to see more"
			// Deliberate: a scrollable area must be focusable, or a keyboard user
			// cannot scroll a table wider than the column.
			// biome-ignore lint/a11y/noNoninteractiveTabindex: a scroll region must take focus
			tabIndex={0}
			data-cols={columns}
		>
			<table className="response-table">
				{header.some((cell) => cell) && (
					<thead>
						<tr>
							{header.map((cell, index) => (
								// biome-ignore lint/suspicious/noArrayIndexKey: positional by design
								<th key={index} scope="col">
									<Rich text={cell} revealing={revealing} />
								</th>
							))}
						</tr>
					</thead>
				)}
				<tbody>
					{rows.map((row, rowIndex) => (
						// biome-ignore lint/suspicious/noArrayIndexKey: positional by design
						<tr key={rowIndex}>
							{row.map((cell, colIndex) => (
								<td
									// biome-ignore lint/suspicious/noArrayIndexKey: positional by design
									key={colIndex}
									// Carries the heading into the stacked-card layout on narrow widths.
									data-label={header[colIndex] ?? ""}
								>
									<Rich text={cell} revealing={revealing} />
								</td>
							))}
						</tr>
					))}
				</tbody>
			</table>
		</section>
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
				return <span key={index}>{protectTokens(node.text)}</span>;
			})}
		</>
	);
}

/**
 * Currency, numbers, percentages and dates, kept on one line.
 *
 * "EC$1,050" is one token with no spaces, so normal wrapping never splits it --
 * but a tight table cell with an aggressive break would, turning it into
 * "EC$1,05 / 0". Wrapping each such token in `.nowrap` is the belt to the
 * cell CSS's braces: the value is atomic wherever it lands.
 */
const PROTECTED_TOKEN =
	/(EC\$\s?[\d,]+(?:\.\d+)?|\$\s?[\d,]+(?:\.\d+)?|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?\s?%|\d+\s?percent\b|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})/gi;

function protectTokens(text: string): Array<ReactNode> {
	const out: Array<ReactNode> = [];
	let last = 0;
	let key = 0;
	for (const match of text.matchAll(PROTECTED_TOKEN)) {
		const start = match.index ?? 0;
		if (start > last) out.push(text.slice(last, start));
		out.push(
			<span key={`n${key}`} className="nowrap">
				{match[0]}
			</span>,
		);
		key += 1;
		last = start + match[0].length;
	}
	if (last < text.length) out.push(text.slice(last));
	return out;
}

/**
 * Where an answer came from, and how to go and read it.
 *
 * Closed by default and one tap to open, because most readers do not want it and
 * the ones who do want it badly. What changed here is how easy it is to find:
 * it was a grey pill reading "3 sources" that looked like metadata, and it now
 * says what it is, in the brand's own colour, with the count as a badge.
 *
 * One entry per SOURCE, not per row. The server cites the knowledge-base rows
 * it used, and four rows off the ASPIRE FAQ page are four rows and one source —
 * so they group under one heading with the extracts beneath it, rather than
 * printing the same link four times. The count is the number of sources, which
 * is the number a reader would say out loud.
 *
 * The panel is deliberately plain. Everything under a heading is corpus text —
 * the row's own question and its own words — so there is nothing to summarise,
 * and a child reading it should meet the same sentence the assistant read.
 *
 * The heading is a link only when there is something real to open. A source
 * with no public page (the programme's own teaching material), a row whose
 * stored URL would not validate, and a reader whose persona is shown no links
 * all render the same way: named, not linked. Named-but-not-linked is the
 * honest outcome, and it is never a fabricated URL.
 *
 * There is no "no sources" state, and that is a property rather than an
 * omission: the server builds this panel from the intersection of what was
 * cited and what was retrieved, so an answer with nothing behind it is declined
 * before it reaches here. Nothing on this path can invent a row.
 */
function Sources({ sources }: { sources: Array<Source> }) {
	if (sources.length === 0) return null;
	const groups = groupSources(sources);
	if (groups.length === 0) return null;

	return (
		// Opening grows the thread by the panel's height, which scroll-follow does not cover.
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
				<span className="sources__label">{say("sources")}</span>
				<span className="sources__count">{groups.length}</span>
				{/* The badge reads as a bare number otherwise, and it counts
				    sources now rather than rows — worth saying out loud. */}
				<span className="sr-only">
					{groups.length === 1 ? "source" : "sources"}
				</span>
				<ChevronDownIcon size={14} className="sources__chevron" />
			</summary>

			<ol className="sources__list">
				{groups.map((group, index) => (
					<li key={group.key} className="source">
						{/* Numbered, so "the second one" is a thing a reader can say. */}
						<span className="source__n" aria-hidden="true">
							{index + 1}
						</span>
						<div className="source__body">
							<SourceHead group={group} />
							{group.extracts.map((extract, position) =>
								// A row with nothing to show is nothing to show. Without this
								// it renders as an empty bordered gap under the heading.
								extract.question || extract.kbId || extract.snippet ? (
									// biome-ignore lint/suspicious/noArrayIndexKey: two rows of one page can repeat both id and text; position is their identity
									<div key={position} className="source__extract">
										{extract.question || extract.kbId ? (
											<p className="source__head">
												{extract.question ? (
													<span className="source__label">
														{extract.question}
													</span>
												) : null}
												{extract.kbId ? (
													<span className="source__ref">{extract.kbId}</span>
												) : null}
											</p>
										) : null}
										{extract.snippet ? (
											<p className="source__text">{extract.snippet}</p>
										) : null}
									</div>
								) : null,
							)}
						</div>
					</li>
				))}
			</ol>
		</details>
	);
}

/**
 * A source's own name, as a link where there is one.
 *
 * `target="_blank"` and `rel="noopener noreferrer"` for the same reason every
 * other outbound link in the app carries them, and because leaving mid-answer
 * would lose the conversation. The domain sits under the title rather than
 * beside it: it is the thing a cautious reader checks before tapping, and a
 * title long enough to wrap should not push it off the row.
 */
function SourceHead({ group }: { group: GroupedSource }) {
	if (!group.label && !group.domain) {
		// Attributed to nothing. The extracts below still stand on their own,
		// and inventing a heading for them would be the one thing this panel
		// must never do.
		return null;
	}

	const name = group.label || group.domain;
	if (!group.href) {
		// No domain line. A host is a URL written shorter, and this branch is
		// where a reader who is shown no links ends up — printing the domain
		// beneath the name would hand them the thing the gate withheld. The
		// server blanks it too; this is the second of the two.
		return (
			<p className="source__origin">
				<span className="source__site">{name}</span>
			</p>
		);
	}

	return (
		<p className="source__origin">
			<a
				className="source__site source__site--link"
				href={group.href}
				target="_blank"
				rel="noopener noreferrer"
			>
				{name}
				<ExternalLinkIcon className="source__out" aria-hidden="true" />
				{/* Says where it goes, for a reader who cannot see the icon.
				    A row stored before the domain existed keeps its link and
				    loses its host, and "(opens  in a new tab)" is the one thing
				    this sentence must not say. */}
				<span className="sr-only">
					{group.domain
						? `(opens ${group.domain} in a new tab)`
						: "(opens in a new tab)"}
				</span>
			</a>
			{group.domain ? (
				<span className="source__domain">{group.domain}</span>
			) : null}
		</p>
	);
}

function Failure({
	guideName,
	text,
	canRetry,
	tone,
	onRetry,
	arriving,
}: {
	guideName: string;
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
				{/* Every other assistant turn carries this; without it heading navigation skips failures. */}
				<h2 className="sr-only">{guideName}</h2>
				{/* No role="alert" here. */}
				<p className="failure" data-tone={tone}>
					{stopped ? <StopIcon /> : <AlertIcon />}
					<span>{text}</span>
				</p>
				{canRetry ? (
					<div className="answer-actions">
						<button type="button" className="text-btn" onClick={onRetry}>
							<RetryIcon />
							{/* Nothing went wrong, so not "Try again" — the question is still there to ask. */}
							{stopped ? say("askAgain") : say("tryAgain")}
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
	/** `simple` forces the plain-words answer regardless of the composer toggle. */
	onRegenerate: (messageId: number, simple?: boolean) => void;
	playback: Playback;
	messageId: number;
	discards: number;
}) {
	const [copied, setCopied] = useState(false);
	// Two-step only when something would actually be lost. Holds WHICH action is
	// armed, because both buttons discard the same messages and a shared boolean
	// would let one button confirm the other.
	const [confirming, setConfirming] = useState<"again" | "simpler" | null>(
		null,
	);
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
		const timer = setTimeout(() => setConfirming(null), 5000);
		return () => clearTimeout(timer);
	}, [confirming]);

	function rerun(which: "again" | "simpler") {
		if (discards > 0 && confirming !== which) {
			setConfirming(which);
			return;
		}
		setConfirming(null);
		onRegenerate(messageId, which === "simpler" ? true : undefined);
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
						{playing ? say("playing") : paused ? say("paused") : say("play")}
					</button>
					{playing ? <PlayingStars /> : null}
				</>
			) : null}

			{/* Labelled like its neighbours: a lone bare icon is the one a reader must guess at. */}
			<button type="button" className="text-btn" onClick={copy}>
				{copied ? <CheckIcon /> : <CopyIcon />}
				{copied ? say("copied") : say("copy")}
			</button>

			{/* The per-answer half of "Explain it simply".
			    The composer toggle shapes the NEXT answer; this one is about the
			    answer already on screen, which is what the label leads a reader
			    to expect. It re-asks the same question with the plain-words
			    instruction on, so the facts and the sources are the ones that
			    were already checked -- it is not a fresh question. */}
			<button
				type="button"
				className="text-btn"
				data-confirming={confirming === "simpler" || undefined}
				onClick={() => rerun("simpler")}
				title="Say this again in simpler words"
			>
				<SparkIcon />
				{confirming === "simpler"
					? `Simplify and drop the ${discards} ${discards === 1 ? "message" : "messages"} after it?`
					: say("simpler")}
			</button>

			{/* "Ask again", not "Try again": under a good answer the latter reads as "you got it wrong". */}
			<button
				type="button"
				className="text-btn"
				data-confirming={confirming === "again" || undefined}
				onClick={() => rerun("again")}
			>
				<RetryIcon />
				{confirming === "again"
					? `Ask again and drop the ${discards} ${discards === 1 ? "message" : "messages"} after it?`
					: say("askAgain")}
			</button>
		</div>
	);
}
