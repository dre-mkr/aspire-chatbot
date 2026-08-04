import { createFileRoute } from "@tanstack/react-router";
import { conversationQuery } from "#/lib/aspire/queries";
import { currentSession } from "#/lib/aspire/session";

export const Route = createFileRoute("/_shell/chat/$chatId")({
	// Full-document SSR. The transcript is fetched in the loader, so the
	// conversation arrives as HTML rather than as a blank shell that then
	// populates -- which is what makes reopening a chat feel instant.
	ssr: true,
	loader: ({ context, params }) => {
		if (!currentSession()) return;
		void context.queryClient
			.ensureQueryData(conversationQuery(params.chatId))
			.catch(() => undefined);
	},
	component: () => null,
});
