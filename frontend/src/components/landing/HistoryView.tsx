import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { groupByRecency } from "#/lib/aspire/history";
import { conversationsQuery } from "#/lib/aspire/queries";
import { useSession } from "#/lib/aspire/use-session";
import { ViewHeader } from "./ViewHeader";

export function HistoryView({
	onBack,
	onSelectChat,
}: {
	onBack: () => void;
	onSelectChat?: (threadId: string) => void;
}) {
	const navigate = useNavigate();
	// This view arrived calling `useConversationList({}).data`, which does not
	// exist -- that hook returns naming and deletion helpers, never the list.
	// The list is `conversationsQuery`, and `groupByRecency` already produces
	// the {label, items} shape the markup below was written against.
	const { session } = useSession();
	const { data: conversations } = useQuery(
		conversationsQuery(session?.userId ?? "anon"),
	);
	const groups = conversations ? groupByRecency(conversations) : [];
	const open = (threadId: string) =>
		onSelectChat
			? onSelectChat(threadId)
			: navigate({ to: "/chat/$chatId", params: { chatId: threadId } });

	return (
		<div className="flex flex-col min-h-screen bg-[#0B051D] text-white">
			<div className="border-b border-white/10">
				<ViewHeader onBack={onBack} tone="dark" />
			</div>
			<main className="flex-1 flex flex-col p-8 max-w-4xl mx-auto w-full">
				<h1 className="text-4xl font-display font-medium text-white mb-2">
					Chat History
				</h1>
				<p className="text-white/60 mb-12">
					Review your past conversations and learning modules.
				</p>

				{!groups || groups.length === 0 ? (
					<div className="text-center py-12 bg-white/5 rounded-3xl border border-white/10">
						<i className="ph-duotone ph-chat-circle text-4xl text-white/20 mb-4"></i>
						<p className="text-white/50">
							You haven't started any conversations yet.
						</p>
					</div>
				) : (
					<div className="flex flex-col gap-8">
						{groups.map((group) => (
							<div key={group.label}>
								<h2 className="text-sm font-semibold text-white/40 uppercase tracking-wider mb-4">
									{group.label}
								</h2>
								<div className="flex flex-col gap-3">
									{group.items.map((chat) => (
										<button
											type="button"
											key={chat.threadId}
											onClick={() => open(chat.threadId)}
											className="flex items-center gap-4 p-4 rounded-2xl bg-white/5 border border-white/10 hover:bg-white/10 transition-colors text-left group cursor-pointer"
										>
											<div className="w-10 h-10 rounded-full bg-[#482977]/50 flex items-center justify-center text-[#c22f99] group-hover:scale-110 transition-transform">
												<i className="ph-duotone ph-chat-text text-xl"></i>
											</div>
											<div className="flex-1 overflow-hidden">
												<h3 className="font-medium text-white truncate">
													{chat.title || "Untitled Conversation"}
												</h3>
												<p className="text-xs text-white/50 truncate">
													{new Date(chat.updatedAt).toLocaleDateString()}
												</p>
											</div>
											<i className="ph-bold ph-caret-right text-white/30 group-hover:text-white/70 transition-colors"></i>
										</button>
									))}
								</div>
							</div>
						))}
					</div>
				)}
			</main>
		</div>
	);
}
