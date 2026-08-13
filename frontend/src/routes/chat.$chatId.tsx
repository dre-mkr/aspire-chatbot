import { createFileRoute } from "@tanstack/react-router";
import { ChatScreen } from "#/components/chat/ChatScreen";
import { peekPendingTurn } from "#/lib/aspire/handoff";
import { conversationQuery } from "#/lib/aspire/queries";
import { validateAnswerSearch } from "#/lib/aspire/search";
import { currentSession } from "#/lib/aspire/session";

export const Route = createFileRoute("/chat/$chatId")({
	// Full-document SSR: the first paint of every conversation.
	ssr: true,
	validateSearch: validateAnswerSearch,
	/**
	 * Warms the cache, and never blocks. `defaultPendingComponent` is a
	 * full-screen takeover after 300ms, so awaiting anything here would put a
	 * spinner over every chat you open.
	 */
	loader: ({ context, params }) => {
		// A conversation minted one tick ago, which the service has never heard of.
		if (peekPendingTurn(params.chatId)) return;
		if (!currentSession()) return;
		void context.queryClient
			.ensureQueryData(conversationQuery(params.chatId))
			.catch(() => undefined);
	},
	component: ChatScreen,
});
