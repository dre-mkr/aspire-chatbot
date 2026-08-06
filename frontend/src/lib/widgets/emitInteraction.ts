/**
 * Reporting what a child did with a widget, once, when they stop.
 *
 * ## On settle, not on tick
 *
 * A slider drag fires an input event on every frame. Sending one interaction
 * per frame would be sixty requests a second, and -- worse than the cost -- the
 * agent's reply would be about whichever frame arrived last rather than about
 * where the child actually stopped. "You found EC$180" is a good sentence;
 * "you found EC$47, EC$52, EC$58, ..." is noise nobody reads.
 *
 * So the emitter debounces to ~800ms of stillness and coalesces everything in
 * between into one event carrying the FINAL state.
 *
 * ## Attempts are counted, not the frames
 *
 * `attempts` counts distinct interaction bursts -- how many times the child
 * came back and moved something -- which is a meaningful number. The frames
 * within a burst are not.
 *
 * ## Skipping is silence
 *
 * A widget the child never touched emits nothing. Not `completed: false`, not
 * an "abandoned" event: nothing. The agent then continues without comment,
 * which is the rule -- no guilt, no nagging, no "you didn't try the slider".
 */
import type { WidgetInteraction } from "../stream/types";

/** How long everything must be still before the interaction counts as settled. */
export const SETTLE_MS = 800;

export type InteractionSink = (
	interaction: WidgetInteraction,
) => void | Promise<void>;

interface Pending {
	timer: ReturnType<typeof setTimeout>;
	attempts: number;
	firstTouchAt: number;
}

/**
 * One emitter per conversation. Tracks a debounce per widget instance.
 *
 * Keyed on `widget_kind:concept_id` rather than on a widget id, because a
 * widget has no id -- it is a payload inside a directive, and two widgets of
 * the same kind about the same concept in one turn is a case gate 7 already
 * forbids.
 */
export class InteractionEmitter {
	private readonly pending = new Map<string, Pending>();

	constructor(
		private readonly sink: InteractionSink,
		private readonly settleMs: number = SETTLE_MS,
	) {}

	/**
	 * Record a change. Emits once the child has been still for `settleMs`.
	 *
	 * `completed` is the widget saying the interaction reached its natural end
	 * -- the final period of a growth stack, "Got it" on anything. It bypasses
	 * the debounce because there is nothing left to wait for.
	 */
	touch(
		interaction: Omit<WidgetInteraction, "type" | "attempts" | "dwell_ms">,
		options: { immediate?: boolean } = {},
	): void {
		const key = `${interaction.widget_kind}:${interaction.concept_id}`;
		const existing = this.pending.get(key);
		const now = Date.now();

		if (existing) clearTimeout(existing.timer);

		const attempts = (existing?.attempts ?? 0) + 1;
		const firstTouchAt = existing?.firstTouchAt ?? now;

		const fire = () => {
			this.pending.delete(key);
			void this.sink({
				type: "widget_interaction",
				...interaction,
				attempts,
				dwell_ms: Date.now() - firstTouchAt,
			});
		};

		if (options.immediate) {
			fire();
			return;
		}

		this.pending.set(key, {
			timer: setTimeout(fire, this.settleMs),
			attempts,
			firstTouchAt,
		});
	}

	/**
	 * Drop everything outstanding without emitting.
	 *
	 * Called when the conversation moves on. An interaction that settles after
	 * the turn it belonged to would arrive as a comment on the wrong answer.
	 */
	cancel(): void {
		for (const { timer } of this.pending.values()) clearTimeout(timer);
		this.pending.clear();
	}

	/** Whether anything is waiting. Used by the tests and by unmount handling. */
	get outstanding(): number {
		return this.pending.size;
	}
}

/**
 * Send one interaction to the service.
 *
 * A widget interaction is a TURN: it enters the graph as a tool result and the
 * agent must respond to it within one turn, referencing the child's actual
 * numbers. That is why this posts to the chat endpoint rather than to a
 * telemetry sink -- the response is the point.
 */
export async function postInteraction(
	interaction: WidgetInteraction,
	options: { apiUrl: string; token: string; signal?: AbortSignal },
): Promise<Response> {
	return fetch(`${options.apiUrl}/v2/widget/interaction`, {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Authorization: `Bearer ${options.token}`,
		},
		body: JSON.stringify(interaction),
		signal: options.signal,
	});
}
