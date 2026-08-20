/** Directive type to component, with a fallback that renders nothing. */
import { Link } from "@tanstack/react-router";
import { type ReactNode, useEffect, useState } from "react";
import { type AspireVideo, fetchVideos } from "#/lib/aspire/videos";
import type {
	ChartDirective,
	CitationsDirective,
	Directive,
	EscalatedDirective,
	ProgressDirective,
	ReviewCardDirective,
	SignupDirective,
	UploadDirective,
	VideoDirective,
	WidgetDirective,
	WidgetInteraction,
} from "../../lib/stream/types";
import { WidgetRenderer } from "../widgets/WidgetRenderer";
import { ReviewCard } from "./ReviewCard";
import { UploadCard } from "./UploadCard";
import { VideoCard } from "./VideoPanel";

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
	"signup",
	"upload",
	"review_card",
	"chart",
	"progress",
	"citations",
	"escalated",
	"widget",
	"video",
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
		case "widget":
			return (
				<WidgetRenderer
					widget={(directive as WidgetDirective).payload}
					onInteraction={context.onWidgetInteraction}
					// Skipping is silent by design: the agent continues without comment.
					onSkip={() => undefined}
				/>
			);

		case "video":
			return <OfferedVideo directive={directive as VideoDirective} />;

		case "citations":
			return <Citations directive={directive as CitationsDirective} />;

		case "progress":
			return <Progress directive={directive as ProgressDirective} />;

		case "escalated":
			return <Escalated directive={directive as EscalatedDirective} />;

		case "chart":
			return <Chart directive={directive as ChartDirective} />;

		case "signup":
			return <SignupCard directive={directive as SignupDirective} />;

		case "upload":
			return (
				<UploadCard
					directive={directive as UploadDirective}
					// Presign is authed with this thread's graph session token, so the card needs the thread.
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

/**
 * A video the reader said yes to.
 *
 * The directive carries an id and a title, not a source. Resolving the id
 * against `/api/videos` is what keeps the only written path on the server, and
 * it costs one small request the first time a video is accepted in a session.
 *
 * The title arrives on the directive so the card is not blank while that
 * request is in flight — the reader has just asked for this, and a gap where
 * they expected a film reads as a failure.
 */
function OfferedVideo({ directive }: { directive: VideoDirective }) {
	const [video, setVideo] = useState<AspireVideo | null>(null);
	const [failed, setFailed] = useState(false);

	useEffect(() => {
		let live = true;
		fetchVideos()
			.then((list) => {
				if (!live) return;
				const found = list.find((item) => item.id === directive.video_id);
				if (found) setVideo(found);
				else setFailed(true);
			})
			.catch(() => live && setFailed(true));
		return () => {
			live = false;
		};
	}, [directive.video_id]);

	if (failed) {
		return (
			<p className="video-offer__failed">
				That video could not be loaded. You can find it in the Videos panel.
			</p>
		);
	}
	if (!video) {
		return <p className="video-offer__loading">Loading {directive.title}…</p>;
	}
	return (
		<div className="video-offer">
			<VideoCard video={video} compact />
		</div>
	);
}

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
