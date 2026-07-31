import {
	ClockIcon,
	DeviceIcon,
	PanelLeftIcon,
	PlusIcon,
} from "#/components/icons";
import type { HistoryGroup, StoredConversation } from "#/lib/aspire/history";

interface RailProps {
	/** Desktop: icon-only rail. Compact: drawer is closed. */
	collapsed: boolean;
	/**
	 * The rail is off-screen entirely — collapsed to zero width on the landing
	 * screen, or closed as a drawer. It is only hidden visually, so without this
	 * its controls stay in the tab order and focus vanishes into nothing.
	 */
	unreachable: boolean;
	history: Array<HistoryGroup>;
	activeThreadId: string | null;
	onToggle: () => void;
	onNewChat: () => void;
	onOpenPast: (conversation: StoredConversation) => void;
}

export function Rail({
	collapsed,
	unreachable,
	history,
	activeThreadId,
	onToggle,
	onNewChat,
	onOpenPast,
}: RailProps) {
	// Anything folded away has to leave the tab order too, or focus lands on
	// controls nobody can see.
	const folded = collapsed || undefined;

	return (
		<aside
			className="rail"
			id="aspire-rail"
			aria-label="Conversations"
			inert={unreachable || undefined}
		>
			<div className="rail__head">
				<button
					type="button"
					className="rail__mark"
					onClick={onToggle}
					aria-controls="aspire-rail"
					aria-expanded={!collapsed}
				>
					<img src="/brand/aspire-mark.png" alt="" width={40} height={40} />
					<span className="sr-only">
						{collapsed ? "Expand sidebar" : "Collapse sidebar"}
					</span>
				</button>

				<img
					className="rail__wordmark rail__fold"
					src="/brand/aspire-wordmark.png"
					alt="ASPIRE"
					width={190}
					height={48}
				/>

				<button
					type="button"
					className="icon-btn rail__fold rail__collapse"
					onClick={onToggle}
					inert={folded}
				>
					<PanelLeftIcon />
					<span className="sr-only">Collapse sidebar</span>
				</button>
			</div>

			<div className="rail__new">
				<button type="button" className="btn-new" onClick={onNewChat}>
					<span className="btn-new__glyph">
						<PlusIcon />
					</span>
					<span className="rail__fold">New chat</span>
				</button>
			</div>

			<div className="rail__body">
				{/* Not a heading: the rail is a labelled landmark, and a heading here
				    would sit above the page's own h1 in document order. */}
				<p className="rail__section-label">
					<span className="rail__section-glyph">
						<ClockIcon />
					</span>
					<span className="rail__fold">History</span>
				</p>

				<div className="rail__groups rail__fold" inert={folded}>
					{history.length === 0 ? (
						<p className="rail__empty">
							Your conversations will appear here once you ask something.
						</p>
					) : (
						history.map((group) => (
							<section key={group.label} aria-label={group.label}>
								<p className="rail__group-title">{group.label}</p>
								{group.items.map((conversation) => (
									<button
										key={conversation.threadId}
										type="button"
										className="history-item"
										aria-current={conversation.threadId === activeThreadId}
										onClick={() => onOpenPast(conversation)}
									>
										{conversation.title}
									</button>
								))}
							</section>
						))
					)}
				</div>
			</div>

			{/* There is no account yet, so the foot says where the transcript
			    actually lives rather than dressing up a signed-in user. */}
			<div className="rail__foot">
				<span className="rail__device" aria-hidden="true">
					<DeviceIcon />
				</span>
				<span className="rail__identity rail__fold">
					<span className="rail__name">Not signed in</span>
					<span className="rail__note">Chats are saved on this device</span>
				</span>
			</div>
		</aside>
	);
}
