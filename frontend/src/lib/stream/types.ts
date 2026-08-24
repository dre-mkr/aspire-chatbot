/** The v2 wire protocol, as types. */

/** Every event the server can send. */
export type WireEventName = "token" | "directive" | "done" | "error";

export interface TokenEvent {
	event: "token";
	data: { i: number; t: string };
}

export interface DirectiveEvent {
	event: "directive";
	data: { i: number; d: Directive };
}

export interface DoneEvent {
	event: "done";
	data: { i: number; usage: TurnUsage };
}

/** Note it carries no ordinal. */
export interface ErrorEvent {
	event: "error";
	data: { code: string; message: string };
}

export type WireEvent = TokenEvent | DirectiveEvent | DoneEvent | ErrorEvent;

export interface TurnUsage {
	elapsed_ms?: number;
	agent?: string | null;
	/** Whether this turn should be spoken. Server-decided, from the age band. */
	speak?: boolean;
	events?: number;
	widgets_emitted?: number;
	gate_failures?: Record<string, number>;
}

/* ── directives ─────────────────────────────────────────────────────────── */

export interface QuickReplyOption {
	label: string;
	value: string;
}

export interface QuickRepliesDirective {
	t: "quick_replies";
	options: Array<QuickReplyOption>;
}

export interface GameDirective {
	t: "game";
	game: "scramble" | "true_false" | "millionaire";
	concept: string;
	difficulty: 1 | 2 | 3;
}

/** Open the guided eligibility check. */
export interface EligibilityDirective {
	t: "eligibility";
	check: "aspire_eligibility";
	language: "en" | "es" | "fr";
}

/** Open the account sign-up wizard. */
export interface SignupDirective {
	t: "signup";
	role: "participant" | "guardian" | "educator" | null;
}

export interface UploadDirective {
	t: "upload";
	slot: string;
	label: string;
	accepts: Array<string>;
	max_mb: number;
	help: string;
	/** Which application this document belongs to. */
	application_id?: string;
}

export interface ReviewSection {
	title: string;
	/** `[slot, label, displayValue]`. The display value is already masked. */
	fields: Array<[string, string, string]>;
	/** Document ids only. Bytes and storage keys never ride on this. */
	documents: Array<string>;
}

export interface ReviewCardDirective {
	t: "review_card";
	sections: Array<ReviewSection>;
}

export interface CollectibleDirective {
	t: "collectible";
	name: string;
	emoji: string;
	caption: string;
	topic: string;
}

export interface PledgeDirective {
	t: "pledge";
	/** "EC$200 a month" -- already formatted. */
	amount_line: string;
	goal: string;
	button_label: string;
	/** What tapping the button sends as a plain user message. */
	button_value: string;
	pledged: boolean;
}

export interface ChartDirective {
	t: "chart";
	kind: "line" | "bar" | "stacked_bar";
	series: Array<{ label: string; points: Array<number> }>;
	x_labels: Array<string>;
	y_unit: "xcd_cents" | "count" | "rate";
}

export interface ProgressDirective {
	t: "progress";
	badge: string | null;
	streak: number;
	/** Concepts that moved this session. Never shown as a score. */
	mastery_delta: number;
}

export interface CitationsDirective {
	t: "citations";
	/** The only provenance: the inline `[ASP-xxx]` marker is stripped server-side. */
	refs: Array<{
		kb_id: string;
		title: string;
		question?: string;
		snippet?: string;
		/**
		 * Where the row came from. Read off the knowledge base's `source_url`
		 * column and validated server-side — never written by the model, and
		 * never present unless the corpus actually held one.
		 *
		 * `url` is empty for a source with no public page (the programme's own
		 * teaching material) and for a reader whose persona gets no links at
		 * all; `site`/`page` still name it in both cases, so a source is
		 * attributed even when it cannot be opened.
		 */
		source_url?: string;
		site?: string;
		page?: string;
		domain?: string;
		updated?: string;
	}>;
}

export interface EscalatedDirective {
	t: "escalated";
	ticket_id: string;
	eta: string;
}

export interface WidgetDirective {
	t: "widget";
	payload: ConceptWidget;
}

/**
 * One ASPIRE story video, to play inside the conversation.
 *
 * An id, never a URL. The card resolves it against `/api/videos`, which is the
 * same catalog the server matched on, so a path is written in exactly one
 * place and a directive can never point a reader off-site.
 */
export interface VideoDirective {
	t: "video";
	video_id: string;
	title: string;
	topic: string;
}

/** The open member. */
export interface UnknownDirective {
	t: string;
	[key: string]: unknown;
}

export type Directive =
	| QuickRepliesDirective
	| GameDirective
	| EligibilityDirective
	| SignupDirective
	| UploadDirective
	| ReviewCardDirective
	| ChartDirective
	| ProgressDirective
	| CitationsDirective
	| EscalatedDirective
	| WidgetDirective
	| VideoDirective
	| UnknownDirective
	| PledgeDirective
	| CollectibleDirective;

/* ── concept widgets ────────────────────────────────────────────────────── */

/** The only colours a widget may name. Resolved by the theme, never literal. */
export type ColourToken =
	| "neutral"
	| "accent"
	| "positive"
	| "caution"
	| "muted";

export type Unit =
	| "xcd_cents"
	| "years"
	| "months"
	| "weeks"
	| "rate"
	| "count"
	| "share";

export type Visual = "stacked_bars" | "line" | "coin_stack" | "number_only";

export type UnitIcon = "coin" | "person" | "star" | "block" | "cup" | "book";

interface WidgetBase {
	v: number;
	concept_id: string;
	title: string;
	caption: string;
	/** The same lesson in words, for a screen reader. Required, never optional. */
	a11y_text: string;
}

export interface Control {
	id: string;
	label: string;
	kind: "slider" | "stepper" | "choice";
	unit: Unit;
	min: number;
	max: number;
	default: number;
	step: number;
}

export interface SimulatorWidget extends WidgetBase {
	kind: "simulator";
	controls: Array<Control>;
	formula: string | null;
	expression: string | null;
	output_label: string;
	output_unit: Unit;
	visual: Visual;
}

export interface GrowthStackWidget extends WidgetBase {
	kind: "growth_stack";
	principal_cents: number;
	contribution_cents: number;
	rate: number;
	periods: number;
	period_label: string;
	saved_label: string;
	earned_label: string;
	reveal_line: string;
}

export interface CompareWidget extends WidgetBase {
	kind: "compare";
	panels: Array<{
		label: string;
		summary: string;
		detail: string;
		colour: ColourToken;
	}>;
	highlight: number | null;
	prompt: string;
}

export interface SortBucketsWidget extends WidgetBase {
	kind: "sort_buckets";
	items: Array<{ id: string; label: string; belongs_to: string | null }>;
	buckets: Array<{
		id: string;
		label: string;
		hint: string;
		colour: ColourToken;
		default_share: number;
	}>;
	prompt: string;
}

export interface AllocatorWidget extends WidgetBase {
	kind: "allocator";
	total_cents: number;
	buckets: Array<{
		id: string;
		label: string;
		hint: string;
		colour: ColourToken;
		default_share: number;
	}>;
	prompt: string;
	no_wrong_answer: true;
}

export interface FlowDiagramWidget extends WidgetBase {
	kind: "flow_diagram";
	steps: Array<{
		id: string;
		label: string;
		detail: string;
		colour: ColourToken;
	}>;
	edge_labels: Array<string>;
}

export interface TimelineWidget extends WidgetBase {
	kind: "timeline";
	points: Array<{
		label: string;
		caption: string;
		at: number;
		colour: ColourToken;
	}>;
	start_label: string;
	end_label: string;
}

export interface RevealCardsWidget extends WidgetBase {
	kind: "reveal_cards";
	cards: Array<{ front: string; back: string }>;
	prompt: string;
}

export interface ProportionWidget extends WidgetBase {
	kind: "proportion";
	total: number;
	highlighted: number;
	icon: UnitIcon;
	highlighted_label: string;
	remainder_label: string;
}

export interface UnknownWidget extends WidgetBase {
	kind: string;
	[key: string]: unknown;
}

export type ConceptWidget =
	| SimulatorWidget
	| GrowthStackWidget
	| CompareWidget
	| SortBucketsWidget
	| AllocatorWidget
	| FlowDiagramWidget
	| TimelineWidget
	| RevealCardsWidget
	| ProportionWidget
	| UnknownWidget;

/* ── what a widget reports back ─────────────────────────────────────────── */

export interface WidgetInteraction {
	type: "widget_interaction";
	widget_kind: string;
	concept_id: string;
	final_state: Record<string, number | string | boolean>;
	computed: Record<string, number | string>;
	attempts: number;
	dwell_ms: number;
	completed: boolean;
}

/** What continues a registration that is paused on a document. */
export interface UploadResult {
	document_id: string;
	mime?: string;
	size_bytes?: number;
	checksum?: string;
	storage_key?: string;
	skipped?: boolean;
}

/** A finished game's score, sent as its own turn (`POST /v2/game/result`). */
export interface GameResultPayload {
	game: string;
	concept_id: string;
	score: number;
	max_score: number;
	duration_s: number;
	completed: boolean;
}
