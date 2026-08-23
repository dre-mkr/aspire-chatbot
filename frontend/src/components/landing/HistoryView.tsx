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
	const {
		data: conversations,
		isPending,
		isError,
		refetch,
	} = useQuery(conversationsQuery(session?.userId ?? "anon"));
	const groups = conversations ? groupByRecency(conversations) : [];
	const open = (threadId: string) =>
		onSelectChat
			? onSelectChat(threadId)
			: navigate({ to: "/chat/$chatId", params: { chatId: threadId } });

	return (
		<div className="view">
			<ViewHeader onBack={onBack} />

			<main className="view__main">
				<div className="view__head">
					<h1 className="view__title">Chat history</h1>
					<p className="view__lede">
						Review your past conversations and learning modules.
					</p>
				</div>

				{/* There was one branch here, and it said "You haven't started any
				 * conversations yet." It said it while the list was still loading, and
				 * it said it when the request failed — so a reader with a year of
				 * conversations behind a flaky connection was told they had none.
				 * Three states now, and the empty one is only reached when the list
				 * really did arrive and really was empty. */}
				{isPending ? (
					<div className="history__list" aria-busy="true">
						<span className="sr-only">Loading your conversations</span>
						{[0, 1, 2].map((n) => (
							<div className="history__row history__row--ghost" key={n}>
								<span className="history__mark" />
								<span className="history__ghost-lines">
									<span />
									<span />
								</span>
							</div>
						))}
					</div>
				) : isError ? (
					<div className="history__empty" role="alert">
						<i
							className="ph-duotone ph-cloud-warning history__empty-mark"
							aria-hidden="true"
						/>
						<p>We could not load your conversations just now.</p>
						<button
							type="button"
							className="history__retry"
							onClick={() => refetch()}
						>
							Try again
						</button>
					</div>
				) : groups.length === 0 ? (
					<div className="history__empty">
						<i
							className="ph-duotone ph-chat-circle history__empty-mark"
							aria-hidden="true"
						/>
						<p>You haven&rsquo;t started any conversations yet.</p>
						<p className="history__empty-hint">
							Ask ASPIRE a question and it will be waiting here next time.
						</p>
					</div>
				) : (
					<div className="history__groups">
						{groups.map((group) => (
							<section key={group.label}>
								<h2 className="history__group-label">{group.label}</h2>
								<div className="history__list">
									{group.items.map((chat) => (
										<button
											type="button"
											key={chat.threadId}
											onClick={() => open(chat.threadId)}
											className="history__row"
										>
											<span className="history__mark" aria-hidden="true">
												<i className="ph-duotone ph-chat-text" />
											</span>
											<span className="history__text">
												<span className="history__title">
													{chat.title || "Untitled conversation"}
												</span>
												<span className="history__date">
													{new Date(chat.updatedAt).toLocaleDateString()}
												</span>
											</span>
											<i
												className="ph-bold ph-caret-right history__chevron"
												aria-hidden="true"
											/>
										</button>
									))}
								</div>
							</section>
						))}
					</div>
				)}
			</main>
		</div>
	);
}
