import { useQuery } from "@tanstack/react-query";
import {
	useEffect,
	useId,
	useLayoutEffect,
	useMemo,
	useRef,
	useState,
} from "react";
import { AccountControl } from "#/components/auth/AccountControl";
import {
	ClockIcon,
	DownloadIcon,
	MoreIcon,
	PanelLeftIcon,
	PencilIcon,
	PlusIcon,
	RetryIcon,
	TrashIcon,
} from "#/components/icons";
import { EducatorsView } from "#/components/landing/EducatorsView";
import { JourneyView } from "#/components/landing/JourneyView";
import { ParentsView } from "#/components/landing/ParentsView";
import {
	displayTitle,
	groupByRecency,
	type StoredConversation,
} from "#/lib/aspire/history";
import { conversationsQuery } from "#/lib/aspire/queries";
import { useSession } from "#/lib/aspire/use-session";
import { Crossfade } from "./Crossfade";
import { HelpLauncher } from "./HelpPanel";
import { VideoLauncher } from "./VideoPanel";
import { ViewLauncher } from "./ViewLauncher";

interface RailProps {
	/** Desktop: icon-only rail. Compact: drawer is closed. */
	collapsed: boolean;
	/** Off-screen entirely: zero width on the landing screen, or a closed drawer. */
	unreachable: boolean;
	activeThreadId: string | null;
	onToggle: () => void;
	onNewChat: () => void;
	onOpenPast: (conversation: StoredConversation) => void;
	/** Writes one conversation out as a text file — any of them, not just the open one. */
	onSaveConversation: (conversation: StoredConversation) => void;
	onRenameConversation: (
		conversation: StoredConversation,
		title: string,
	) => void;
	onRegenerateTitle: (conversation: StoredConversation) => void;
	/** Permanent, and confirmed in the row's own menu before it is called. */
	onDeleteConversation: (conversation: StoredConversation) => void;
	/**
	 * Start a conversation from a rail item, rather than opening a page.
	 *
	 * Games, stories and the journey are all things the assistant can already
	 * do; what was missing was a way in that did not require knowing the words.
	 * `stageFirstTurn` is the same mechanism the landing cards use.
	 */
	onSeed?: (question: string) => void;
}

export function Rail({
	collapsed,
	unreachable,
	activeThreadId,
	onToggle,
	onNewChat,
	onOpenPast,
	onSaveConversation,
	onRenameConversation,
	onRegenerateTitle,
	onDeleteConversation,
	onSeed,
}: RailProps) {
	/** The list, subscribed here rather than passed in. */
	const { session } = useSession();
	const conversations = useQuery(conversationsQuery(session?.userId ?? "anon"));
	/** Shown before the list folds. Five is what fits without crowding the nav. */
	const HISTORY_SHOWN = 5;
	const [historyExpanded, setHistoryExpanded] = useState(false);

	const history = useMemo(
		() => groupByRecency(conversations.data ?? []),
		[conversations.data],
	);

	/**
	 * The groups as shown, truncated to `HISTORY_SHOWN` unless expanded.
	 *
	 * Counted across groups rather than within them, because the reader sees one
	 * list -- five items total, not five under each heading. A group that loses
	 * every item is dropped rather than left as a bare date with nothing under it.
	 *
	 * The active thread is always kept, wherever it falls: hiding the
	 * conversation somebody is currently reading is the one omission they would
	 * notice at once.
	 */
	const { visibleHistory, hiddenCount } = useMemo(() => {
		const total = history.reduce((n, group) => n + group.items.length, 0);
		if (historyExpanded || total <= HISTORY_SHOWN) {
			return { visibleHistory: history, hiddenCount: 0 };
		}
		let budget = HISTORY_SHOWN;
		const groups = [];
		for (const group of history) {
			const items = group.items.filter((c) => {
				if (c.threadId === activeThreadId) return true;
				if (budget <= 0) return false;
				budget -= 1;
				return true;
			});
			if (items.length > 0) groups.push({ ...group, items });
		}
		const shown = groups.reduce((n, group) => n + group.items.length, 0);
		return { visibleHistory: groups, hiddenCount: total - shown };
	}, [history, historyExpanded, activeThreadId]);

	// Anything folded away has to leave the tab order too, or focus lands on controls nobody can see.
	const folded = collapsed || undefined;

	return (
		<aside
			className="rail"
			id="aspire-rail"
			aria-label="Conversations"
			inert={unreachable || undefined}
		>
			<div className="rail__head">
				{/* One logo at a time, but both always mounted. */}
				<div className="rail__logo">
					{/* The A mark IS the toggle, but only collapsed: at 76px nothing else fits beside it. */}
					<button
						type="button"
						className="rail__mark"
						onClick={onToggle}
						aria-controls="aspire-rail"
						aria-expanded={!collapsed}
						inert={!collapsed || undefined}
					>
						{/* alt="" on purpose: the button labels itself; the wordmark carries the brand. */}
						<img src="/brand/aspire-mark.png" alt="" width={40} height={40} />
						<span className="sr-only">Expand sidebar</span>
					</button>

					{/* Opacity does not remove a node from the a11y tree, so the hidden state is stated. */}
					<img
						className="rail__wordmark"
						src="/brand/aspire-wordmark.png"
						alt="ASPIRE"
						width={190}
						height={48}
						aria-hidden={collapsed || undefined}
					/>
				</div>

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

			{/* `tabIndex={-1}` while folded, and only while folded. */}
			<div className="rail__body" tabIndex={folded ? -1 : undefined}>
				{/* Not a heading: the rail is a labelled landmark, and this would outrank the page h1. */}
				<p className="rail__section-label">
					<span className="rail__section-glyph">
						<ClockIcon />
					</span>
					<span className="rail__fold">History</span>
				</p>

				{/* Four states, not two. */}
				{/* A navigation landmark, because that is what the rows are: the one
				    way to move between conversations. The label repeats the section
				    above it, which is not read out here. */}
				<nav
					className="rail__groups rail__fold"
					aria-label="Conversation history"
					inert={folded}
				>
					{conversations.isPending ? (
						<div className="rail__skeleton" aria-hidden="true">
							<i />
							<i />
							<i />
						</div>
					) : history.length === 0 ? (
						conversations.isError ? (
							<p className="rail__empty">
								Your conversations could not be loaded.{" "}
								<button
									type="button"
									className="rail__retry"
									onClick={() => void conversations.refetch()}
								>
									Try again
								</button>
							</p>
						) : (
							<p className="rail__empty">
								Your conversations will appear here once you ask something.
							</p>
						)
					) : (
						<>
							{/* FOLDED PAST FIVE, and the count is the point of the control.
							 *
							 * Every conversation rendered meant the nav below -- Videos,
							 * Stories, Learn, Games, the two audience pages -- was pushed
							 * further out of reach with every question asked. A reader who
							 * uses this product properly loses the rest of it.
							 *
							 * The active conversation is always kept, wherever it sits in
							 * the list: folding away the thread the reader is currently in
							 * would be the one omission they would notice immediately.
							 *
							 * Grouping survives the fold. `groupByRecency` returns Today,
							 * Yesterday and so on, and a truncated list that drops its
							 * headings reads as a different, shorter history rather than
							 * as the top of a longer one. */}
							{visibleHistory.map((group) => (
								<section key={group.label} aria-label={group.label}>
									<p className="rail__group-title">{group.label}</p>
									{group.items.map((conversation) => (
										<HistoryRow
											key={conversation.threadId}
											conversation={conversation}
											active={conversation.threadId === activeThreadId}
											onOpen={onOpenPast}
											onSave={onSaveConversation}
											onRename={onRenameConversation}
											onRegenerate={onRegenerateTitle}
											onDelete={onDeleteConversation}
										/>
									))}
								</section>
							))}
							{hiddenCount > 0 || historyExpanded ? (
								<button
									type="button"
									className="rail__history-toggle"
									aria-expanded={historyExpanded}
									onClick={() => setHistoryExpanded((was) => !was)}
								>
									<i
										className={`ph-bold ${historyExpanded ? "ph-caret-up" : "ph-caret-down"}`}
										aria-hidden="true"
									/>
									{historyExpanded ? "Show fewer" : `Show ${hiddenCount} more`}
								</button>
							) : null}
						</>
					)}
				</nav>
			</div>

			{/* Outside `rail__body`, so a long history cannot scroll it out of reach. */}
			<div className="rail__help">
				{/* Each of these asks a question rather than opening a page.
				 *
				 * The assistant already plays games, offers films and tracks a
				 * journey; none of it had a door. A rail item that seeds the turn
				 * lets the reader arrive at it without having to guess the phrase.
				 *
				 * Videos keeps its own panel: browsing a library is not a
				 * conversation, and `/api/videos` is unfiltered so every persona
				 * reaches it -- including the two the assistant will not offer a
				 * film to unprompted.
				 */}
				<VideoLauncher />
				{onSeed ? (
					<>
						<button
							type="button"
							className="btn-help btn-seed"
							onClick={() => onSeed("Can you tell me a story?")}
						>
							<span className="btn-help__glyph" aria-hidden="true">
								<i className="ph-duotone ph-book-open-text" />
							</span>
							<span className="rail__fold">Stories</span>
						</button>
						{/* Lessons are the point of the product and had no door at all.
						    "teach me about ..." is the phrase the tutor answers to --
						    see `tests/learning/test_learn.py` -- so the seed says it. */}
						<button
							type="button"
							className="btn-help btn-seed"
							onClick={() => onSeed("Teach me about saving.")}
						>
							<span className="btn-help__glyph" aria-hidden="true">
								<i className="ph-duotone ph-graduation-cap" />
							</span>
							<span className="rail__fold">Learn</span>
						</button>
						<button
							type="button"
							className="btn-help btn-seed"
							onClick={() => onSeed("I'd like to play a game.")}
						>
							<span className="btn-help__glyph" aria-hidden="true">
								<i className="ph-duotone ph-game-controller" />
							</span>
							<span className="rail__fold">Games</span>
						</button>
						{/* These three open the landing page's own section views in
						    place. None of them is a route -- `LandingScreen` renders
						    them behind local state -- so from inside a conversation
						    they were written, reachable from the landing, and
						    unreachable from where most readers actually are.

						    Parents and Educators sit last before How to use because
						    they are the two an adult goes looking for, and an adult
						    scans to the bottom of a rail. A child does not go looking
						    for "For Educators" at all. */}
						<ViewLauncher
							label="My Journey"
							icon="ph-duotone ph-medal"
							dialogLabel="Your financial journey"
							triggerClassName="btn-journey"
						>
							{(close) => (
								<JourneyView onBack={close} backLabel="Back to chat" />
							)}
						</ViewLauncher>
						<ViewLauncher
							label="For Parents & Guardians"
							icon="ph-duotone ph-users-three"
							ariaLabel="For parents and guardians"
							dialogLabel="For parents and guardians"
							triggerClassName="btn-parents"
						>
							{(close) => (
								<ParentsView onBack={close} backLabel="Back to chat" />
							)}
						</ViewLauncher>
						<ViewLauncher
							label="For Educators"
							icon="ph-duotone ph-chalkboard-teacher"
							dialogLabel="For teachers and educators"
							triggerClassName="btn-educators"
						>
							{(close) => (
								<EducatorsView onBack={close} backLabel="Back to chat" />
							)}
						</ViewLauncher>
					</>
				) : null}
				<HelpLauncher />
			</div>

			{/* One block, two states: an invitation signed out, the avatar and name signed in. */}
			<div className="rail__foot">
				<AccountControl variant="rail" />
			</div>
		</aside>
	);
}

/** One conversation in the rail, with its own overflow menu. */
function HistoryRow({
	conversation,
	active,
	onOpen,
	onSave,
	onRename,
	onRegenerate,
	onDelete,
}: {
	conversation: StoredConversation;
	active: boolean;
	onOpen: (conversation: StoredConversation) => void;
	onSave: (conversation: StoredConversation) => void;
	onRename: (conversation: StoredConversation, title: string) => void;
	onRegenerate: (conversation: StoredConversation) => void;
	onDelete: (conversation: StoredConversation) => void;
}) {
	const [open, setOpen] = useState(false);
	/** Viewport coordinates for the menu. */
	const [at, setAt] = useState<{ top: number; left: number } | null>(null);
	const [renaming, setRenaming] = useState(false);
	/** The menu's second face: are you sure? */
	const [confirming, setConfirming] = useState(false);
	const menuId = useId();
	/** The confirmation's sentence, which is also the menu's accessible name. */
	const askId = `${menuId}-ask`;
	const wrapRef = useRef<HTMLDivElement>(null);
	const triggerRef = useRef<HTMLButtonElement>(null);
	const inputRef = useRef<HTMLInputElement>(null);
	const cancelRef = useRef<HTMLButtonElement>(null);

	// The same stored title the bar reads, with the same fallback applied.
	const label = displayTitle(conversation);

	useEffect(() => {
		if (!renaming) return;
		inputRef.current?.focus();
		inputRef.current?.select();
	}, [renaming]);

	// The question replaces the items, so the clicked item unmounts and focus would fall to <body>.
	useEffect(() => {
		if (confirming) cancelRef.current?.focus();
	}, [confirming]);

	// Asking again next time.
	useEffect(() => {
		if (!open) setConfirming(false);
	}, [open]);

	const menuRef = useRef<HTMLDivElement>(null);

	/** A first guess, so the menu has somewhere to be while it is being measured. */
	const place = () => {
		const trigger = triggerRef.current;
		if (!trigger) return;
		const r = trigger.getBoundingClientRect();
		setAt({ top: r.bottom + 4, left: r.left });
	};

	/** Corrects the position against the menu's real height, once it exists. */
	// biome-ignore lint/correctness/useExhaustiveDependencies: confirming is the trigger, not an input — the effect re-measures the DOM it changed
	useLayoutEffect(() => {
		const menu = menuRef.current;
		const trigger = triggerRef.current;
		if (!open || !menu || !trigger || !at) return;

		const box = menu.getBoundingClientRect();
		const r = trigger.getBoundingClientRect();
		const top =
			r.bottom + 4 + box.height > window.innerHeight - 8
				? Math.max(8, r.top - box.height - 4)
				: r.bottom + 4;
		const left = Math.max(
			8,
			Math.min(r.right - box.width, window.innerWidth - box.width - 8),
		);
		if (Math.abs(top - at.top) > 1 || Math.abs(left - at.left) > 1) {
			setAt({ top, left });
		}
	}, [open, at, confirming]);

	useEffect(() => {
		if (!open) return;
		const onKey = (event: KeyboardEvent) => {
			if (event.key !== "Escape") return;
			event.stopPropagation();
			setOpen(false);
			triggerRef.current?.focus();
		};
		const onPointer = (event: PointerEvent) => {
			if (!wrapRef.current?.contains(event.target as Node)) setOpen(false);
		};
		// Fixed coordinates go stale the moment anything moves, so close rather than drift.
		const onMove = () => setOpen(false);

		window.addEventListener("keydown", onKey, true);
		window.addEventListener("pointerdown", onPointer);
		window.addEventListener("resize", onMove);
		document
			.querySelector(".rail__body")
			?.addEventListener("scroll", onMove, { passive: true });
		return () => {
			window.removeEventListener("keydown", onKey, true);
			window.removeEventListener("pointerdown", onPointer);
			window.removeEventListener("resize", onMove);
			document
				.querySelector(".rail__body")
				?.removeEventListener("scroll", onMove);
		};
	}, [open]);

	return (
		<div className="history-row" ref={wrapRef} data-open={open || undefined}>
			{renaming ? (
				<input
					ref={inputRef}
					className="history-item history-item--input"
					defaultValue={label}
					maxLength={60}
					aria-label={`Rename ${label}`}
					onBlur={(event) => {
						setRenaming(false);
						const next = event.target.value.trim();
						if (next && next !== label) onRename(conversation, next);
					}}
					onKeyDown={(event) => {
						if (event.key === "Enter") {
							event.preventDefault();
							event.currentTarget.blur();
						} else if (event.key === "Escape") {
							event.preventDefault();
							setRenaming(false);
						}
					}}
				/>
			) : (
				<button
					type="button"
					className="history-item"
					aria-current={active}
					title={label}
					onClick={() => onOpen(conversation)}
				>
					{/* The row shows the truncated question first; the generated title lands later. */}
					<Crossfade text={label} />
				</button>
			)}

			<button
				type="button"
				ref={triggerRef}
				className="history-more"
				aria-expanded={open}
				aria-controls={menuId}
				aria-label={`Actions for ${label}`}
				onClick={() => {
					if (!open) place();
					setOpen((value) => !value);
				}}
			>
				<MoreIcon />
			</button>

			{/* The rule below suggests <fieldset>, which groups form CONTROLS inside a form. */}
			{open && at ? (
				// biome-ignore lint/a11y/useSemanticElements: a popover of actions, not a form control group
				<div
					className="row-menu"
					ref={menuRef}
					id={menuId}
					role="group"
					// While the question is up the group is named BY it, so entering announces what is asked.
					aria-labelledby={confirming ? askId : undefined}
					aria-label={confirming ? undefined : `Actions for ${label}`}
					style={{ top: at.top, left: at.left }}
				>
					{confirming ? (
						/* The account menu's two-step: one sentence saying what actually happens, then the choice. */
						<>
							{/* Named, not "this chat". */}
							<p className="row-menu__confirm" id={askId}>
								Delete “{label}”? The whole conversation goes, and it cannot be
								brought back.
							</p>
							<button
								type="button"
								className="row-menu__item row-menu__item--danger"
								onClick={() => {
									setOpen(false);
									onDelete(conversation);
								}}
							>
								Yes, delete
							</button>
							<button
								type="button"
								ref={cancelRef}
								className="row-menu__item"
								onClick={() => {
									setOpen(false);
									triggerRef.current?.focus();
								}}
							>
								Keep this chat
							</button>
						</>
					) : (
						<>
							<button
								type="button"
								className="row-menu__item"
								onClick={() => {
									setOpen(false);
									setRenaming(true);
								}}
							>
								<PencilIcon />
								Rename
							</button>
							<button
								type="button"
								className="row-menu__item"
								onClick={() => {
									setOpen(false);
									onRegenerate(conversation);
								}}
							>
								<RetryIcon />
								Regenerate title
							</button>
							<button
								type="button"
								className="row-menu__item"
								onClick={() => {
									setOpen(false);
									onSave(conversation);
								}}
							>
								<DownloadIcon />
								Save chat
							</button>
							{/* Last, and separated. */}
							<button
								type="button"
								className="row-menu__item row-menu__item--danger"
								onClick={() => setConfirming(true)}
							>
								<TrashIcon />
								Delete
							</button>
						</>
					)}
				</div>
			) : null}
		</div>
	);
}