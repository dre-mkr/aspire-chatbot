/** Reporting what a child did with a widget, once, when they stop. */
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

/** One emitter per conversation. */
export class InteractionEmitter {
	private readonly pending = new Map<string, Pending>();

	constructor(
		private readonly sink: InteractionSink,
		private readonly settleMs: number = SETTLE_MS,
	) {}

	/** Record a change. */
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

	/** Drop everything outstanding without emitting. */
	cancel(): void {
		for (const { timer } of this.pending.values()) clearTimeout(timer);
		this.pending.clear();
	}

	/** Whether anything is waiting. Used by the tests and by unmount handling. */
	get outstanding(): number {
		return this.pending.size;
	}
}

/** Send one interaction to the service. */
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
