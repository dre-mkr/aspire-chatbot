import { createFileRoute } from "@tanstack/react-router";
import { conversationQuery } from "#/lib/aspire/queries";
import { currentSession } from "#/lib/aspire/session";

export const Route = createFileRoute("/_shell/chat/$chatId")({
	// Full-document SSR.
	ssr: true,
	loader: ({ context, params }) => {
		if (!currentSession()) return;
		void context.queryClient
			.ensureQueryData(conversationQuery(params.chatId))
			.catch(() => undefined);
	},
	component: () => null,
});
