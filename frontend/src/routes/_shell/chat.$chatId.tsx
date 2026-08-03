import { createFileRoute } from "@tanstack/react-router";
import { currentSession } from "#/lib/aspire/session";
import { conversationQuery } from "#/lib/aspire/queries";

export const Route = createFileRoute("/_shell/chat/$chatId")({
	loader: ({ context, params }) => {
		if (!currentSession()) return;
		void context.queryClient
			.ensureQueryData(conversationQuery(params.chatId))
			.catch(() => undefined);
	},
	component: () => null,
});
