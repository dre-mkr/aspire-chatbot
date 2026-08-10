/**
 * The v2 wire protocol, as types.
 *
 * Mirrors `backend/app/schemas/directives.py` and `stream_interceptor.py`. The
 * two are kept in step by hand, and the thing that makes that safe is the
 * fallback rule rather than the discipline: an unknown `t` renders nothing (see
 * `DirectiveRegistry`), so a backend that ships a new directive before the
 * frontend knows about it degrades to prose instead of crashing.
 *
 * That property is why `Directive` has an open member. Modelling the union as
 * closed would make TypeScript insist every case is handled, which is exactly
 * the assumption that breaks the moment the two deploy separately.
 */

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

/**
 * Note it carries no ordinal.
 *
 * The ordinal sequence describes the answer's content; an error is the reason
 * there is no more of it. A client positioning by ordinal must not have to
 * reason about a gap where an error was.
 */
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

/**
 * Open the guided eligibility check.
 *
 * Carries no rule and no verdict — the card holds the audited rules and asks
 * its own questions. This is the whole turn: an eligibility directive arrives
 * with no prose beside it, because the server never asked a model to write any.
 */
export interface EligibilityDirective {
	t: "eligibility";
	check: "aspire_eligibility";
	language: "en" | "es" | "fr";
}

/**
 * Open the account sign-up wizard.
 *
 * An account is not an application: applying through the assistant happens on a
 * parent or guardian's own account, and this is how somebody who has not got one
 * is offered the step that comes first.
 *
 * `role` is which branch the wizard opens on, derived server-side from the
 * reader's own claims rather than from anything they typed. `null` means "no
 * suggestion" and lands on the ordinary participant branch.
 */
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
	/**
	 * Which application this document belongs to.
	 *
	 * Sent on to `/v2/documents/presign`, which scopes the signed PUT to it. A
	 * missing one makes the endpoint fall back to the caller's SESSION id, and
	 * the row the graph writes afterwards names the APPLICATION id — so the
	 * object lands at a key nothing ever reads back. Optional because an older
	 * server does not send it; the card then omits it and gets the old default.
	 */
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
	refs: Array<{ kb_id: string; title: string }>;
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
 * The open member.
 *
 * A directive from a newer backend arrives here rather than as a type error,
 * and the registry renders nothing for it. Deleting this member would make the
 * union closed, which reads as safer and is the opposite: it would move a
 * runtime degradation into a compile-time refusal to build.
 */
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
	| UnknownDirective;

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

/**
 * What continues a registration that is paused on a document.
 *
 * Deliberately only the few fields the server allows through: the bytes went
 * browser-to-bucket and this is the receipt, not the file. `document_id` is the
 * one that must be present -- without it the paused node has nothing to record
 * and treats the slot as skipped. Keys outside this set are dropped server-side
 * with a warning (see `ALLOWED_RESUME_KEYS` in `nodes/upload.py`).
 */
export interface UploadResult {
	document_id: string;
	mime?: string;
	size_bytes?: number;
	checksum?: string;
	storage_key?: string;
	skipped?: boolean;
}
