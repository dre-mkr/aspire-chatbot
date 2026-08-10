/** Directive type to component, with a fallback that renders nothing. */
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import {
	type EligibilityState,
	startEligibility,
} from "../../lib/aspire/eligibility";
import { type GameState, startGame } from "../../lib/aspire/games";
import type {
	ChartDirective,
	CitationsDirective,
	Directive,
	EligibilityDirective,
	EscalatedDirective,
	GameDirective,
	ProgressDirective,
	QuickRepliesDirective,
	ReviewCardDirective,
	SignupDirective,
	UploadDirective,
	WidgetDirective,
	WidgetInteraction,
} from "../../lib/stream/types";
import { WidgetRenderer } from "../widgets/WidgetRenderer";
import { QuickReplies } from "./QuickReplies";
import { ReviewCard } from "./ReviewCard";
import { UploadCard } from "./UploadCard";

/* Lazy for the same reason `Transcript` loads them lazily: the three cards are ~31KB raw between them and most… */
const EligibilityCheck = lazy(() =>
	import("./EligibilityCheck").then((m) => ({ default: m.EligibilityCheck })),
);
const TrueFalse = lazy(() =>
	import("./TrueFalse").then((m) => ({ default: m.TrueFalse })),
);
const WordScramble = lazy(() =>
	import("./WordScramble").then((m) => ({ default: m.WordScramble })),
);

export interface DirectiveContext {
	/** The conversation this directive belongs to. */
	threadId?: string;
	/** Send a message as the user. Chips and games both use it. */
	send: (value: string) => void;
	/** A widget interaction, already debounced by the widget. */
	onWidgetInteraction: (interaction: WidgetInteraction) => void;
	/** A game finished. Carries the score the agent must reference. */
	onGameResult?: (result: {
		game: string;
		concept_id: string;
		score: number;
		max_score: number;
		duration_s: number;
		completed: boolean;
	}) => void;
	/** A document was uploaded. Resumes the interrupted graph. */
	onUpload?: (
		slot: string,
		result: { document_id: string; mime: string; size_bytes: number },
	) => void;
	/** A review-card field was edited. Jumps the graph to that slot. */
	onEditSlot?: (slot: string) => void;
	onSubmit?: () => void;
	/** Speaks a card's question or verdict aloud. Never its option labels. */
	onSpeak?: (text: string) => void;
	speakAvailable?: boolean;
	locale?: string;
	isLesson?: boolean;
}

/** Types this build knows how to render. Everything else renders nothing. */
const KNOWN = new Set([
	"quick_replies",
	"game",
	"eligibility",
	"signup",
	"upload",
	"review_card",
	"chart",
	"progress",
	"citations",
	"escalated",
	"widget",
]);

/** Logged once per unknown type per session, not once per render. */
const warned = new Set<string>();

export function DirectiveView({
	directive,
	context,
}: {
	directive: Directive;
	context: DirectiveContext;
}): ReactNode {
	if (!KNOWN.has(directive.t)) {
		if (!warned.has(directive.t)) {
			warned.add(directive.t);
			console.warn(
				`[aspire] directive "${directive.t}" is not known to this build; ignoring it.`,
			);
		}
		return null;
	}

	switch (directive.t) {
		case "quick_replies":
			return (
				<QuickReplies
					options={(directive as QuickRepliesDirective).options}
					onPick={context.send}
					locale={context.locale}
					isLesson={context.isLesson}
				/>
			);

		case "widget":
			return (
				<WidgetRenderer
					widget={(directive as WidgetDirective).payload}
					onInteraction={context.onWidgetInteraction}
					// Skipping is silent by design: the agent continues without comment.
					onSkip={() => undefined}
				/>
			);

		case "citations":
			return <Citations directive={directive as CitationsDirective} />;

		case "progress":
			return <Progress directive={directive as ProgressDirective} />;

		case "escalated":
			return <Escalated directive={directive as EscalatedDirective} />;

		case "chart":
			return <Chart directive={directive as ChartDirective} />;

		case "game":
			return (
				<GameLaunch
					directive={directive as GameDirective}
					context={context}
					// Remounts when the directive names a different game, so a second "play true or false" in one conversation star…
					key={`${(directive as GameDirective).game}:${(directive as GameDirective).concept}`}
				/>
			);

		case "eligibility":
			return (
				<EligibilityLaunch
					directive={directive as EligibilityDirective}
					context={context}
				/>
			);

		case "signup":
			return <SignupCard directive={directive as SignupDirective} />;

		case "upload":
			return (
				<UploadCard
					directive={directive as UploadDirective}
					// The presign call is authenticated with this thread's graph session token, so the card needs the thread, not j…
					threadId={context.threadId}
					onUploaded={(result) =>
						context.onUpload?.((directive as UploadDirective).slot, result)
					}
				/>
			);

		case "review_card":
			return (
				<ReviewCard
					directive={directive as ReviewCardDirective}
					onEdit={(slot) => context.onEditSlot?.(slot)}
					onSubmit={() => context.onSubmit?.()}
				/>
			);

		default:
			return null;
	}
}

/* ── the small ones, inline ─────────────────────────────────────────────── */

/** The account sign-up card. */
function SignupCard({ directive }: { directive: SignupDirective }) {
	const label =
		directive.role === "guardian"
			? "Create a guardian account"
			: directive.role === "educator"
				? "Create a teacher account"
				: "Create an account";

	return (
		<div
			style={{
				marginBlockStart: "0.75rem",
				padding: "0.875rem",
				borderRadius: "0.875rem",
				background: "var(--wash-m-10)",
				border: "1px solid var(--wash-m-16)",
			}}
		>
			<p
				style={{
					margin: 0,
					fontSize: "var(--band-type, 16px)",
					fontWeight: 700,
					color: "var(--plum-deep)",
				}}
			>
				{label}
			</p>
			<p
				style={{
					margin: "0.25rem 0 0.75rem",
					fontSize: "calc(var(--band-type, 16px) - 1px)",
					color: "var(--slate)",
				}}
			>
				{directive.role === "guardian"
					? "It takes about a minute. You can start an application straight after."
					: "It takes about a minute, and your chats come with you."}
			</p>
			<Link
				to="/signup"
				search={
					typeof window === "undefined"
						? undefined
						: { next: window.location.pathname }
				}
				style={{
					display: "inline-flex",
					alignItems: "center",
					minHeight: "44px",
					padding: "0 1rem",
					borderRadius: "999px",
					background: "var(--plum)",
					color: "#fff",
					fontSize: "calc(var(--band-type, 16px) - 1px)",
					fontWeight: 600,
					textDecoration: "none",
				}}
			>
				{label}
			</Link>
		</div>
	);
}

function Citations({ directive }: { directive: CitationsDirective }) {
	return (
		<details
			style={{
				marginBlockStart: "0.5rem",
				fontSize: "calc(var(--band-type, 16px) - 2px)",
				color: "var(--quiet)",
			}}
		>
			<summary style={{ cursor: "pointer", minHeight: "44px" }}>
				Where this came from ({directive.refs.length})
			</summary>
			<ul style={{ margin: "0.5rem 0 0", paddingInlineStart: "1.25rem" }}>
				{directive.refs.map((ref) => (
					<li key={ref.kb_id}>
						<span style={{ fontFamily: "var(--font-mono)" }}>{ref.kb_id}</span>
						{ref.title ? ` — ${ref.title}` : null}
					</li>
				))}
			</ul>
		</details>
	);
}

function Progress({ directive }: { directive: ProgressDirective }) {
	return (
		<div
			style={{
				marginBlockStart: "0.75rem",
				padding: "0.875rem",
				borderRadius: "0.875rem",
				background: "var(--wash-m-10)",
				border: "1px solid var(--wash-m-16)",
			}}
		>
			<p
				style={{
					margin: 0,
					fontSize: "var(--band-type, 16px)",
					fontWeight: 700,
					color: "var(--plum-deep)",
				}}
			>
				{directive.streak > 1
					? `${directive.streak} days in a row!`
					: "Nice work today"}
			</p>
			{/* `mastery_delta` is rendered as a count of ideas worked on, never as a score. */}
			{directive.mastery_delta > 0 ? (
				<p
					style={{
						margin: "0.25rem 0 0",
						fontSize: "calc(var(--band-type, 16px) - 1px)",
						color: "var(--slate)",
					}}
				>
					You worked on {directive.mastery_delta} idea
					{directive.mastery_delta === 1 ? "" : "s"}.
				</p>
			) : null}
			{directive.badge ? (
				<p
					style={{
						margin: "0.5rem 0 0",
						fontSize: "var(--band-type, 16px)",
						fontWeight: 600,
						color: "var(--magenta)",
					}}
				>
					New badge: {directive.badge.replace(/_/g, " ")}
				</p>
			) : null}
		</div>
	);
}

function Escalated({ directive }: { directive: EscalatedDirective }) {
	return (
		<div
			style={{
				marginBlockStart: "0.75rem",
				padding: "0.875rem",
				borderRadius: "0.875rem",
				background: "var(--wash-6)",
				border: "1px solid var(--hairline)",
			}}
		>
			<p style={{ margin: 0, fontSize: "var(--band-type, 16px)" }}>
				A person has this now.
			</p>
			{/* The reference is rendered as its own element rather than left in prose. */}
			{directive.ticket_id ? (
				<p
					style={{
						margin: "0.25rem 0 0",
						fontFamily: "var(--font-mono)",
						fontWeight: 700,
						color: "var(--plum-deep)",
					}}
				>
					{directive.ticket_id}
				</p>
			) : null}
			{directive.eta ? (
				<p
					style={{
						margin: "0.25rem 0 0",
						fontSize: "calc(var(--band-type, 16px) - 1px)",
						color: "var(--slate)",
					}}
				>
					Expect a reply {directive.eta}.
				</p>
			) : null}
		</div>
	);
}

function Chart({ directive }: { directive: ChartDirective }) {
	const points = directive.series[0]?.points ?? [];
	if (points.length === 0) return null;
	const peak = Math.max(...points, 1);

	return (
		<figure style={{ margin: "0.75rem 0" }}>
			<svg
				viewBox="0 0 100 40"
				preserveAspectRatio="none"
				role="img"
				aria-label={`${directive.series[0]?.label ?? "Projection"}, rising to ${points[points.length - 1].toFixed(2)}`}
				style={{
					width: "100%",
					height: "6rem",
					background: "var(--wash-3)",
					borderRadius: "0.5rem",
				}}
			>
				<path
					d={points
						.map((value, index) => {
							const x = (index / Math.max(1, points.length - 1)) * 100;
							const y = 40 - (value / peak) * 38;
							return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
						})
						.join(" ")}
					fill="none"
					stroke="var(--magenta)"
					strokeWidth="2"
					vectorEffect="non-scaling-stroke"
				/>
			</svg>
			<figcaption
				style={{
					fontSize: "calc(var(--band-type, 16px) - 2px)",
					color: "var(--quiet)",
				}}
			>
				{directive.series[0]?.label}
			</figcaption>
		</figure>
	);
}

/** The game card. */
const ENGINE_NAME: Record<GameDirective["game"], string> = {
	scramble: "word_scramble",
	true_false: "true_false",
	millionaire: "millionaire",
};

function GameLaunch({
	directive,
	context,
}: {
	directive: GameDirective;
	context: DirectiveContext;
}) {
	const { threadId, onGameResult } = context;
	const [state, setState] = useState<GameState | null>(null);
	const [failure, setFailure] = useState<string | null>(null);
	/** What the set was worth. */
	const scored = useRef<{
		solved: number;
		total: number;
		duration_s: number;
		completed: boolean;
	}>({ solved: 0, total: 0, duration_s: 0, completed: false });

	useEffect(() => {
		if (!threadId) return;
		let live = true;
		startGame(threadId, { game_type: ENGINE_NAME[directive.game] })
			.then((game) => {
				if (!live) return;
				setState(game);
				if (game)
					scored.current = {
						solved: 0,
						total: game.prompt.total,
						duration_s: 0,
						completed: false,
					};
			})
			.catch((error: Error) => {
				if (live) setFailure(error.message);
			});
		return () => {
			live = false;
		};
	}, [threadId, directive.game]);

	if (!threadId || failure) {
		return (
			<Card>{failure ?? "The game needs a conversation to live in."}</Card>
		);
	}
	if (!state) return <CardLoading />;

	/** The set's final numbers, straight from the server's summary. */
	const summarised = (summary: {
		solved: number;
		total: number;
		duration_seconds: number;
	}) => {
		scored.current = {
			solved: summary.solved,
			total: Math.max(1, summary.total),
			duration_s: Math.max(0, Math.round(summary.duration_seconds)),
			completed: true,
		};
	};

	/** The card closed. */
	const finished = (final: GameState | null) => {
		setState(final);
		if (final) {
			scored.current = {
				...scored.current,
				solved: final.solved,
				total: final.prompt.total,
			};
			return;
		}
		onGameResult?.({
			game: directive.game,
			concept_id: directive.concept,
			score: scored.current.solved,
			max_score: Math.max(1, scored.current.total),
			duration_s: scored.current.duration_s,
			completed: scored.current.completed,
		});
	};

	return (
		<Suspense fallback={<CardLoading />}>
			{state.prompt.kind === "statement" ? (
				<TrueFalse
					threadId={threadId}
					state={state}
					onChanged={finished}
					onSummary={summarised}
				/>
			) : (
				<WordScramble
					threadId={threadId}
					state={state}
					onChanged={finished}
					onSummary={summarised}
				/>
			)}
		</Suspense>
	);
}

/** The eligibility card. */
function EligibilityLaunch({
	directive,
	context,
}: {
	directive: EligibilityDirective;
	context: DirectiveContext;
}) {
	const { threadId, onSpeak, speakAvailable } = context;
	const [state, setState] = useState<EligibilityState | null>(null);
	const [failure, setFailure] = useState<string | null>(null);

	useEffect(() => {
		if (!threadId) return;
		let live = true;
		startEligibility(threadId, directive.language)
			.then((next) => {
				if (live) setState(next);
			})
			.catch((error: Error) => {
				if (live) setFailure(error.message);
			});
		return () => {
			live = false;
		};
	}, [threadId, directive.language]);

	if (!threadId || failure) {
		return (
			<Card>{failure ?? "The check needs a conversation to live in."}</Card>
		);
	}
	if (!state) return <CardLoading />;

	return (
		<Suspense fallback={<CardLoading />}>
			<EligibilityCheck
				threadId={threadId}
				state={state}
				onChanged={setState}
				onSpeak={onSpeak}
				speakAvailable={speakAvailable}
			/>
		</Suspense>
	);
}

function Card({ children }: { children: ReactNode }) {
	return (
		<div
			style={{
				marginBlockStart: "0.75rem",
				padding: "0.875rem",
				borderRadius: "0.875rem",
				border: "1px solid var(--hairline)",
				fontSize: "var(--band-type, 16px)",
				color: "var(--slate)",
			}}
		>
			{children}
		</div>
	);
}

/* A card is a large block, and a spinner where one is about to appear reads as broken. */
function CardLoading() {
	return (
		<div
			aria-busy="true"
			aria-live="polite"
			style={{
				marginBlockStart: "0.75rem",
				minHeight: "8rem",
				borderRadius: "0.875rem",
				background: "var(--wash-3)",
				border: "1px solid var(--hairline)",
			}}
		>
			<span className="sr-only">Loading…</span>
		</div>
	);
}
