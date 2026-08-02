import { createFileRoute } from "@tanstack/react-router";

/**
 * One conversation, at `/chat/:id`.
 *
 * Also renders nothing: its whole job is to put `chatId` in the match so the
 * shell can read it. That is what makes a conversation addressable, restorable
 * on refresh, and reachable by the back button.
 */
export const Route = createFileRoute("/_shell/chat/$chatId")({
	component: () => null,
});
