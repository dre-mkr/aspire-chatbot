/** `kind` and `v` to a component. */
import { Component, type ErrorInfo, type ReactNode } from "react";
import type { ConceptWidget, WidgetInteraction } from "../../lib/stream/types";
import { Allocator } from "./Allocator";
import { Compare } from "./Compare";
import { FlowDiagram } from "./FlowDiagram";
import { GrowthStack } from "./GrowthStack";
import { Proportion } from "./Proportion";
import { RevealCards } from "./RevealCards";
import { Simulator } from "./Simulator";
import { SortBuckets } from "./SortBuckets";
import { Timeline } from "./Timeline";

/** Versions this build can render. Anything else renders nothing. */
const SUPPORTED_VERSIONS = new Set([1]);

export interface WidgetProps {
	widget: ConceptWidget;
	/** Called when the interaction settles, not on every tick. */
	onInteraction: (interaction: WidgetInteraction) => void;
	/** The child skipped it. The agent continues WITHOUT COMMENT. */
	onSkip: () => void;
}

export function WidgetRenderer({ widget, onInteraction, onSkip }: WidgetProps) {
	if (!SUPPORTED_VERSIONS.has(widget.v)) {
		console.warn(
			`[aspire] widget ${widget.kind} v${widget.v} is newer than this build renders; showing prose only.`,
		);
		return null;
	}

	const started = Date.now();
	const settle = (
		finalState: Record<string, number | string | boolean>,
		computed: Record<string, number | string> = {},
		completed = true,
	) => {
		onInteraction({
			type: "widget_interaction",
			widget_kind: widget.kind,
			concept_id: widget.concept_id,
			final_state: finalState,
			computed,
			attempts: 1,
			dwell_ms: Date.now() - started,
			completed,
		});
	};

	const body = renderBody(widget, settle, onSkip);
	if (body === null) {
		console.warn(
			`[aspire] no renderer for widget kind ${widget.kind}; showing prose only.`,
		);
		return null;
	}

	return <WidgetBoundary kind={widget.kind}>{body}</WidgetBoundary>;
}

function renderBody(
	widget: ConceptWidget,
	settle: (
		state: Record<string, number | string | boolean>,
		computed?: Record<string, number | string>,
		completed?: boolean,
	) => void,
	onSkip: () => void,
): ReactNode | null {
	switch (widget.kind) {
		case "compare":
			return (
				<Compare
					widget={widget as never}
					onDone={(state) => settle(state)}
					onSkip={onSkip}
				/>
			);
		case "reveal_cards":
			return (
				<RevealCards
					widget={widget as never}
					onDone={(state) => settle(state)}
					onSkip={onSkip}
				/>
			);
		case "proportion":
			return (
				<Proportion
					widget={widget as never}
					onDone={(state) => settle(state)}
					onSkip={onSkip}
				/>
			);
		case "simulator":
			return (
				<Simulator
					widget={widget as never}
					onSettle={(state, computed) => settle(state, computed)}
					onSkip={onSkip}
				/>
			);
		case "growth_stack":
			return (
				<GrowthStack
					widget={widget as never}
					onSettle={(state, computed) => settle(state, computed)}
					onSkip={onSkip}
				/>
			);
		case "sort_buckets":
			return (
				<SortBuckets
					widget={widget as never}
					onDone={(state) => settle(state)}
					onSkip={onSkip}
				/>
			);
		case "allocator":
			return (
				<Allocator
					widget={widget as never}
					onSettle={(state, computed) => settle(state, computed)}
					onSkip={onSkip}
				/>
			);
		case "flow_diagram":
			return (
				<FlowDiagram
					widget={widget as never}
					onDone={(state) => settle(state)}
					onSkip={onSkip}
				/>
			);
		case "timeline":
			return (
				<Timeline
					widget={widget as never}
					onDone={(state) => settle(state)}
					onSkip={onSkip}
				/>
			);
		// Anything else renders NOTHING and logs.
		default:
			return null;
	}
}

/** Contains a render failure to the widget. */
class WidgetBoundary extends Component<
	{ kind: string; children: ReactNode },
	{ failed: boolean }
> {
	state = { failed: false };

	static getDerivedStateFromError() {
		return { failed: true };
	}

	componentDidCatch(error: Error, info: ErrorInfo) {
		console.error(
			`[aspire] widget ${this.props.kind} failed to render`,
			error,
			info.componentStack,
		);
	}

	render() {
		// Nothing, not a fallback message. See the module docstring.
		return this.state.failed ? null : this.props.children;
	}
}
