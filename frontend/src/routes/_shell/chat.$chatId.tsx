import { createFileRoute } from "@tanstack/react-router";
import { deviceId } from "#/lib/aspire/device";
import { conversationQuery } from "#/lib/aspire/queries";

/**
 * One conversation, at `/chat/:id`.
 *
 * Renders nothing: its whole job is to put `chatId` in the match so the shell
 * can read it. That is what makes a conversation addressable, restorable on
 * refresh, and reachable by the back button.
 *
 * The loader is what keeps switching chats feeling the way it always has.
 * History used to be localStorage, so opening a conversation was synchronous —
 * the transcript was simply there. Now it comes from the service, and without
 * this the rail would hand you a blank thread for one round trip on every
 * switch. Warming the cache before the navigation commits means the shell finds
 * the transcript already in hand and reopens it in a single commit, exactly as
 * it did when it was reading from the browser.
 *
 * Deliberately not awaited: the route does not render the transcript, the shell
 * does, and a blocking loader would trade a blank thread for a stalled
 * navigation. The shell falls through to its own fetch when the cache is cold,
 * so a link opened from nowhere still works — it is the only path that ever
 * waits. `defaultPreload: "intent"` means hovering a rail row usually resolves
 * this before the click.
 */
export const Route = createFileRoute("/_shell/chat/$chatId")({
	loader: ({ context, params }) => {
		// Skipped on the server, and not as an optimisation. This browser's
		// identity lives in its own storage, so a request made during SSR carries
		// no principal and the service correctly refuses it. Warming the cache
		// with that refusal would be worse than not warming it at all.
		if (!deviceId()) return;
		void context.queryClient
			.ensureQueryData(conversationQuery(params.chatId))
			// A conversation this identity cannot read is not an error here. The
			// shell reconciles the address and sends the reader to the empty state.
			.catch(() => undefined);
	},
	component: () => null,
});
